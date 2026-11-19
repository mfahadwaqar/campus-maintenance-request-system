from datetime import date, timedelta
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from PIL import Image
from rest_framework.test import APITestCase

from accounts.models import Building, RoomLocation, Unit, UnitKind, User
from assignments.models import Assignment

from .models import Category, Photo
from .services import (
    assign_technician,
    complete_work,
    put_on_hold,
    start_review,
    start_work,
    submit_report,
    verify_report,
)
from .storage import private_photo_storage


def photo_upload():
    output = BytesIO()
    Image.new("RGB", (8, 8), color="green").save(output, format="JPEG")
    return SimpleUploadedFile("fields.jpg", output.getvalue(), content_type="image/jpeg")


class ReportJsonFieldTests(APITestCase):
    """The report JSON carries everything the pages need without extra calls."""

    def setUp(self):
        self.building = Building.objects.create(name="Fields Dorm", zone="Zone 1")
        self.category = Category.objects.create(name="Fields Plumbing")
        self.room, _ = RoomLocation.objects.get_or_create(
            code="A101",
            defaults={
                "name": "Dormitory A",
                "location_type": RoomLocation.LocationType.DORMITORY,
            },
        )
        self.unit = Unit.objects.create(name="Fields Unit", kind=UnitKind.INTERNAL)
        self.resident = User.objects.create_user(
            username="st200001",
            email="fields.resident@example.test",
            password="test-password",
            role=User.Role.RESIDENT,
            name="Fields Resident",
            phone="0800000000",
        )
        self.officer = User.objects.create_user(
            username="fields_officer",
            email="fields.officer@example.test",
            password="test-password",
            role=User.Role.CALL_CENTER_STAFF,
        )
        self.technician = User.objects.create_user(
            username="fields_tech",
            email="fields.tech@example.test",
            password="test-password",
            role=User.Role.TECHNICIAN_CONTRACTOR,
            unit=self.unit,
            name="Fields Technician",
        )

    def tearDown(self):
        for photo in Photo.objects.all():
            private_photo_storage.delete(photo.file_path)
        super().tearDown()

    def new_report(self, **overrides):
        values = {
            "category": self.category,
            "building": self.building,
            "room_location": self.room.code,
            "room_verified": True,
            "title": "Leaking sink",
            "description": "Water under the sink.",
            "requested_urgency": "MEDIUM",
        }
        values.update(overrides)
        return submit_report(resident=self.resident, **values)

    def assign(self, report):
        start_review(
            report_id=report.pk,
            actor=self.officer,
            expected_version=report.version,
            room_verified=True,
        )
        report.refresh_from_db()
        return assign_technician(
            report_id=report.pk,
            technician=self.technician,
            assigned_by=self.officer,
            unit=self.unit,
            priority="HIGH",
            expected_version=report.version,
        )

    def close(self, report, signed=True):
        report.refresh_from_db()
        start_work(
            report_id=report.pk,
            technician=self.technician,
            expected_version=report.version,
        )
        report.refresh_from_db()
        return complete_work(
            report_id=report.pk,
            technician=self.technician,
            expected_version=report.version,
            completion_notes="Replaced the washer.",
            requester_signed_on_site=signed,
        )

    def fetch(self, user, report):
        self.client.force_authenticate(user)
        response = self.client.get(f"/api/reports/{report.pk}/")
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def test_new_report_has_empty_workflow_fields_and_resident_details(self):
        report = self.new_report()

        data = self.fetch(self.officer, report)

        self.assertEqual(data["status_label"], "Submitted")
        self.assertEqual(data["resident"]["name"], "Fields Resident")
        self.assertEqual(data["resident"]["student_id"], "st200001")
        self.assertEqual(data["resident"]["email"], "fields.resident@example.test")
        self.assertEqual(data["resident"]["phone"], "0800000000")
        self.assertIsNone(data["active_assignment"])
        self.assertEqual(data["assignments"], [])
        self.assertIsNone(data["completion"])
        self.assertIsNone(data["hold"])
        self.assertIsNone(data["reopen"])
        self.assertIsNone(data["verification"])
        self.assertEqual(data["photos"], [])

    def test_assignment_shows_unit_and_technician(self):
        report = self.new_report()
        self.assign(report)

        data = self.fetch(self.officer, report)

        active = data["active_assignment"]
        self.assertEqual(active["unit"]["name"], "Fields Unit")
        self.assertEqual(active["technician"]["name"], "Fields Technician")
        self.assertTrue(active["is_active"])
        self.assertEqual(len(data["assignments"]), 1)
        self.assertEqual(data["priority"], "HIGH")

    def test_assign_endpoint_response_includes_assignments(self):
        report = self.new_report()
        start_review(
            report_id=report.pk,
            actor=self.officer,
            expected_version=report.version,
            room_verified=True,
        )
        report.refresh_from_db()
        self.client.force_authenticate(self.officer)

        response = self.client.post(
            f"/api/reports/{report.pk}/assign/",
            {
                "unit": self.unit.pk,
                "technician": self.technician.pk,
                "priority": "MEDIUM",
                "version": report.version,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(len(response.json()["assignments"]), 1)
        self.assertEqual(response.json()["status"], "ASSIGNED")

    def test_reassignment_keeps_history_and_one_active_row(self):
        report = self.new_report()
        self.assign(report)
        other_unit = Unit.objects.create(name="Second Unit", kind=UnitKind.CONTRACTOR)
        report.refresh_from_db()
        assign_technician(
            report_id=report.pk,
            technician=None,
            assigned_by=self.officer,
            unit=other_unit,
            priority=None,
            expected_version=report.version,
        )

        data = self.fetch(self.officer, report)

        self.assertEqual(len(data["assignments"]), 2)
        self.assertEqual(sum(row["is_active"] for row in data["assignments"]), 1)
        self.assertEqual(data["active_assignment"]["unit"]["name"], "Second Unit")
        self.assertIsNone(data["active_assignment"]["technician"])

    def test_hold_shows_reason_and_expected_date(self):
        report = self.new_report()
        self.assign(report)
        report.refresh_from_db()
        expected = date.today() + timedelta(days=4)
        put_on_hold(
            report_id=report.pk,
            technician=self.technician,
            expected_version=report.version,
            reason="Waiting for a replacement valve",
            expected_date=expected,
        )

        data = self.fetch(self.resident, report)

        self.assertEqual(data["status"], "ON_HOLD")
        self.assertEqual(data["hold"]["reason"], "Waiting for a replacement valve")
        self.assertEqual(data["hold"]["expected_date"], expected.isoformat())

    def test_completion_closes_ticket_and_exposes_notes_and_reopen_window(self):
        report = self.new_report()
        self.assign(report)
        self.close(report)

        data = self.fetch(self.resident, report)

        self.assertEqual(data["status"], "CLOSED")
        self.assertEqual(data["completion"]["completion_notes"], "Replaced the washer.")
        self.assertTrue(data["completion"]["requester_signed_on_site"])
        self.assertFalse(data["completion"]["completed_without_resident"])
        self.assertEqual(data["reopen"]["window_days"], 3)
        self.assertTrue(data["reopen"]["window_open"])
        self.assertGreater(data["reopen"]["seconds_remaining"], 3 * 24 * 3600 - 120)

    def test_completion_without_the_resident_is_marked(self):
        report = self.new_report()
        self.assign(report)
        self.close(report, signed=False)

        data = self.fetch(self.officer, report)

        self.assertTrue(data["completion"]["completed_without_resident"])

    def test_reopen_window_is_closed_after_three_days(self):
        report = self.new_report()
        self.assign(report)
        self.close(report)
        Assignment.objects.filter(report=report).update(
            completed_at=timezone.now() - timedelta(days=4)
        )

        data = self.fetch(self.resident, report)

        self.assertFalse(data["reopen"]["window_open"])
        self.assertEqual(data["reopen"]["seconds_remaining"], 0)

    @override_settings(REOPEN_WINDOW_DAYS=1)
    def test_reopen_window_follows_the_setting(self):
        report = self.new_report()
        self.assign(report)
        self.close(report)

        data = self.fetch(self.resident, report)

        self.assertEqual(data["reopen"]["window_days"], 1)
        self.assertLessEqual(data["reopen"]["seconds_remaining"], 24 * 3600)

    def test_verification_is_returned_after_closure(self):
        report = self.new_report()
        self.assign(report)
        self.close(report)
        report.refresh_from_db()
        verify_report(
            report_id=report.pk,
            resident=self.resident,
            expected_version=report.version,
            rating=4,
            comment="Fixed well",
        )

        data = self.fetch(self.resident, report)

        self.assertEqual(data["verification"]["rating"], 4)
        self.assertEqual(data["verification"]["comment"], "Fixed well")

    def test_photos_are_listed_with_download_urls(self):
        report = self.new_report(photo=photo_upload())

        data = self.fetch(self.resident, report)

        self.assertEqual(len(data["photos"]), 1)
        photo = Photo.objects.get(report=report)
        self.assertEqual(data["photos"][0]["stage"], "REPORT")
        self.assertEqual(
            data["photos"][0]["url"],
            reverse("api:report-photo", args=[report.pk, photo.pk]),
        )

    def test_unassigned_technician_still_cannot_see_the_report(self):
        report = self.new_report()
        self.assign(report)
        stranger = User.objects.create_user(
            username="fields_stranger",
            email="fields.stranger@example.test",
            password="test-password",
            role=User.Role.TECHNICIAN_CONTRACTOR,
            unit=self.unit,
        )
        self.client.force_authenticate(stranger)

        response = self.client.get(f"/api/reports/{report.pk}/")

        self.assertEqual(response.status_code, 404)

    def test_list_runs_the_same_number_of_queries_for_many_reports(self):
        first = self.new_report(title="One")
        self.assign(first)
        self.client.force_authenticate(self.officer)
        with CaptureQueriesContext(connection) as small:
            self.client.get("/api/reports/")
        for number in range(5):
            report = self.new_report(title=f"Extra {number}")
            self.assign(report)
        with CaptureQueriesContext(connection) as large:
            response = self.client.get("/api/reports/")

        self.assertEqual(response.json()["count"], 6)
        self.assertEqual(len(large), len(small))


class UnitResultsSpecShapeTests(APITestCase):
    def test_unit_results_carry_the_names_used_in_the_specification(self):
        unit = Unit.objects.create(name="Shape Unit", kind=UnitKind.INTERNAL)
        staff = User.objects.create_user(
            username="shape_staff",
            email="shape.staff@example.test",
            password="test-password",
            role=User.Role.CALL_CENTER_STAFF,
        )
        self.client.force_authenticate(staff)

        response = self.client.get("/api/units/results/?period=all")

        row = next(item for item in response.json() if item["unit"] == "Shape Unit")
        self.assertEqual(row["jobs_completed"], 0)
        self.assertIsNone(row["average_hours"])
        self.assertEqual(row["unit_id"], unit.pk)
        self.assertEqual(row["completed_jobs"], 0)
