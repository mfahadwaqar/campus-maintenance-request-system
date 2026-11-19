from datetime import timedelta
from io import BytesIO
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.utils import timezone
from PIL import Image
from rest_framework.test import APITestCase

from accounts.models import (
    Building,
    RoomLocation,
    Unit,
    UnitKind,
    User,
)
from assignments.models import Assignment
from notifications.models import Notification

from .models import (
    Category,
    Comment,
    Photo,
    Report,
    StatusHistory,
    Verification,
)
from .services import (
    apply_transition,
    assign_technician,
    complete_work,
    start_review,
    start_work,
    submit_report,
)
from .storage import private_photo_storage


def image_upload(name="api-photo.jpg"):
    output = BytesIO()
    Image.new("RGB", (8, 8), color="blue").save(output, format="JPEG")
    return SimpleUploadedFile(name, output.getvalue(), content_type="image/jpeg")


def release_streamed_file(response):
    """Close a streamed photo so Windows can delete it; response.close() would also close the test database."""
    for closer in getattr(response, "_resource_closers", ()):
        closer()


class ReportApiTests(APITestCase):
    def setUp(self):
        self.building = Building.objects.create(name="Dormitory A", zone="Zone 1")
        self.category = Category.objects.create(name="API Plumbing")
        self.room, _ = RoomLocation.objects.get_or_create(
            code="A101",
            defaults={
                "name": "Dormitory A",
                "location_type": RoomLocation.LocationType.DORMITORY,
            },
        )
        self.unit = Unit.objects.create(name="API Unit", kind=UnitKind.INTERNAL)
        self.resident = User.objects.create_user(
            username="api_resident",
            email="api_resident@example.test",
            password="test-password",
            role=User.Role.RESIDENT,
        )
        self.other_resident = User.objects.create_user(
            username="api_other_resident",
            email="api_other@example.test",
            password="test-password",
            role=User.Role.RESIDENT,
        )
        self.officer = User.objects.create_user(
            username="api_officer",
            email="api_officer@example.test",
            password="test-password",
            role=User.Role.CALL_CENTER_STAFF,
        )
        self.technician = User.objects.create_user(
            username="api_technician",
            email="api_technician@example.test",
            password="test-password",
            role=User.Role.TECHNICIAN_CONTRACTOR,
            unit=self.unit,
        )
        self.other_technician = User.objects.create_user(
            username="api_other_technician",
            email="api_other_technician@example.test",
            password="test-password",
            role=User.Role.TECHNICIAN_CONTRACTOR,
            unit=self.unit,
        )

    def tearDown(self):
        for photo in Photo.objects.all():
            private_photo_storage.delete(photo.file_path)
        super().tearDown()

    def api_url(self, suffix="reports/"):
        return f"/api/{suffix}"

    def create_report(self, resident=None, **overrides):
        values = {
            "category": self.category,
            "building": self.building,
            "room_location": self.room.code,
            "room_verified": True,
            "title": "Leaking sink",
            "description": "Water is leaking under the sink.",
            "requested_urgency": "MEDIUM",
        }
        values.update(overrides)
        return submit_report(resident=resident or self.resident, **values)

    def assign_report(self, report, technician=None):
        start_review(
            report_id=report.pk,
            actor=self.officer,
            expected_version=report.version,
            room_verified=True,
        )
        report.refresh_from_db()
        return assign_technician(
            report_id=report.pk,
            technician=technician or self.technician,
            assigned_by=self.officer,
            unit=self.unit,
            priority="MEDIUM",
            expected_version=report.version,
        )

    def complete_report(self, report, *, close=True, photo=None, signed=False):
        report.refresh_from_db()
        if report.status == Report.Status.SUBMITTED:
            self.assign_report(report)
            report.refresh_from_db()
        start_work(
            report_id=report.pk,
            technician=self.technician,
            expected_version=report.version,
        )
        report.refresh_from_db()
        if close:
            complete_work(
                report_id=report.pk,
                technician=self.technician,
                expected_version=report.version,
                completion_notes="Completed the API test repair.",
                photo=photo,
                requester_signed_on_site=signed,
            )
        else:
            apply_transition(
                report,
                Report.Status.COMPLETED,
                self.technician,
                expected_version=report.version,
                completion_notes="Completed the API test repair.",
            )
        report.refresh_from_db()
        return report

    def test_api_requires_authentication_and_returns_json_401(self):
        response = self.client.get(self.api_url())

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response["Content-Type"], "application/json")

    def test_resident_can_create_and_list_only_their_own_reports(self):
        self.client.force_authenticate(self.resident)
        response = self.client.post(
            self.api_url(),
            {
                "category": self.category.pk,
                "building": self.building.pk,
                "room_location": self.room.code,
                "room_verified": True,
                "title": "Leaking sink",
                "description": "Water is leaking under the sink.",
                "requested_urgency": "MEDIUM",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        report = Report.objects.get()
        self.assertEqual(response.data["id"], report.pk)
        self.assertEqual(response.data["status"], Report.Status.SUBMITTED)
        self.assertEqual(response.data["version"], 1)
        self.assertTrue(
            StatusHistory.objects.filter(
                report=report,
                new_status=Report.Status.SUBMITTED,
                changed_by=self.resident,
            ).exists()
        )

        other_report = self.create_report(resident=self.other_resident)
        list_response = self.client.get(self.api_url())
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(list_response.data["count"], 1)
        self.assertEqual(list_response.data["results"][0]["id"], report.pk)
        self.assertNotEqual(list_response.data["results"][0]["id"], other_report.pk)

    def test_report_create_rejects_bad_reference_data(self):
        self.client.force_authenticate(self.resident)
        response = self.client.post(
            self.api_url(),
            {
                "category": self.category.pk,
                "building": self.building.pk,
                "room_location": "NOT-A-ROOM",
                "room_verified": True,
                "title": "Leaking sink",
                "description": "Water is leaking.",
                "requested_urgency": "MEDIUM",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Report.objects.count(), 0)

    def test_report_detail_hides_another_residents_report(self):
        report = self.create_report(resident=self.other_resident)
        self.client.force_authenticate(self.resident)

        response = self.client.get(self.api_url(f"reports/{report.pk}/"))

        self.assertEqual(response.status_code, 404)

    def test_officer_status_and_assignment_endpoints_enforce_version_and_audit(self):
        report = self.create_report()
        self.client.force_authenticate(self.officer)

        review_response = self.client.patch(
            self.api_url(f"reports/{report.pk}/status/"),
            {
                "status": Report.Status.UNDER_REVIEW,
                "version": report.version,
                "room_verified": True,
            },
            format="json",
        )
        self.assertEqual(review_response.status_code, 200)
        report.refresh_from_db()
        self.assertEqual(report.status, Report.Status.UNDER_REVIEW)

        stale_response = self.client.post(
            self.api_url(f"reports/{report.pk}/assign/"),
            {
                "unit": self.unit.pk,
                "technician": self.technician.pk,
                "priority": "HIGH",
                "version": 1,
            },
            format="json",
        )
        self.assertEqual(stale_response.status_code, 409)
        self.assertEqual(stale_response.data["error"], "version_conflict")
        self.assertFalse(Assignment.objects.filter(report=report).exists())
        report.refresh_from_db()
        self.assertEqual(report.status, Report.Status.UNDER_REVIEW)

        assignment_response = self.client.post(
            self.api_url(f"reports/{report.pk}/assign/"),
            {
                "unit": self.unit.pk,
                "technician": self.technician.pk,
                "priority": "HIGH",
                "version": report.version,
            },
            format="json",
        )
        self.assertEqual(assignment_response.status_code, 200)
        report.refresh_from_db()
        self.assertEqual(report.status, Report.Status.ASSIGNED)
        self.assertEqual(report.priority, "HIGH")
        self.assertEqual(
            Assignment.objects.filter(report=report, is_active=True).get().technician,
            self.technician,
        )
        self.assertEqual(StatusHistory.objects.filter(report=report).count(), 3)

    def test_technician_status_api_validates_and_runs_completion_workflow(self):
        report = self.create_report()
        self.client.force_authenticate(self.officer)
        review = self.client.patch(
            self.api_url(f"reports/{report.pk}/status/"),
            {
                "status": Report.Status.UNDER_REVIEW,
                "version": report.version,
                "room_verified": True,
            },
            format="json",
        )
        self.assertEqual(review.status_code, 200)
        report.refresh_from_db()
        assigned = self.client.post(
            self.api_url(f"reports/{report.pk}/assign/"),
            {
                "unit": self.unit.pk,
                "technician": self.technician.pk,
                "priority": "MEDIUM",
                "version": report.version,
            },
            format="json",
        )
        self.assertEqual(assigned.status_code, 200)
        report.refresh_from_db()

        self.client.force_authenticate(self.technician)
        started = self.client.patch(
            self.api_url(f"reports/{report.pk}/status/"),
            {"status": Report.Status.IN_PROGRESS, "version": report.version},
            format="json",
        )
        self.assertEqual(started.status_code, 200)
        report.refresh_from_db()

        invalid_completion = self.client.patch(
            self.api_url(f"reports/{report.pk}/status/"),
            {"status": Report.Status.COMPLETED, "version": report.version},
            format="json",
        )
        self.assertEqual(invalid_completion.status_code, 400)
        report.refresh_from_db()
        self.assertEqual(report.status, Report.Status.IN_PROGRESS)

        completed = self.client.patch(
            self.api_url(f"reports/{report.pk}/status/"),
            {
                "status": Report.Status.COMPLETED,
                "version": report.version,
                "completion_notes": "Replaced the damaged tap.",
            },
            format="json",
        )
        completion_version = report.version
        self.assertEqual(completed.status_code, 200)
        report.refresh_from_db()
        self.assertEqual(report.status, Report.Status.CLOSED)
        self.assertEqual(completed.data["status"], Report.Status.CLOSED)
        self.assertEqual(completed.data["version"], completion_version + 2)
        final_history = list(
            StatusHistory.objects.filter(report=report)
            .order_by("-pk")
            .values_list("new_status", "changed_by__username")[:2]
        )
        self.assertEqual(
            [entry[0] for entry in final_history],
            [Report.Status.CLOSED, Report.Status.COMPLETED],
        )
        self.assertEqual(final_history[0][1], "system-event-actor")
        self.assertEqual(final_history[1][1], self.technician.username)
        self.assertIsNotNone(
            Assignment.objects.get(report=report, completed_at__isnull=False).completed_at
        )

    def test_wrong_role_cannot_assign_and_nonassigned_technician_cannot_view(self):
        report = self.create_report()
        self.client.force_authenticate(self.resident)
        forbidden = self.client.post(
            self.api_url(f"reports/{report.pk}/assign/"),
            {
                "unit": self.unit.pk,
                "technician": self.technician.pk,
                "priority": "HIGH",
                "version": report.version,
            },
            format="json",
        )
        self.assertEqual(forbidden.status_code, 403)

        self.client.force_authenticate(self.other_technician)
        hidden = self.client.get(self.api_url(f"reports/{report.pk}/"))
        self.assertEqual(hidden.status_code, 404)

    def test_comments_history_and_notifications_are_scoped(self):
        report = self.create_report()
        first_comment = Comment.objects.create(
            report=report,
            author=self.resident,
            body="A public update.",
        )
        Comment.objects.create(
            report=report,
            author=self.resident,
            body="A later update.",
        )
        first_notification = Notification.objects.create(
            user=self.resident,
            report=report,
            message=f"{report.ticket_no}: was submitted.",
        )
        Notification.objects.create(
            user=self.resident,
            report=report,
            message=f"{report.ticket_no}: was assigned.",
        )
        Notification.objects.create(
            user=self.other_resident,
            report=report,
            message=f"{report.ticket_no}: was submitted.",
        )
        self.client.force_authenticate(self.resident)

        comments = self.client.get(
            self.api_url(f"reports/{report.pk}/comments/")
        )
        history = self.client.get(self.api_url(f"reports/{report.pk}/history/"))
        notifications = self.client.get(self.api_url("notifications/"))
        new_comments = self.client.get(
            self.api_url(f"reports/{report.pk}/comments/?since={first_comment.pk}")
        )
        new_notifications = self.client.get(
            self.api_url(f"notifications/?since={first_notification.pk}")
        )

        self.assertEqual(comments.status_code, 200)
        self.assertEqual(comments.data["results"][0]["body"], "A public update.")
        self.assertEqual(history.status_code, 200)
        self.assertEqual(history.data["results"][0]["new_status"], Report.Status.SUBMITTED)
        self.assertEqual(notifications.status_code, 200)
        self.assertEqual(notifications.data["count"], 2)
        self.assertEqual(notifications.data["results"][0]["report_id"], report.pk)
        self.assertEqual(new_comments.data["count"], 1)
        self.assertEqual(new_comments.data["results"][0]["body"], "A later update.")
        self.assertEqual(new_notifications.data["count"], 1)

        created_comment = self.client.post(
            self.api_url(f"reports/{report.pk}/comments/"),
            {"body": "Additional update."},
            format="json",
        )
        self.assertEqual(created_comment.status_code, 201)
        self.assertEqual(created_comment.data["author_id"], self.resident.pk)

    def test_search_parameters_are_forbidden_for_non_officers(self):
        self.create_report()
        self.client.force_authenticate(self.resident)

        response = self.client.get(self.api_url("reports/?room=A101"))

        self.assertEqual(response.status_code, 403)

    def test_unit_results_are_period_filtered_and_role_scoped(self):
        report = self.create_report()
        start_review(
            report_id=report.pk,
            actor=self.officer,
            expected_version=report.version,
            room_verified=True,
        )
        report.refresh_from_db()
        assign_technician(
            report_id=report.pk,
            technician=self.technician,
            assigned_by=self.officer,
            priority="MEDIUM",
            expected_version=report.version,
        )
        report.refresh_from_db()
        start_work(
            report_id=report.pk,
            technician=self.technician,
            expected_version=report.version,
        )
        report.refresh_from_db()
        complete_work(
            report_id=report.pk,
            technician=self.technician,
            expected_version=report.version,
            completion_notes="Repaired the sink.",
        )
        self.client.force_authenticate(self.officer)

        response = self.client.get(self.api_url("units/results/?period=month"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data[0]["completed_jobs"], 1)
        self.assertEqual(response.data[0]["period"], "month")
        self.assertIn("average_completion_hours", response.data[0])
        invalid_period = self.client.get(
            self.api_url("units/results/?period=decade")
        )
        self.assertEqual(invalid_period.status_code, 400)

        other_unit = Unit.objects.create(
            name="Other API Unit", kind=UnitKind.INTERNAL
        )
        self.other_technician.unit = other_unit
        self.other_technician.save(update_fields=("unit",))
        self.client.force_authenticate(self.other_technician)
        technician_results = self.client.get(self.api_url("units/results/"))
        self.assertEqual(
            [result["unit_id"] for result in technician_results.data],
            [other_unit.pk],
        )

        self.client.force_authenticate(self.officer)
        staff_results = self.client.get(self.api_url("units/results/"))
        self.assertEqual(
            {result["unit_id"] for result in staff_results.data},
            {self.unit.pk, other_unit.pk},
        )
        self.assertTrue(
            all(result["period"] == "quarter" for result in staff_results.data)
        )
        self.client.force_authenticate(self.resident)
        forbidden = self.client.get(self.api_url("units/results/"))
        self.assertEqual(forbidden.status_code, 403)

    def test_session_authenticated_write_requires_csrf_token(self):
        report = self.create_report()
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.officer)

        response = csrf_client.patch(
            self.api_url(f"reports/{report.pk}/status/"),
            {"status": Report.Status.UNDER_REVIEW, "version": report.version},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)
        report.refresh_from_db()
        self.assertEqual(report.status, Report.Status.SUBMITTED)

    def test_verify_and_reopen_use_workflow_services(self):
        report = self.create_report()
        start_review(
            report_id=report.pk,
            actor=self.officer,
            expected_version=report.version,
            room_verified=True,
        )
        report.refresh_from_db()
        assign_technician(
            report_id=report.pk,
            technician=self.technician,
            assigned_by=self.officer,
            priority="MEDIUM",
            expected_version=report.version,
        )
        report.refresh_from_db()
        start_work(
            report_id=report.pk,
            technician=self.technician,
            expected_version=report.version,
        )
        report.refresh_from_db()
        complete_work(
            report_id=report.pk,
            technician=self.technician,
            expected_version=report.version,
            completion_notes="Replaced the tap.",
        )
        report.refresh_from_db()

        self.client.force_authenticate(self.resident)
        verify_response = self.client.post(
            self.api_url(f"reports/{report.pk}/verify/"),
            {"comment": "Resolved.", "version": report.version},
            format="json",
        )
        self.assertEqual(verify_response.status_code, 200)
        report.refresh_from_db()
        self.assertEqual(report.status, Report.Status.CLOSED)
        self.assertEqual(Verification.objects.filter(report=report).count(), 1)
        self.assertIsNone(Verification.objects.get(report=report).rating)

        # Reopen is offered for completed work; use a second completed report because
        # the verified report has already entered the closed state.
        reopen_report_record = self.create_report(title="Second repair")
        start_review(
            report_id=reopen_report_record.pk,
            actor=self.officer,
            expected_version=reopen_report_record.version,
            room_verified=True,
        )
        reopen_report_record.refresh_from_db()
        assign_technician(
            report_id=reopen_report_record.pk,
            technician=self.technician,
            assigned_by=self.officer,
            priority="MEDIUM",
            expected_version=reopen_report_record.version,
        )
        reopen_report_record.refresh_from_db()
        start_work(
            report_id=reopen_report_record.pk,
            technician=self.technician,
            expected_version=reopen_report_record.version,
        )
        reopen_report_record.refresh_from_db()
        complete_work(
            report_id=reopen_report_record.pk,
            technician=self.technician,
            expected_version=reopen_report_record.version,
            completion_notes="Attempted repair.",
        )
        reopen_report_record.refresh_from_db()

        reopen_response = self.client.post(
            self.api_url(f"reports/{reopen_report_record.pk}/reopen/"),
            {
                "reason": "The leak is still present.",
                "version": reopen_report_record.version,
            },
            format="json",
        )
        self.assertEqual(reopen_response.status_code, 200)
        reopen_report_record.refresh_from_db()
        self.assertEqual(reopen_report_record.status, Report.Status.ASSIGNED)
        self.assertEqual(
            Verification.objects.filter(
                report=reopen_report_record,
                outcome=Verification.Outcome.REOPENED,
            ).count(),
            1,
        )

    def test_item_1_completion_returns_closed_with_two_history_rows_and_version_steps(self):
        report = self.create_report()
        self.assign_report(report)
        report.refresh_from_db()
        self.client.force_authenticate(self.technician)
        started = self.client.patch(
            self.api_url(f"reports/{report.pk}/status/"),
            {"status": Report.Status.IN_PROGRESS, "version": report.version},
            format="json",
        )
        self.assertEqual(started.status_code, 200)
        report.refresh_from_db()
        version_before_completion = report.version

        response = self.client.patch(
            self.api_url(f"reports/{report.pk}/status/"),
            {
                "status": Report.Status.COMPLETED,
                "version": version_before_completion,
                "completion_notes": "Repaired the sink.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], Report.Status.CLOSED)
        self.assertEqual(response.data["version"], version_before_completion + 2)
        final_history = list(
            StatusHistory.objects.filter(report=report)
            .order_by("-pk")
            .values_list("new_status", "changed_by__username")[:2]
        )
        self.assertEqual(
            [entry[0] for entry in final_history],
            [Report.Status.CLOSED, Report.Status.COMPLETED],
        )
        self.assertEqual(final_history[0][1], "system-event-actor")
        self.assertEqual(final_history[1][1], self.technician.username)
        self.assertIsNotNone(
            Assignment.objects.get(report=report, completed_at__isnull=False).completed_at
        )

    def test_item_2_reopen_day_four_returns_coded_conflict(self):
        report = self.create_report()
        self.complete_report(report)
        report.refresh_from_db()
        now = timezone.now()
        Assignment.objects.filter(report=report, completed_at__isnull=False).update(
            completed_at=now - timedelta(days=4)
        )
        self.client.force_authenticate(self.resident)

        with patch("reports.services.timezone.now", return_value=now):
            response = self.client.post(
                self.api_url(f"reports/{report.pk}/reopen/"),
                {"reason": "The repair still needs attention.", "version": report.version},
                format="json",
            )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["error"], "reopen_window_closed")
        self.assertIn("detail", response.data)

    def test_item_3_closed_comments_return_coded_conflict_and_reopened_comments_work(self):
        report = self.create_report()
        self.complete_report(report)

        self.client.force_authenticate(self.resident)
        closed_response = self.client.post(
            self.api_url(f"reports/{report.pk}/comments/"),
            {"body": "A late comment."},
            format="json",
        )
        self.assertEqual(closed_response.status_code, 409)
        self.assertEqual(closed_response.data["error"], "ticket_closed")
        self.assertIn("detail", closed_response.data)

        self.client.force_authenticate(self.officer)
        staff_closed_response = self.client.post(
            self.api_url(f"reports/{report.pk}/comments/"),
            {"body": "A staff late comment."},
            format="json",
        )
        self.assertEqual(staff_closed_response.status_code, 409)
        self.assertEqual(staff_closed_response.data["error"], "ticket_closed")

        self.client.force_authenticate(self.other_technician)
        hidden_closed_response = self.client.post(
            self.api_url(f"reports/{report.pk}/comments/"),
            {"body": "A comment from an unassigned Technician/Contractor."},
            format="json",
        )
        self.assertEqual(hidden_closed_response.status_code, 404)

        self.client.force_authenticate(self.resident)
        reopened = self.client.post(
            self.api_url(f"reports/{report.pk}/reopen/"),
            {"reason": "The repair still needs attention.", "version": report.version},
            format="json",
        )
        self.assertEqual(reopened.status_code, 200)
        self.assertEqual(reopened.data["status"], Report.Status.ASSIGNED)
        comment_response = self.client.post(
            self.api_url(f"reports/{report.pk}/comments/"),
            {"body": "The issue remains."},
            format="json",
        )
        self.assertEqual(comment_response.status_code, 201)

    def test_item_4_verification_is_optional_rating_and_requires_closed_status(self):
        closed_report = self.create_report()
        self.complete_report(closed_report)
        closed_report.refresh_from_db()
        self.client.force_authenticate(self.resident)
        for rating in (0, 6, 1.5):
            with self.subTest(rating=rating):
                invalid_rating = self.client.post(
                    self.api_url(f"reports/{closed_report.pk}/verify/"),
                    {"version": closed_report.version, "rating": rating},
                    format="json",
                )
                self.assertEqual(invalid_rating.status_code, 400)

        response = self.client.post(
            self.api_url(f"reports/{closed_report.pk}/verify/"),
            {"version": closed_report.version, "comment": "Resolved."},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], Report.Status.CLOSED)
        self.assertIsNone(Verification.objects.get(report=closed_report).rating)

        completed_report = self.create_report(title="Not yet closed")
        self.complete_report(completed_report, close=False)
        completed_report.refresh_from_db()
        response = self.client.post(
            self.api_url(f"reports/{completed_report.pk}/verify/"),
            {"version": completed_report.version},
            format="json",
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["error"], "ticket_not_closed")

    def test_item_5_assignment_requires_explicit_active_unit_and_stale_version_code(self):
        report = self.create_report()
        start_review(
            report_id=report.pk,
            actor=self.officer,
            expected_version=report.version,
            room_verified=True,
        )
        report.refresh_from_db()
        self.client.force_authenticate(self.officer)

        missing_unit = self.client.post(
            self.api_url(f"reports/{report.pk}/assign/"),
            {"technician": self.technician.pk, "version": report.version},
            format="json",
        )
        self.assertEqual(missing_unit.status_code, 400)

        stale = self.client.post(
            self.api_url(f"reports/{report.pk}/assign/"),
            {
                "unit": self.unit.pk,
                "priority": "MEDIUM",
                "version": report.version - 1,
            },
            format="json",
        )
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.data["error"], "version_conflict")

    def test_item_6_officer_report_without_room_confirmation_is_rejected(self):
        self.client.force_authenticate(self.officer)
        response = self.client.post(
            self.api_url("officer/reports/"),
            {
                "resident": self.resident.pk,
                "category": self.category.pk,
                "building": self.building.pk,
                "room_location": self.room.code,
                "room_verified": False,
                "title": "Staff-entered report",
                "description": "A request taken by phone.",
                "requested_urgency": "MEDIUM",
                "channel": "PHONE",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Report.objects.count(), 0)

    def test_item_7_signature_flag_persists_and_controls_completion_photo(self):
        report = self.create_report()
        self.assign_report(report)
        report.refresh_from_db()
        start_work(
            report_id=report.pk,
            technician=self.technician,
            expected_version=report.version,
        )
        report.refresh_from_db()
        self.client.force_authenticate(self.technician)

        photo_without_signature = self.client.patch(
            self.api_url(f"reports/{report.pk}/status/"),
            {
                "status": Report.Status.COMPLETED,
                "version": report.version,
                "completion_notes": "Completed.",
                "requester_signed_on_site": False,
                "photo": image_upload("not-signed.jpg"),
            },
            format="multipart",
        )
        self.assertEqual(photo_without_signature.status_code, 400)
        report.refresh_from_db()
        self.assertEqual(report.status, Report.Status.IN_PROGRESS)

        signed = self.client.patch(
            self.api_url(f"reports/{report.pk}/status/"),
            {
                "status": Report.Status.COMPLETED,
                "version": report.version,
                "completion_notes": "Completed with paper signature.",
                "requester_signed_on_site": True,
            },
            format="multipart",
        )
        self.assertEqual(signed.status_code, 200)
        assignment = Assignment.objects.filter(report=report).latest("pk")
        self.assertTrue(assignment.requester_signed_on_site)
        self.assertIsNotNone(assignment.completed_at)

    def test_item_8_photo_download_obeys_resident_staff_and_assignment_scope(self):
        self.client.force_authenticate(self.resident)
        created = self.client.post(
            self.api_url(),
            {
                "category": self.category.pk,
                "building": self.building.pk,
                "room_location": self.room.code,
                "room_verified": True,
                "title": "Photo access test",
                "description": "A report with a photo.",
                "requested_urgency": "MEDIUM",
                "photo": image_upload(),
            },
            format="multipart",
        )
        self.assertEqual(created.status_code, 201)
        report = Report.objects.get(pk=created.data["id"])
        photo = Photo.objects.get(report=report)
        self.assign_report(report)
        photo_url = self.api_url(f"reports/{report.pk}/photos/{photo.pk}/")

        for user, expected in (
            (self.resident, 200),
            (self.other_resident, 404),
            (self.officer, 200),
            (self.technician, 200),
            (self.other_technician, 404),
        ):
            with self.subTest(role=user.role, user=user.pk):
                self.client.force_authenticate(user)
                response = self.client.get(photo_url)
                self.assertEqual(response.status_code, expected)
                release_streamed_file(response)

        report.refresh_from_db()
        start_work(
            report_id=report.pk,
            technician=self.technician,
            expected_version=report.version,
        )
        report.refresh_from_db()
        self.client.force_authenticate(self.technician)
        completion = self.client.patch(
            self.api_url(f"reports/{report.pk}/status/"),
            {
                "status": Report.Status.COMPLETED,
                "version": report.version,
                "completion_notes": "Completed.",
                "requester_signed_on_site": True,
                "photo": image_upload("completion.jpg"),
            },
            format="multipart",
        )
        self.assertEqual(completion.status_code, 200)
        completion_photo = Photo.objects.get(
            report=report, stage=Photo.Stage.COMPLETION
        )
        completion_url = self.api_url(
            f"reports/{report.pk}/photos/{completion_photo.pk}/"
        )
        for user, expected in (
            (self.resident, 200),
            (self.officer, 200),
            (self.technician, 404),
            (self.other_technician, 404),
        ):
            with self.subTest(completion_photo=True, role=user.role, user=user.pk):
                self.client.force_authenticate(user)
                response = self.client.get(completion_url)
                self.assertEqual(response.status_code, expected)
                release_streamed_file(response)

    def test_item_9_since_returns_only_newer_ids_in_ascending_order(self):
        report = self.create_report()
        older_id_comment = Comment.objects.create(
            report=report, author=self.resident, body="Lower ID"
        )
        newer_id_comment = Comment.objects.create(
            report=report, author=self.resident, body="Higher ID"
        )
        older_id_notification = Notification.objects.create(
            user=self.resident, report=report, message="Lower ID"
        )
        newer_id_notification = Notification.objects.create(
            user=self.resident, report=report, message="Higher ID"
        )
        now = timezone.now()
        Comment.objects.filter(pk=older_id_comment.pk).update(
            created_at=now + timedelta(seconds=2)
        )
        Comment.objects.filter(pk=newer_id_comment.pk).update(
            created_at=now - timedelta(seconds=2)
        )
        Notification.objects.filter(pk=older_id_notification.pk).update(
            created_at=now + timedelta(seconds=2)
        )
        Notification.objects.filter(pk=newer_id_notification.pk).update(
            created_at=now - timedelta(seconds=2)
        )
        self.client.force_authenticate(self.resident)

        comments = self.client.get(
            self.api_url(
                f"reports/{report.pk}/comments/?since={older_id_comment.pk - 1}"
            )
        )
        notifications = self.client.get(
            self.api_url(f"notifications/?since={older_id_notification.pk - 1}")
        )

        self.assertEqual(
            [item["id"] for item in comments.data["results"]],
            [older_id_comment.pk, newer_id_comment.pk],
        )
        self.assertEqual(
            [item["id"] for item in notifications.data["results"]],
            [older_id_notification.pk, newer_id_notification.pk],
        )

    def test_item_10_unit_results_support_all_periods_and_refuse_other_roles(self):
        report = self.create_report()
        self.assign_report(report)
        report.refresh_from_db()
        start_work(
            report_id=report.pk,
            technician=self.technician,
            expected_version=report.version,
        )
        report.refresh_from_db()
        complete_work(
            report_id=report.pk,
            technician=self.technician,
            expected_version=report.version,
            completion_notes="Completed for unit results.",
        )
        self.client.force_authenticate(self.officer)
        for period in ("month", "quarter", "year", "all"):
            with self.subTest(period=period):
                response = self.client.get(
                    self.api_url(f"units/results/?period={period}")
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data[0]["completed_jobs"], 1)
                self.assertEqual(response.data[0]["period"], period)
                self.assertNotIn("score", response.data[0])
                self.assertNotIn("target", response.data[0])
                self.assertNotIn("rank", response.data[0])

        non_role_staff = User.objects.create_user(
            username="api_django_staff",
            email="api_django_staff@example.test",
            password="test-password",
            is_staff=True,
        )
        for user in (self.resident, non_role_staff):
            with self.subTest(role=user.role, is_staff=user.is_staff):
                self.client.force_authenticate(user)
                response = self.client.get(self.api_url("units/results/"))
                self.assertEqual(response.status_code, 403)

    def test_item_11_non_call_center_search_parameters_return_403(self):
        report = self.create_report()
        self.client.force_authenticate(self.resident)
        for parameter in (
            f"ticket_no={report.ticket_no}",
            f"student_id={self.resident.username}",
            f"room={self.room.code}",
            "room=",
        ):
            with self.subTest(parameter=parameter):
                response = self.client.get(
                    self.api_url(f"reports/?{parameter}")
                )
                self.assertEqual(response.status_code, 403)

    def test_item_12_unassigned_technician_gets_404_on_report_routes(self):
        report = self.create_report()
        self.client.force_authenticate(self.other_technician)
        self.assertEqual(self.client.get(self.api_url()).data["count"], 0)
        urls_and_methods = (
            ("GET", f"reports/{report.pk}/"),
            ("PATCH", f"reports/{report.pk}/status/"),
            ("GET", f"reports/{report.pk}/history/"),
            ("GET", f"reports/{report.pk}/comments/"),
            ("GET", f"reports/{report.pk}/photos/1/"),
            ("POST", f"reports/{report.pk}/verify/"),
            ("POST", f"reports/{report.pk}/reopen/"),
        )
        for method, suffix in urls_and_methods:
            with self.subTest(method=method, suffix=suffix):
                url = self.api_url(suffix)
                if method == "GET":
                    response = self.client.get(url)
                elif method == "PATCH":
                    response = self.client.patch(
                        url,
                        {"status": Report.Status.IN_PROGRESS, "version": report.version},
                        format="json",
                    )
                else:
                    response = self.client.post(
                        url, {"version": report.version}, format="json"
                    )
                self.assertEqual(response.status_code, 404)

    def test_openapi_schema_and_docs_routes_exist(self):
        schema = self.client.get("/api/schema/")
        docs = self.client.get("/api/docs/")

        self.assertEqual(schema.status_code, 200)
        self.assertIn("/api/reports/", schema.data["paths"])
        self.assertIn("/api/units/results/", schema.data["paths"])
        self.assertEqual(
            schema.data["servers"],
            [
                {
                    "url": "http://192.41.170.180",
                    "description": "CSIM server (deployed)",
                },
                {
                    "url": "http://localhost:8000",
                    "description": "Local development",
                },
            ],
        )
        report_list_description = schema.data["paths"]["/api/reports/"]["get"][
            "description"
        ]
        self.assertIn("Call Center Staff", report_list_description)
        self.assertIn("Technician/Contractor", report_list_description)
        self.assertEqual(docs.status_code, 200)
