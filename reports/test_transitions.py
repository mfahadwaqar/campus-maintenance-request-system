from datetime import timedelta
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.models import Building, Unit, User
from assignments.models import Assignment
from reports.models import Category, Report
from reports.services import apply_transition
from reports.transitions import ALLOWED_TRANSITIONS, seed_allowed_transitions


class TransitionTests(TestCase):
    def setUp(self):
        seed_allowed_transitions()
        self.unit = Unit.objects.create(name="Unit", kind="INTERNAL")
        self.resident = User.objects.create_user(username="resident", email="resident@example.test", role="RESIDENT")
        self.officer = User.objects.create_user(username="officer", email="officer@example.test", role="CALL_CENTER_STAFF")
        self.technician = User.objects.create_user(username="tech", email="tech@example.test", role="TECHNICIAN_CONTRACTOR", unit=self.unit)
        self.building = Building.objects.create(name="Building")
        self.category = Category.objects.create(name="Category")

    def report(self, status="SUBMITTED"):
        report = Report.objects.create(ticket_no=f"CMR-2026-127155-{Report.objects.count()+1:06d}", resident=self.resident,
            category=self.category, building=self.building, room_location="101", title="Title",
            description="Description", channel="WEB", status="SUBMITTED")
        if status == "UNDER_REVIEW":
            apply_transition(report, status, self.officer)
        elif status == "ASSIGNED":
            apply_transition(report, status, self.officer, unit=self.unit, technician=self.technician)
        elif status in ("IN_PROGRESS", "ON_HOLD", "COMPLETED"):
            apply_transition(report, "ASSIGNED", self.officer, unit=self.unit, technician=self.technician)
            if status == "IN_PROGRESS":
                apply_transition(report, status, self.technician)
            else:
                apply_transition(report, "IN_PROGRESS", self.technician)
                if status == "ON_HOLD":
                    apply_transition(report, status, self.technician, reason="Test hold", expected_date="2026-12-01")
                else:
                    apply_transition(report, status, self.technician, completion_notes="Completed")
        return report

    def assignment(self, report, technician=None):
        existing = Assignment.objects.filter(report=report).first()
        if existing:
            return existing
        return Assignment.objects.create(report=report, unit=self.unit, technician=technician or self.technician, assigned_by=self.officer)

    def test_exact_seed_is_idempotent(self):
        self.assertEqual(set(ALLOWED_TRANSITIONS), set(tuple(x) for x in __import__('reports.models', fromlist=['AllowedTransition']).AllowedTransition.objects.values_list('from_status','to_status','actor_role')))
        self.assertEqual(len(ALLOWED_TRANSITIONS), 16)
        seed_allowed_transitions()
        self.assertEqual(len(__import__('reports.models', fromlist=['AllowedTransition']).AllowedTransition.objects.all()), 16)

    def test_each_allowed_transition_succeeds(self):
        cases = [
            ("SUBMITTED", "UNDER_REVIEW", "CALL_CENTER_STAFF", "SUBMITTED"),
            ("SUBMITTED", "ASSIGNED", "CALL_CENTER_STAFF", "SUBMITTED"),
            ("SUBMITTED", "REJECTED", "CALL_CENTER_STAFF", "SUBMITTED"),
            ("UNDER_REVIEW", "ASSIGNED", "CALL_CENTER_STAFF", "UNDER_REVIEW"),
            ("UNDER_REVIEW", "REJECTED", "CALL_CENTER_STAFF", "UNDER_REVIEW"),
            ("ASSIGNED", "IN_PROGRESS", "TECHNICIAN_CONTRACTOR", "ASSIGNED"),
            ("ASSIGNED", "ON_HOLD", "TECHNICIAN_CONTRACTOR", "ASSIGNED"),
            ("IN_PROGRESS", "ON_HOLD", "TECHNICIAN_CONTRACTOR", "IN_PROGRESS"),
            ("ON_HOLD", "IN_PROGRESS", "TECHNICIAN_CONTRACTOR", "ON_HOLD"),
            ("IN_PROGRESS", "COMPLETED", "TECHNICIAN_CONTRACTOR", "IN_PROGRESS"),
            ("COMPLETED", "REOPENED", "RESIDENT", "COMPLETED"),
        ]
        for old, new, role, _ in cases:
            report = self.report(old)
            actor = {"CALL_CENTER_STAFF": self.officer, "TECHNICIAN_CONTRACTOR": self.technician, "RESIDENT": self.resident}[role]
            kwargs = {}
            if new == "REJECTED": kwargs["reason"] = "Not valid"
            if new == "ON_HOLD": kwargs.update(reason="Waiting", expected_date=timezone.localdate() + timedelta(days=7))
            if new == "ASSIGNED":
                kwargs["technician"] = self.technician
            if new == "COMPLETED":
                assignment = self.assignment(report)
                kwargs["completion_notes"] = "Fixed"
            elif old in {"ASSIGNED", "IN_PROGRESS", "ON_HOLD", "REOPENED"} and new in {"IN_PROGRESS", "ON_HOLD"}:
                if not Assignment.objects.filter(report=report, is_active=True).exists():
                    self.assignment(report)
            elif new == "REOPENED":
                assignment = self.assignment(report)
                assignment.completed_at = timezone.now()
                assignment.save(update_fields=("completed_at",))
                kwargs["reason"] = "Still broken"
            apply_transition(report, new, actor, **kwargs)
            report.refresh_from_db()
            self.assertEqual(report.status, new)

    def test_representative_disallowed_transition_is_refused(self):
        report = self.report("SUBMITTED")
        with self.assertRaises(ValidationError):
            apply_transition(report, "CLOSED", self.resident)
        report.refresh_from_db()
        self.assertEqual(report.status, "SUBMITTED")

    def test_officer_cannot_close_completed_report(self):
        report = self.report("COMPLETED")
        assignment = self.assignment(report)
        assignment.completed_at = timezone.now()
        assignment.save(update_fields=("completed_at",))
        with self.assertRaises(ValidationError):
            apply_transition(report, "CLOSED", self.officer)

    @override_settings(REPAIR_CLOSE_DAYS=15)
    def test_resident_cannot_close_after_window(self):
        report = self.report("COMPLETED")
        assignment = self.assignment(report)
        assignment.completed_at = timezone.now() - timedelta(days=16)
        assignment.save(update_fields=("completed_at",))
        with self.assertRaises(ValidationError):
            apply_transition(report, "CLOSED", self.resident)

    @override_settings(REPAIR_CLOSE_DAYS=15)
    def test_system_cannot_close_inside_window(self):
        report = self.report("COMPLETED")
        assignment = self.assignment(report)
        assignment.completed_at = timezone.now() - timedelta(days=5)
        assignment.save(update_fields=("completed_at",))
        with self.assertRaises(ValidationError):
            apply_transition(report, "CLOSED", self.officer, actor_role="SYSTEM")
