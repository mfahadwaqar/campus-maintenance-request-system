from django.db import IntegrityError, transaction
from django.test import TestCase

from accounts.models import Building, Unit, User
from assignments.models import Assignment
from reports.models import Category, Comment, Photo, Report, Subcategory, Verification


class ModelConstraintTests(TestCase):
    def setUp(self):
        self.unit = Unit.objects.create(name="Internal Unit", kind="INTERNAL")
        self.resident = User.objects.create_user(username="resident", email="resident@example.com", role="RESIDENT")
        self.officer = User.objects.create_user(username="officer", email="officer@example.com", role="CALL_CENTER_STAFF")
        self.tech = User.objects.create_user(username="tech", email="tech@example.com", role="TECHNICIAN_CONTRACTOR", unit=self.unit)
        self.building = Building.objects.create(name="Block A")
        self.category = Category.objects.create(name="Electrical")
        self.subcategory = Subcategory.objects.create(category=self.category, name="Lighting")

    def report(self, ticket="CMR-2026-127155-000001", **kwargs):
        values = {
            "ticket_no": ticket,
            "resident": self.resident,
            "category": self.category,
            "subcategory": self.subcategory,
            "building": self.building,
            "room_location": "Room 101",
            "title": "Broken light",
            "description": "Light does not work.",
            "channel": "WEB",
        }
        values.update(kwargs)
        return Report.objects.create(**values)

    def assignment(self, report, technician=None, **kwargs):
        values = {
            "report": report,
            "unit": self.unit,
            "technician": technician or self.tech,
            "assigned_by": self.officer,
        }
        values.update(kwargs)
        return Assignment.objects.create(**values)

    def test_technician_requires_unit(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.bulk_create([User(username="no-unit", email="no-unit@example.com", role="TECHNICIAN_CONTRACTOR")])

    def test_assignment_rejects_second_active_assignment(self):
        report = self.report()
        self.assignment(report)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.assignment(report)

    def test_composite_foreign_key_rejects_different_category(self):
        other_category = Category.objects.create(name="Plumbing")
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.report(category=other_category)

    def test_verification_reopened_requires_comment_and_no_rating(self):
        report = self.report()
        assignment = self.assignment(report)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Verification.objects.create(report=report, resident=self.resident, assignment=assignment, outcome="REOPENED", rating=3, comment="Please review")

    def test_photo_completion_requires_assignment(self):
        report = self.report()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Photo.objects.create(report=report, uploaded_by=self.officer, stage="COMPLETION", file_path="completion.jpg", content_type="image/jpeg", size_bytes=100)

    def test_photo_report_stage_rejects_assignment(self):
        report = self.report()
        assignment = self.assignment(report)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Photo.objects.create(report=report, uploaded_by=self.officer, assignment=assignment, stage="REPORT", file_path="report.jpg", content_type="image/jpeg", size_bytes=100)

    def test_comment_body_must_not_be_blank(self):
        report = self.report()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Comment.objects.create(report=report, author=self.resident, body="")

    def test_completed_assignment_requires_notes_and_timestamp(self):
        report = self.report()
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.assignment(report, end_reason="COMPLETED", is_active=False, ended_at="2026-11-05T00:00:00Z")
