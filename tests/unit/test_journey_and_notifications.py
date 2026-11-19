"""Unit tests for the progress line (branches) and notifications (mocks and stubs).

Lecture 6.1: a stub gives a dependency a fixed answer; a mock verifies that an interaction
happened. Here the email sender is replaced so no mail is sent and we can see what was asked.
"""

from unittest import mock

import pytest

from notifications.models import Notification
from reports.templatetags.ui import journey

pytestmark = pytest.mark.unit

LABELS = ["Sent", "Review", "Assigned", "In progress", "Closed"]


def states(status):
    return [step["state"] for step in journey(status)["steps"]]


# ------------------------------------------------------------------ progress line (white-box)
@pytest.mark.parametrize(
    "status,current_index",
    [("SUBMITTED", 0), ("UNDER_REVIEW", 1), ("ASSIGNED", 2), ("IN_PROGRESS", 3)],
)
def test_steps_before_the_current_one_are_done(status, current_index):
    result = states(status)

    assert result[:current_index] == ["done"] * current_index
    assert result[current_index] == "current"
    assert all(state == "" for state in result[current_index + 1 :])


@pytest.mark.parametrize("status", ["CLOSED", "COMPLETED"])
def test_a_finished_ticket_shows_every_step_done(status):
    assert states(status) == ["done"] * 5
    assert [step["label"] for step in journey(status)["steps"]] == LABELS


def test_a_rejected_ticket_has_no_progress_line():
    assert journey("REJECTED")["steps"] == []


def test_on_hold_is_shown_on_the_in_progress_step():
    steps = journey("ON_HOLD")["steps"]

    assert steps[3]["label"] == "On hold"
    assert "current" in steps[3]["state"]


def test_reopened_is_shown_on_the_assigned_step():
    steps = journey("REOPENED")["steps"]

    assert steps[2]["label"] == "Reopened"
    assert steps[1]["state"] == "done"


# ------------------------------------------------------------------ notifications (mocks)
@pytest.fixture
def send_mail():
    with mock.patch("notifications.services.send_mail") as patched:
        yield patched


@pytest.mark.django_db
def test_submitting_notifies_call_center_staff_once_each_and_not_the_resident(
    send_mail, django_capture_on_commit_callbacks, new_report, resident, staff
):
    with django_capture_on_commit_callbacks(execute=True):
        new_report()

    recipients = [call.kwargs["recipient_list"] for call in send_mail.call_args_list]
    assert recipients == [[staff.email]]
    assert resident.email not in [r for group in recipients for r in group]
    send_mail.assert_called_once()


@pytest.mark.django_db
def test_email_is_only_sent_after_the_transaction_commits(send_mail, new_report, staff):
    new_report()  # no on_commit callbacks are executed in a plain test transaction

    send_mail.assert_not_called()
    assert Notification.objects.filter(status="PENDING").exists()


@pytest.mark.django_db
def test_a_mail_failure_marks_the_notification_failed_and_does_not_raise(
    send_mail, django_capture_on_commit_callbacks, new_report, staff
):
    send_mail.side_effect = ConnectionRefusedError("smtp down")  # stub: the dependency fails

    with django_capture_on_commit_callbacks(execute=True):
        report = new_report()  # must not raise

    assert report.pk
    assert Notification.objects.filter(status="FAILED").count() == 1
    assert not Notification.objects.filter(status="SENT").exists()


@pytest.mark.django_db
def test_a_user_without_an_email_is_marked_failed_without_calling_the_mailer(
    send_mail, django_capture_on_commit_callbacks, new_report, staff
):
    User = type(staff)
    User.objects.filter(pk=staff.pk).update(email="")

    with django_capture_on_commit_callbacks(execute=True):
        new_report()

    assert Notification.objects.get(user=staff).status == "FAILED"
    send_mail.assert_not_called()


@pytest.mark.django_db
def test_inactive_users_receive_nothing(send_mail, django_capture_on_commit_callbacks, new_report, staff):
    staff.is_active = False
    staff.save()

    with django_capture_on_commit_callbacks(execute=True):
        new_report()

    assert not Notification.objects.filter(user=staff).exists()


@pytest.mark.django_db
def test_the_closing_notice_leads_with_the_outcome_and_names_the_ticket(
    send_mail, django_capture_on_commit_callbacks, in_progress_report, flow
):
    with django_capture_on_commit_callbacks(execute=True):
        report = flow.complete(in_progress_report)

    notice = Notification.objects.filter(report=report, message__contains="automatically closed").get()
    assert notice.message.startswith("Your repair is complete.")
    assert report.ticket_no in notice.message
    send_mail.assert_any_call(
        subject="Maintenance request update",
        message=notice.message,
        from_email=mock.ANY,
        recipient_list=[report.resident.email],
        fail_silently=False,
    )
