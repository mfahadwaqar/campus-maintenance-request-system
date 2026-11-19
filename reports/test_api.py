from django.test import Client
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
    Report,
    StatusHistory,
    Verification,
)
from .services import (
    assign_technician,
    complete_work,
    start_review,
    start_work,
    submit_report,
)


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
                "technician": self.technician.pk,
                "priority": "HIGH",
                "version": 1,
            },
            format="json",
        )
        self.assertEqual(stale_response.status_code, 409)
        self.assertFalse(Assignment.objects.filter(report=report).exists())
        report.refresh_from_db()
        self.assertEqual(report.status, Report.Status.UNDER_REVIEW)

        assignment_response = self.client.post(
            self.api_url(f"reports/{report.pk}/assign/"),
            {
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
        self.assertEqual(completed.status_code, 200)
        report.refresh_from_db()
        self.assertEqual(report.status, Report.Status.CLOSED)

    def test_wrong_role_cannot_assign_and_nonassigned_technician_cannot_view(self):
        report = self.create_report()
        self.client.force_authenticate(self.resident)
        forbidden = self.client.post(
            self.api_url(f"reports/{report.pk}/assign/"),
            {
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
        invalid_period = self.client.get(
            self.api_url("units/results/?period=decade")
        )
        self.assertEqual(invalid_period.status_code, 400)
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
        self.assertEqual(reopen_report_record.status, Report.Status.REOPENED)
        self.assertEqual(
            Verification.objects.filter(
                report=reopen_report_record,
                outcome=Verification.Outcome.REOPENED,
            ).count(),
            1,
        )

    def test_openapi_schema_and_docs_routes_exist(self):
        schema = self.client.get("/api/schema/")
        docs = self.client.get("/api/docs/")

        self.assertEqual(schema.status_code, 200)
        self.assertIn("/api/reports/", schema.data["paths"])
        self.assertEqual(docs.status_code, 200)
