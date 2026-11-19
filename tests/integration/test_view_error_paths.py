"""Integration tests for the error paths of the staff, technician and resident pages.

Found by reading the coverage report's missing lines (lecture 6.2): the happy paths were
covered, but the 'what if it goes wrong?' branches were not. Each negative test also checks
that the refused action left the database exactly as it was.
"""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from assignments.models import Assignment
from reports.models import Report, StatusHistory
from tests.conftest import jpeg_upload

pytestmark = [pytest.mark.integration, pytest.mark.blackbox, pytest.mark.django_db]


def messages_of(response):
    return [str(m) for m in response.context["messages"]]


def snapshot(report):
    report.refresh_from_db()
    return (report.status, report.version, StatusHistory.objects.filter(report=report).count())


# ================================================================ staff pages
class TestStaffReview:
    def test_review_without_the_room_confirmation_is_refused(self, client, staff, new_report):
        report = new_report()
        before = snapshot(report)
        client.force_login(staff)

        response = client.post(
            reverse("accounts:begin_report_review", args=[report.pk]),
            {"version": report.version},
            follow=True,
        )

        assert "Refresh the request and try again." in messages_of(response)
        assert snapshot(report) == before

    def test_review_with_a_stale_version_says_the_request_changed(self, client, staff, new_report):
        report = new_report()
        stale = report.version
        client.force_login(staff)
        client.post(reverse("accounts:begin_report_review", args=[report.pk]), {"version": stale, "room_verified": "on"})
        after_first = snapshot(report)

        response = client.post(
            reverse("accounts:begin_report_review", args=[report.pk]),
            {"version": stale, "room_verified": "on"},
            follow=True,
        )

        assert any("changed" in m for m in messages_of(response))
        assert snapshot(report) == after_first


class TestPriority:
    def test_priority_can_be_set_while_under_review(self, client, staff, new_report, flow):
        report = flow.review(new_report())
        client.force_login(staff)

        response = client.post(
            reverse("accounts:update_report_priority", args=[report.pk]),
            {"version": report.version, "priority": "URGENT"},
            follow=True,
        )

        report.refresh_from_db()
        assert "Priority updated." in messages_of(response)
        assert report.priority == "URGENT"

    def test_an_invalid_priority_is_refused(self, client, staff, new_report, flow):
        report = flow.review(new_report())
        before = snapshot(report)
        client.force_login(staff)

        response = client.post(
            reverse("accounts:update_report_priority", args=[report.pk]),
            {"version": report.version, "priority": "SUPER-URGENT"},
            follow=True,
        )

        assert "Correct the priority form and try again." in messages_of(response)
        assert snapshot(report) == before

    def test_priority_cannot_change_once_the_ticket_is_assigned(self, client, staff, new_report, flow):
        report = flow.assign(new_report())
        client.force_login(staff)

        response = client.post(
            reverse("accounts:update_report_priority", args=[report.pk]),
            {"version": report.version, "priority": "LOW"},
            follow=True,
        )

        assert any("under review" in m for m in messages_of(response))
        report.refresh_from_db()
        assert report.priority == "HIGH"


class TestReject:
    def test_rejecting_with_a_reason_works(self, client, staff, new_report):
        report = new_report()
        client.force_login(staff)

        response = client.post(
            reverse("accounts:reject_report", args=[report.pk]),
            {"version": report.version, "reason": "Duplicate of an earlier request"},
            follow=True,
        )

        report.refresh_from_db()
        assert "Request rejected." in messages_of(response)
        assert report.status == "REJECTED"

    def test_rejecting_without_a_reason_is_refused(self, client, staff, new_report):
        report = new_report()
        before = snapshot(report)
        client.force_login(staff)

        response = client.post(
            reverse("accounts:reject_report", args=[report.pk]),
            {"version": report.version, "reason": ""},
            follow=True,
        )

        assert "A rejection reason is required." in messages_of(response)
        assert snapshot(report) == before

    def test_rejecting_a_ticket_that_is_already_in_progress_is_refused(self, client, staff, in_progress_report):
        before = snapshot(in_progress_report)
        client.force_login(staff)

        response = client.post(
            reverse("accounts:reject_report", args=[in_progress_report.pk]),
            {"version": in_progress_report.version, "reason": "Too late"},
            follow=True,
        )

        assert any("not allowed" in m for m in messages_of(response))
        assert snapshot(in_progress_report) == before


class TestStaffReopen:
    def test_staff_can_reopen_a_closed_ticket_inside_the_window(self, client, staff, closed_report):
        client.force_login(staff)

        response = client.post(
            reverse("accounts:officer_reopen_report", args=[closed_report.pk]),
            {"version": closed_report.version, "reason": "Resident phoned back"},
            follow=True,
        )

        closed_report.refresh_from_db()
        assert "The ticket was reopened for reassignment." in messages_of(response)
        assert closed_report.status == "ASSIGNED"

    def test_the_reopen_form_is_only_offered_inside_the_window(self, client, staff, closed_report):
        client.force_login(staff)
        page = reverse("accounts:officer_report_detail", args=[closed_report.pk])

        assert "Reopen ticket within three days" in client.get(page).content.decode()

        Assignment.objects.filter(report=closed_report, completed_at__isnull=False).update(
            completed_at=timezone.now() - timedelta(days=4)
        )
        assert "Reopen ticket within three days" not in client.get(page).content.decode()

    def test_a_reopen_after_the_window_is_refused_with_a_message(self, client, staff, closed_report):
        Assignment.objects.filter(report=closed_report, completed_at__isnull=False).update(
            completed_at=timezone.now() - timedelta(days=4)
        )
        client.force_login(staff)

        response = client.post(
            reverse("accounts:officer_reopen_report", args=[closed_report.pk]),
            {"version": closed_report.version, "reason": "Too late"},
            follow=True,
        )

        assert any("expired" in m for m in messages_of(response))
        closed_report.refresh_from_db()
        assert closed_report.status == "CLOSED"

    def test_a_reopen_without_a_reason_is_refused(self, client, staff, closed_report):
        client.force_login(staff)

        response = client.post(
            reverse("accounts:officer_reopen_report", args=[closed_report.pk]),
            {"version": closed_report.version, "reason": ""},
            follow=True,
        )

        assert "Provide a reason and refresh before reopening." in messages_of(response)


class TestAssignmentPage:
    def test_the_assign_form_opens_for_a_ticket_under_review(self, client, staff, new_report, flow):
        report = flow.review(new_report())
        client.force_login(staff)

        assert client.get(reverse("assignments:assign_report", args=[report.pk])).status_code == 200

    def test_a_submitted_ticket_cannot_be_assigned_before_review(self, client, staff, new_report):
        report = new_report()
        client.force_login(staff)

        assert client.get(reverse("assignments:assign_report", args=[report.pk])).status_code == 404

    def test_assigning_with_a_stale_version_shows_a_conflict_and_changes_nothing(
        self, client, staff, new_report, flow, unit, technician
    ):
        report = flow.review(new_report())
        stale = report.version
        flow.assign(report)  # someone else assigns first
        before = snapshot(report)
        client.force_login(staff)

        response = client.post(
            reverse("assignments:assign_report", args=[report.pk]),
            {"unit": unit.pk, "technician": technician.pk, "priority": "LOW", "version": stale},
        )

        assert response.status_code == 409
        assert "changed" in response.context["conflict_message"]
        assert snapshot(report) == before


# ================================================================ technician pages
class TestTechnicianPages:
    def test_starting_with_a_garbled_version_says_to_refresh(self, client, technician, assigned_report):
        client.force_login(technician)

        response = client.post(
            reverse("assignments:start_work", args=[assigned_report.pk]),
            {"version": "not-a-number"},
            follow=True,
        )

        assert messages_of(response)
        assigned_report.refresh_from_db()
        assert assigned_report.status == "ASSIGNED"

    def test_starting_with_a_stale_version_is_refused(self, client, technician, assigned_report):
        stale = assigned_report.version - 1
        client.force_login(technician)

        response = client.post(
            reverse("assignments:start_work", args=[assigned_report.pk]), {"version": stale}, follow=True
        )

        assert any("changed" in m for m in messages_of(response))
        assigned_report.refresh_from_db()
        assert assigned_report.status == "ASSIGNED"

    def test_completing_without_notes_shows_the_form_again_with_an_error(self, client, technician, in_progress_report):
        before = snapshot(in_progress_report)
        client.force_login(technician)

        response = client.post(
            reverse("assignments:complete_work", args=[in_progress_report.pk]),
            {"version": in_progress_report.version, "completion_notes": ""},
        )

        assert response.status_code == 200
        assert "completion_notes" in response.context["completion_form"].errors
        assert snapshot(in_progress_report) == before

    def test_completing_with_a_stale_version_gives_409(self, client, technician, in_progress_report):
        client.force_login(technician)

        response = client.post(
            reverse("assignments:complete_work", args=[in_progress_report.pk]),
            {"version": in_progress_report.version - 1, "completion_notes": "Done"},
        )

        assert response.status_code == 409
        in_progress_report.refresh_from_db()
        assert in_progress_report.status == "IN_PROGRESS"

    def test_a_completion_photo_without_the_signature_flag_is_refused(self, client, technician, in_progress_report):
        client.force_login(technician)

        response = client.post(
            reverse("assignments:complete_work", args=[in_progress_report.pk]),
            {"version": in_progress_report.version, "completion_notes": "Done", "photo": jpeg_upload()},
        )

        assert response.status_code == 200
        assert "signature" in str(response.context["completion_form"].non_field_errors()).lower()
        in_progress_report.refresh_from_db()
        assert in_progress_report.status == "IN_PROGRESS"

    def test_holding_without_a_date_shows_the_form_again(self, client, technician, in_progress_report):
        before = snapshot(in_progress_report)
        client.force_login(technician)

        response = client.post(
            reverse("assignments:put_on_hold", args=[in_progress_report.pk]),
            {"version": in_progress_report.version, "reason": "Waiting for parts"},
        )

        assert response.status_code == 200
        assert "expected_date" in response.context["hold_form"].errors
        assert snapshot(in_progress_report) == before

    def test_holding_with_a_stale_version_gives_409(self, client, technician, in_progress_report):
        client.force_login(technician)

        response = client.post(
            reverse("assignments:put_on_hold", args=[in_progress_report.pk]),
            {"version": in_progress_report.version - 1, "reason": "Parts", "expected_date": "2030-01-01"},
        )

        assert response.status_code == 409
        in_progress_report.refresh_from_db()
        assert in_progress_report.status == "IN_PROGRESS"


# ================================================================ resident pages
class TestResidentPages:
    def test_verifying_someone_elses_ticket_is_not_found(self, client, other_resident, closed_report):
        client.force_login(other_resident)

        response = client.post(
            reverse("reports:verify", args=[closed_report.pk]), {"version": closed_report.version, "rating": 5}
        )

        assert response.status_code == 404

    def test_verifying_an_open_ticket_says_it_must_be_closed_first(self, client, resident, assigned_report):
        client.force_login(resident)

        response = client.post(
            reverse("reports:verify", args=[assigned_report.pk]),
            {"version": assigned_report.version, "rating": 4},
            follow=True,
        )

        assert any("closed" in m for m in messages_of(response))

    def test_an_out_of_range_rating_is_refused_by_the_form(self, client, resident, closed_report):
        client.force_login(resident)

        response = client.post(
            reverse("reports:verify", args=[closed_report.pk]),
            {"version": closed_report.version, "rating": 9},
            follow=True,
        )

        assert "Correct the verification form and try again." in messages_of(response)
        assert closed_report.verifications.count() == 0

    def test_reopening_an_open_ticket_is_refused(self, client, resident, assigned_report):
        client.force_login(resident)
        before = snapshot(assigned_report)

        client.post(
            reverse("reports:reopen", args=[assigned_report.pk]),
            {"version": assigned_report.version, "reason": "Not closed yet"},
        )

        assert snapshot(assigned_report) == before

    def test_a_blank_comment_is_refused_with_a_message(self, client, resident, in_progress_report):
        client.force_login(resident)

        response = client.post(
            reverse("reports:comments", args=[in_progress_report.pk]), {"body": "   "}, follow=True
        )

        assert "Comment text is required." in messages_of(response)
        assert in_progress_report.comments.count() == 0

    def test_a_ticket_in_a_building_the_resident_can_pick_but_with_a_bad_room_is_refused(
        self, client, resident, building, category
    ):
        client.force_login(resident)

        response = client.post(
            reverse("reports:create"),
            {
                "category": category.pk,
                "building": building.pk,
                "room_location": "Z999",
                "room_verified": "on",
                "title": "t",
                "description": "d",
                "requested_urgency": "LOW",
            },
        )

        assert "room_location" in response.context["form"].errors
        assert Report.objects.count() == 0
