from django.core.exceptions import ValidationError
from django.test import TestCase

from accounts.models import Building, User
from notifications.models import Notification
from io import BytesIO
from datetime import date, timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from accounts.models import Unit, UnitKind
from assignments.models import Assignment
from .models import Category, Comment, Photo, Report, StatusHistory
from .services import (
    add_comment,
    complete_work,
    enter_report_for_caller,
    put_on_hold,
    reject_report,
    start_review,
    start_work,
    submit_report,
)


class IntakeUATTests(TestCase):
    def setUp(self):
        self.building = Building.objects.create(name="Intake Building")
        self.category = Category.objects.create(name="Intake Category")
        self.resident = User.objects.create_user(
            username="127155", email="127155@example.test", password="test",
            role=User.Role.RESIDENT,
        )
        self.officer = User.objects.create_user(
            username="intake_officer", email="officer@example.test", password="test",
            role=User.Role.CALL_CENTER_STAFF,
        )

    def create_values(self):
        return {
            "category": self.category,
            "building": self.building,
            "room_location": "A101",
            "title": "Leaking tap",
            "description": "Water is leaking from the tap.",
            "requested_urgency": "MEDIUM",
        }

    def test_uat_01_resident_submission_generates_ticket(self):
        report = submit_report(resident=self.resident, **self.create_values())

        self.assertEqual(report.resident, self.resident)
        self.assertEqual(report.channel, "WEB")
        self.assertEqual(report.status, Report.Status.SUBMITTED)
        self.assertRegex(report.ticket_no, r"^CMR-2026-[0-9]+-[0-9]{6}$")
        self.assertTrue(StatusHistory.objects.filter(report=report, new_status="SUBMITTED").exists())

    def test_uat_02_staff_entry_records_channel_and_submitter(self):
        for channel in ("PHONE", "EMAIL", "WALK_IN"):
            with self.subTest(channel=channel):
                report = enter_report_for_caller(
                    resident=self.resident,
                    submitted_by=self.officer,
                    channel=channel,
                    **self.create_values(),
                )
                self.assertEqual(report.resident, self.resident)
                self.assertEqual(report.submitted_by, self.officer)
                self.assertEqual(report.channel, channel)

    def test_uat_03_rejection_records_reason_and_alerts_resident(self):
        report = submit_report(resident=self.resident, **self.create_values())
        start_review(report_id=report.pk, actor=self.officer, expected_version=report.version)
        report.refresh_from_db()

        with self.captureOnCommitCallbacks(execute=True):
            rejected = reject_report(
                report_id=report.pk,
                reason="The described issue is outside our service area.",
                actor=self.officer,
                expected_version=report.version,
            )

        rejected.refresh_from_db()
        self.assertEqual(rejected.status, Report.Status.REJECTED)
        self.assertTrue(Comment.objects.filter(report=rejected, body__contains="outside our service area").exists())
        self.assertTrue(Notification.objects.filter(report=rejected, user=self.resident, message__contains="rejected").exists())


class IntakeReviewTests(TestCase):
    def setUp(self):
        building = Building.objects.create(name="Review Building")
        category = Category.objects.create(name="Review Category")
        self.resident = User.objects.create_user(username="review_resident", email="review_resident@example.test", password="test", role=User.Role.RESIDENT)
        self.officer = User.objects.create_user(username="review_officer", email="review_officer@example.test", password="test", role=User.Role.CALL_CENTER_STAFF)
        self.report = submit_report(resident=self.resident, category=category, building=building, room_location="A", title="Leak", description="Leak", requested_urgency="LOW")

    def test_officer_review_sets_location_verification(self):
        reviewed = start_review(report_id=self.report.pk, actor=self.officer, expected_version=self.report.version)
        reviewed.refresh_from_db()
        self.assertEqual(reviewed.status, Report.Status.UNDER_REVIEW)
        self.assertEqual(reviewed.location_verified_by, self.officer)
        self.assertIsNotNone(reviewed.location_verified_at)


class ExecutionUATTests(TestCase):
    def setUp(self):
        unit = Unit.objects.create(name="Execution Unit", kind=UnitKind.INTERNAL)
        building = Building.objects.create(name="Execution Building")
        category = Category.objects.create(name="Execution Category")
        self.resident = User.objects.create_user(username="execution_resident", email="execution_resident@example.test", password="test", role=User.Role.RESIDENT)
        self.officer = User.objects.create_user(username="execution_officer", email="execution_officer@example.test", password="test", role=User.Role.CALL_CENTER_STAFF)
        self.technician = User.objects.create_user(username="execution_technician", email="execution_technician@example.test", password="test", role=User.Role.TECHNICIAN_CONTRACTOR, unit=unit)
        self.report = submit_report(
            resident=self.resident,
            category=category,
            building=building,
            room_location="A",
            title="Leak",
            description="Leak",
            requested_urgency="MEDIUM",
        )
        start_review(report_id=self.report.pk, actor=self.officer, expected_version=self.report.version)
        self.report.refresh_from_db()
        from reports.services import assign_technician
        assign_technician(
            report_id=self.report.pk,
            technician=self.technician,
            assigned_by=self.officer,
            priority="MEDIUM",
            expected_version=self.report.version,
        )
        self.report.refresh_from_db()

    def test_uat_07_hold_records_reason_date_and_notifies_resident(self):
        with self.captureOnCommitCallbacks(execute=True):
            held = put_on_hold(
                report_id=self.report.pk,
                technician=self.technician,
                expected_version=self.report.version,
                reason="Waiting for a replacement valve.",
                expected_date=date.today() + timedelta(days=2),
            )
        held.refresh_from_db()
        self.assertEqual(held.status, Report.Status.ON_HOLD)
        self.assertEqual(held.expected_date, date.today() + timedelta(days=2))
        self.assertTrue(Comment.objects.filter(report=held, body="Waiting for a replacement valve.").exists())
        self.assertTrue(Notification.objects.filter(report=held, user=self.resident, message__contains="hold").exists())

    def test_uat_08_completion_records_notes_photo_and_verification_start(self):
        start_work(report_id=self.report.pk, technician=self.technician, expected_version=self.report.version)
        self.report.refresh_from_db()
        assignment = Assignment.objects.get(report=self.report, is_active=True)
        self.assertIsNotNone(assignment.started_at)

        output = BytesIO()
        Image.new("RGB", (8, 8), "white").save(output, format="JPEG")
        photo = SimpleUploadedFile("signature.jpg", output.getvalue(), content_type="image/jpeg")

        completed = complete_work(
            report_id=self.report.pk,
            technician=self.technician,
            expected_version=self.report.version,
            completion_notes="Replaced valve and tested operation.",
            photo=photo,
            requester_signed_on_site=True,
        )
        completed.refresh_from_db()
        assignment.refresh_from_db()
        self.assertEqual(completed.status, Report.Status.COMPLETED)
        self.assertIsNotNone(assignment.completed_at)
        self.assertTrue(assignment.requester_signed_on_site)
        self.assertEqual(assignment.completion_notes, "Replaced valve and tested operation.")
        completion_photo = Photo.objects.get(report=completed, stage=Photo.Stage.COMPLETION)
        self.assertEqual(completion_photo.assignment, assignment)


class CommentUATTests(TestCase):
    def test_uat_11_resident_officer_and_technician_comments_appear_on_ticket(self):
        unit = Unit.objects.create(name="Comment Unit", kind=UnitKind.INTERNAL)
        building = Building.objects.create(name="Comment Building")
        category = Category.objects.create(name="Comment Category")
        resident = User.objects.create_user(username="comment_resident", email="comment_resident@example.test", password="test", role=User.Role.RESIDENT)
        officer = User.objects.create_user(username="comment_officer", email="comment_officer@example.test", password="test", role=User.Role.CALL_CENTER_STAFF)
        technician = User.objects.create_user(username="comment_technician", email="comment_technician@example.test", password="test", role=User.Role.TECHNICIAN_CONTRACTOR, unit=unit)
        report = submit_report(
            resident=resident,
            category=category,
            building=building,
            room_location="A",
            title="Comment test",
            description="Comment test",
            requested_urgency="MEDIUM",
        )
        start_review(report_id=report.pk, actor=officer, expected_version=report.version)
        report.refresh_from_db()
        from reports.services import assign_technician
        assign_technician(
            report_id=report.pk,
            technician=technician,
            assigned_by=officer,
            priority="MEDIUM",
            expected_version=report.version,
        )

        resident_comment = add_comment(
            report_id=report.pk,
            author=resident,
            kind="FOLLOW_UP",
            body="Resident follow-up",
        )
        officer_comment = add_comment(
            report_id=report.pk,
            author=officer,
            kind="COMMENT",
            body="Call Center Staff response",
        )
        technician_comment = add_comment(
            report_id=report.pk,
            author=technician,
            kind="COMMENT",
            body="Technician/Contractor update",
        )

        comments = Comment.objects.filter(report=report).values_list("pk", flat=True)
        self.assertIn(resident_comment.pk, comments)
        self.assertIn(officer_comment.pk, comments)
        self.assertIn(technician_comment.pk, comments)
