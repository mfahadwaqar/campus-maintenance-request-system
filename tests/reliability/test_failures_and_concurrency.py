"""Reliability tests: failure handling and concurrency (lecture: TransactionTestCase for real
commit/rollback behaviour, and 'resource exhaustion and recovery' from the non-functional list).
"""

import threading
from unittest import mock

import pytest
from django.db import connection

from assignments.models import Assignment
from reports.models import Photo, Report, StatusHistory
from reports.services import ReportConflict, complete_work, start_review, submit_report

pytestmark = [pytest.mark.reliability, pytest.mark.greybox]


def run_in_threads(jobs):
    """Run each callable in its own thread (and its own database connection); return outcomes."""
    outcomes = [None] * len(jobs)
    barrier = threading.Barrier(len(jobs))

    def worker(index, job):
        try:
            barrier.wait(timeout=10)
            outcomes[index] = ("ok", job())
        except Exception as exc:
            outcomes[index] = ("error", exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=worker, args=(i, job)) for i, job in enumerate(jobs)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    return outcomes


# ------------------------------------------------------------------ concurrency
@pytest.mark.django_db(transaction=True)
def test_two_staff_acting_on_the_same_version_one_wins_and_one_gets_a_conflict(new_report, staff):
    report = new_report()
    version = report.version

    def review():
        return start_review(report_id=report.pk, actor=staff, expected_version=version, room_verified=True)

    outcomes = run_in_threads([review, review])

    kinds = sorted(kind for kind, _ in outcomes)
    errors = [value for kind, value in outcomes if kind == "error"]
    assert kinds == ["error", "ok"], outcomes
    assert isinstance(errors[0], ReportConflict)
    report.refresh_from_db()
    assert report.status == "UNDER_REVIEW"
    assert report.version == version + 1  # the version moved exactly once
    assert StatusHistory.objects.filter(report=report, new_status="UNDER_REVIEW").count() == 1


@pytest.mark.django_db(transaction=True)
def test_a_job_cannot_be_completed_twice_at_the_same_moment(in_progress_report, technician):
    report = in_progress_report
    version = report.version

    def complete():
        return complete_work(
            report_id=report.pk,
            technician=technician,
            expected_version=version,
            completion_notes="Done",
        )

    outcomes = run_in_threads([complete, complete])

    assert sorted(kind for kind, _ in outcomes) == ["error", "ok"], outcomes
    report.refresh_from_db()
    assert report.status == "CLOSED"
    assert Assignment.objects.filter(report=report, completed_at__isnull=False).count() == 1
    assert StatusHistory.objects.filter(report=report, new_status="CLOSED").count() == 1


# ------------------------------------------------------------------ atomicity and recovery
@pytest.mark.django_db(transaction=True)
def test_if_closing_fails_the_completion_is_rolled_back_too(in_progress_report, technician):
    """Completion and closure are documented as one atomic operation."""
    report = in_progress_report
    rows_before = StatusHistory.objects.filter(report=report).count()

    with mock.patch("reports.services._apply_system_transition", side_effect=RuntimeError("disk full")):
        with pytest.raises(RuntimeError):
            complete_work(
                report_id=report.pk,
                technician=technician,
                expected_version=report.version,
                completion_notes="Done",
            )

    report.refresh_from_db()
    assert report.status == "IN_PROGRESS"
    assert StatusHistory.objects.filter(report=report).count() == rows_before
    assert not Assignment.objects.filter(report=report, completed_at__isnull=False).exists()


@pytest.mark.django_db(transaction=True)
def test_if_saving_the_photo_fails_no_half_created_ticket_remains(report_data, resident, photo):
    values = report_data(photo=photo)

    with mock.patch("reports.services.private_photo_storage.save", side_effect=OSError("disk full")):
        with pytest.raises(OSError):
            submit_report(resident=resident, **values)

    assert Report.objects.count() == 0
    assert Photo.objects.count() == 0
    assert StatusHistory.objects.count() == 0


@pytest.mark.django_db
def test_a_dead_mail_server_does_not_stop_a_resident_submitting(
    django_capture_on_commit_callbacks, new_report, staff
):
    with mock.patch("notifications.services.send_mail", side_effect=TimeoutError("smtp timeout")):
        with django_capture_on_commit_callbacks(execute=True):
            report = new_report()

    assert Report.objects.filter(pk=report.pk).exists()
