from io import BytesIO

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse
from PIL import Image

from accounts.models import Building, User
from assignments.models import Assignment
from notifications.models import Notification
from .models import Category, Comment, Photo, Report, StatusHistory, Verification
from .services import (
    add_comment,
    assign_technician,
    complete_work,
    mark_duplicate,
    reopen_report,
    start_review,
    start_work,
    submit_report,
    verify_report,
)


class TechnicianAndVerificationWorkflowTests(TestCase):
    def setUp(self):
        self.building = Building.objects.create(name="North Hall", zone="North")
        self.category = Category.objects.create(name="Plumbing")
        self.resident = self.make_user("resident", User.Role.RESIDENT)
        self.other_resident = self.make_user("other-resident", User.Role.RESIDENT)
        self.officer = self.make_user("officer", User.Role.OFFICER)
        self.second_officer = self.make_user("second-officer", User.Role.OFFICER)
        self.technician = self.make_user("technician", User.Role.TECHNICIAN)
        self.other_technician = self.make_user(
            "other-technician", User.Role.TECHNICIAN
        )

    def tearDown(self):
        for photo in Photo.objects.all():
            photo.file.delete(save=False)

    def make_user(self, username, role):
        return User.objects.create_user(
            username=username,
            password="test-password",
            email=f"{username}@example.test",
            role=role,
        )

    def create_report(self, resident=None, **values):
        return submit_report(
            resident=resident or self.resident,
            category=self.category,
            building=self.building,
            room_location=values.get("room_location", "Room 204"),
            title=values.get("title", "Leaking sink"),
            description=values.get("description", "Water is leaking."),
            requested_urgency="MEDIUM",
        )

    def assign(self, report, technician=None):
        start_review(
            report_id=report.pk,
            actor=self.officer,
            expected_version=report.version,
        )
        return assign_technician(
            report_id=report.pk,
            technician=technician or self.technician,
            assigned_by=self.officer,
            priority="MEDIUM",
            expected_version=report.version + 1,
        )

    def begin_work(self, report, technician=None):
        technician = technician or self.technician
        self.assign(report, technician)
        return start_work(
            report_id=report.pk,
            technician=technician,
            expected_version=report.version + 2,
        )

    def complete_report(self, report, technician=None):
        technician = technician or self.technician
        self.begin_work(report, technician)
        return complete_work(
            report_id=report.pk,
            technician=technician,
            expected_version=report.version + 3,
            completion_notes="Replaced the damaged pipe and tested the sink.",
        )

    def test_full_lifecycle_records_transitions_verification_and_notifications(self):
        report = self.create_report()
        self.assertEqual(report.status, Report.Status.SUBMITTED)
        self.assertTrue(
            Notification.objects.filter(
                report=report, message__contains="was submitted"
            ).exists()
        )

        start_review(
            report_id=report.pk,
            actor=self.officer,
            expected_version=report.version,
        )
        self.assertEqual(
            StatusHistory.objects.filter(report=report).latest("pk").new_status,
            Report.Status.UNDER_REVIEW,
        )
        assign_technician(
            report_id=report.pk,
            technician=self.technician,
            assigned_by=self.officer,
            priority="MEDIUM",
            expected_version=report.version + 1,
        )
        assignment = Assignment.objects.get(report=report, is_active=True)
        self.assertEqual(assignment.technician, self.technician)

        start_work(
            report_id=report.pk,
            technician=self.technician,
            expected_version=report.version + 2,
        )
        complete_work(
            report_id=report.pk,
            technician=self.technician,
            expected_version=report.version + 3,
            completion_notes="Replaced the damaged pipe and tested the sink.",
        )
        report.refresh_from_db()
        self.assertEqual(report.status, Report.Status.COMPLETED)
        assignment.refresh_from_db()
        self.assertFalse(assignment.is_active)
        self.assertTrue(
            Notification.objects.filter(
                report=report, message__contains="ready for verification"
            ).exists()
        )

        verify_report(
            report_id=report.pk,
            resident=self.resident,
            expected_version=report.version,
            rating=5,
            comment="Looks good.",
        )
        report.refresh_from_db()
        self.assertEqual(report.status, Report.Status.CLOSED)
        self.assertEqual(
            Verification.objects.get(report=report).outcome,
            Verification.Outcome.VERIFIED,
        )
        self.assertEqual(StatusHistory.objects.filter(report=report).count(), 6)
        self.assertTrue(
            Notification.objects.filter(
                report=report, message__contains="verified and closed"
            ).exists()
        )

    def test_reopen_then_reassign_keeps_assignment_history(self):
        report = self.create_report()
        self.complete_report(report)
        report.refresh_from_db()

        reopen_report(
            report_id=report.pk,
            resident=self.resident,
            expected_version=report.version,
            reason="The sink is still leaking.",
        )
        report.refresh_from_db()
        self.assertEqual(report.status, Report.Status.REOPENED)
        self.assertTrue(
            Notification.objects.filter(
                report=report,
                user__role=User.Role.OFFICER,
                message__contains="was reopened",
            ).exists()
        )

        assign_technician(
            report_id=report.pk,
            technician=self.other_technician,
            assigned_by=self.second_officer,
            priority="HIGH",
            expected_version=report.version,
        )
        assignments = Assignment.objects.filter(report=report).order_by("pk")
        self.assertEqual(assignments.count(), 2)
        self.assertFalse(assignments[0].is_active)
        self.assertEqual(assignments[0].technician, self.technician)
        self.assertTrue(assignments[1].is_active)
        self.assertEqual(assignments[1].technician, self.other_technician)

    def test_only_active_assigned_technician_can_open_work_order_or_start_work(self):
        report = self.create_report()
        self.assign(report)
        self.client.force_login(self.other_technician)

        response = self.client.get(
            reverse("assignments:technician_report_detail", args=(report.pk,))
        )
        self.assertEqual(response.status_code, 404)
        with self.assertRaises(ValidationError):
            start_work(
                report_id=report.pk,
                technician=self.other_technician,
                expected_version=report.version + 2,
            )
        report.refresh_from_db()
        self.assertEqual(report.status, Report.Status.ASSIGNED)
        self.assertEqual(StatusHistory.objects.filter(report=report).count(), 3)

    def test_completion_without_notes_is_rejected_without_changing_state(self):
        report = self.create_report()
        self.begin_work(report)

        with self.assertRaises(ValidationError):
            complete_work(
                report_id=report.pk,
                technician=self.technician,
                expected_version=report.version + 3,
                completion_notes="  ",
            )

        report.refresh_from_db()
        self.assertEqual(report.status, Report.Status.IN_PROGRESS)
        self.assertTrue(
            Assignment.objects.get(report=report, is_active=True).is_active
        )

    def test_illegal_jump_from_assigned_to_completed_is_rejected(self):
        report = self.create_report()
        self.assign(report)

        with self.assertRaises(ValidationError):
            complete_work(
                report_id=report.pk,
                technician=self.technician,
                expected_version=report.version + 2,
                completion_notes="Tried to skip work.",
            )

        report.refresh_from_db()
        self.assertEqual(report.status, Report.Status.ASSIGNED)
        self.assertEqual(StatusHistory.objects.filter(report=report).count(), 3)

    def test_only_report_resident_can_verify_or_reopen(self):
        report = self.complete_report(self.create_report())
        report.refresh_from_db()

        with self.assertRaises(ValidationError):
            verify_report(
                report_id=report.pk,
                resident=self.other_resident,
                expected_version=report.version,
                rating=4,
            )
        with self.assertRaises(ValidationError):
            reopen_report(
                report_id=report.pk,
                resident=self.other_resident,
                expected_version=report.version,
                reason="Not my report.",
            )
        report.refresh_from_db()
        self.assertEqual(report.status, Report.Status.COMPLETED)
        self.assertFalse(Verification.objects.filter(report=report).exists())

    def test_internal_comments_are_never_visible_to_residents(self):
        report = self.create_report()
        public_comment = add_comment(
            report_id=report.pk,
            author=self.resident,
            body="Please knock before entering.",
        )
        internal_comment = add_comment(
            report_id=report.pk,
            author=self.officer,
            body="Coordinate access with the building office.",
            is_internal=True,
        )
        self.assertQuerySetEqual(
            Comment.objects.for_user(self.resident, report),
            [public_comment],
        )

        self.client.force_login(self.resident)
        response = self.client.get(reverse("reports:detail", args=(report.pk,)))
        self.assertContains(response, "Please knock before entering.")
        self.assertNotContains(response, internal_comment.body)
        self.assertIn(internal_comment, Comment.objects.for_user(self.officer, report))

    def test_merged_resident_sees_only_master_ticket_id_and_status(self):
        master = self.create_report(
            resident=self.other_resident,
            title="MASTER PRIVATE TITLE",
            room_location="MASTER ROOM 900",
            description="MASTER PRIVATE REPAIR DESCRIPTION",
        )
        duplicate = self.create_report(
            title="My duplicate request",
            room_location="Room 205",
        )
        start_review(
            report_id=duplicate.pk,
            actor=self.officer,
            expected_version=duplicate.version,
        )
        mark_duplicate(
            report_id=duplicate.pk,
            master_report_id=master.pk,
            actor=self.officer,
            expected_version=duplicate.version + 1,
        )

        self.client.force_login(self.resident)
        response = self.client.get(reverse("reports:detail", args=(duplicate.pk,)))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"Request #{master.pk}")
        self.assertContains(response, master.get_status_display())
        self.assertNotContains(response, "MASTER PRIVATE TITLE")
        self.assertNotContains(response, "MASTER ROOM 900")
        self.assertNotContains(response, "MASTER PRIVATE REPAIR DESCRIPTION")

    def test_linked_resident_can_reopen_master_from_their_merged_ticket(self):
        master = self.create_report(
            resident=self.other_resident,
            title="Master repair",
        )
        self.complete_report(master)
        master.refresh_from_db()
        duplicate = self.create_report(title="Linked resident report")
        start_review(
            report_id=duplicate.pk,
            actor=self.officer,
            expected_version=duplicate.version,
        )
        mark_duplicate(
            report_id=duplicate.pk,
            master_report_id=master.pk,
            actor=self.officer,
            expected_version=duplicate.version + 1,
        )
        duplicate.refresh_from_db()
        self.client.force_login(self.resident)

        detail_response = self.client.get(
            reverse("reports:detail", args=(duplicate.pk,))
        )
        self.assertContains(detail_response, "Reopen master request")
        response = self.client.post(
            reverse("reports:reopen", args=(duplicate.pk,)),
            {
                "version": duplicate.version,
                "reason": "The linked repair was not completed in my room.",
            },
        )

        self.assertRedirects(response, reverse("reports:detail", args=(duplicate.pk,)))
        master.refresh_from_db()
        duplicate.refresh_from_db()
        self.assertEqual(master.status, Report.Status.REOPENED)
        self.assertEqual(duplicate.status, Report.Status.MERGED)
        verification = Verification.objects.get(report=duplicate)
        self.assertEqual(verification.outcome, Verification.Outcome.REOPENED)
        self.assertIsNone(verification.rating)

    def test_status_changing_views_reject_get_requests(self):
        report = self.create_report()

        self.client.force_login(self.resident)
        verify_response = self.client.get(
            reverse("reports:verify", args=(report.pk,))
        )
        reopen_response = self.client.get(
            reverse("reports:reopen", args=(report.pk,))
        )
        self.assertEqual(verify_response.status_code, 405)
        self.assertEqual(reopen_response.status_code, 405)

    def test_completion_photo_is_stored_as_completion_stage(self):
        report = self.create_report()
        self.begin_work(report)
        report.refresh_from_db()
        output = BytesIO()
        Image.new("RGB", (20, 20), color=(10, 80, 120)).save(output, format="JPEG")
        upload = SimpleUploadedFile(
            "repair.jpg", output.getvalue(), content_type="image/jpeg"
        )
        self.client.force_login(self.technician)

        response = self.client.post(
            reverse("assignments:complete_work", args=(report.pk,)),
            {
                "version": report.version,
                "completion_notes": "Replaced the damaged part and tested it.",
                "photo": upload,
            },
        )

        self.assertRedirects(response, reverse("accounts:technician_dashboard"))
        photo = Photo.objects.get(report=report)
        self.assertEqual(photo.stage, Photo.Stage.COMPLETION)
        self.assertEqual(photo.uploaded_by, self.technician)

    def test_work_start_requires_csrf_token(self):
        report = self.create_report()
        self.assign(report)
        report.refresh_from_db()
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.technician)

        response = csrf_client.post(
            reverse("assignments:start_work", args=(report.pk,)),
            {"version": report.version},
        )

        self.assertEqual(response.status_code, 403)
        report.refresh_from_db()
        self.assertEqual(report.status, Report.Status.ASSIGNED)
