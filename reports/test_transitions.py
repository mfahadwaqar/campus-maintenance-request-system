from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from accounts.models import Building, Unit, User
from assignments.models import Assignment
from reports.models import Category, Report
from reports.services import _apply_system_transition, apply_transition
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
        if status == "SUBMITTED":
            return report
        if status == "UNDER_REVIEW":
            return apply_transition(report, status, self.officer, room_verified=True)
        if status == "REJECTED":
            return apply_transition(report, status, self.officer, reason="Not valid")
        apply_transition(
            report,
            "ASSIGNED",
            self.officer,
            unit=self.unit,
            technician=self.technician,
        )
        if status == "ASSIGNED":
            return Report.objects.get(pk=report.pk)
        apply_transition(report, "IN_PROGRESS", self.technician)
        if status == "IN_PROGRESS":
            return Report.objects.get(pk=report.pk)
        if status == "ON_HOLD":
            return apply_transition(
                report,
                status,
                self.technician,
                reason="Test hold",
                expected_date=timezone.localdate() + timedelta(days=1),
            )
        apply_transition(report, "COMPLETED", self.technician, completion_notes="Completed")
        if status == "COMPLETED":
            return Report.objects.get(pk=report.pk)
        _apply_system_transition(report, "CLOSED")
        if status == "CLOSED":
            return Report.objects.get(pk=report.pk)
        return report

    def assignment(self, report, technician=None):
        existing = Assignment.objects.filter(report=report).first()
        if existing:
            return existing
        return Assignment.objects.create(report=report, unit=self.unit, technician=technician or self.technician, assigned_by=self.officer)

    def test_exact_seed_is_idempotent(self):
        self.assertEqual(set(ALLOWED_TRANSITIONS), set(tuple(x) for x in __import__('reports.models', fromlist=['AllowedTransition']).AllowedTransition.objects.values_list('from_status','to_status','actor_role')))
        self.assertEqual(len(ALLOWED_TRANSITIONS), 14)
        seed_allowed_transitions()
        self.assertEqual(len(__import__('reports.models', fromlist=['AllowedTransition']).AllowedTransition.objects.all()), 14)

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
            ("CLOSED", "ASSIGNED", "RESIDENT", "CLOSED"),
            ("CLOSED", "ASSIGNED", "CALL_CENTER_STAFF", "CLOSED"),
        ]
        for old, new, role, _ in cases:
            report = self.report(old)
            actor = {"CALL_CENTER_STAFF": self.officer, "TECHNICIAN_CONTRACTOR": self.technician, "RESIDENT": self.resident}[role]
            kwargs = {}
            if new == "UNDER_REVIEW":
                kwargs["room_verified"] = True
            if new == "REJECTED": kwargs["reason"] = "Not valid"
            if new == "ON_HOLD": kwargs.update(reason="Waiting", expected_date=timezone.localdate() + timedelta(days=7))
            if new == "ASSIGNED" and old != "CLOSED":
                kwargs["technician"] = self.technician
                kwargs["unit"] = self.unit
                if old == "UNDER_REVIEW":
                    kwargs["priority"] = "MEDIUM"
            if old == "CLOSED" and new == "ASSIGNED":
                kwargs["reason"] = "Still broken"
            if new == "COMPLETED":
                assignment = self.assignment(report)
                kwargs["completion_notes"] = "Fixed"
            elif old in {"ASSIGNED", "IN_PROGRESS", "ON_HOLD", "REOPENED"} and new in {"IN_PROGRESS", "ON_HOLD"}:
                if not Assignment.objects.filter(report=report, is_active=True).exists():
                    self.assignment(report)
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

    def test_resident_cannot_close_a_completed_report(self):
        report = self.report("COMPLETED")
        with self.assertRaises(ValidationError):
            apply_transition(report, "CLOSED", self.resident)

    def test_actor_role_cannot_be_overridden(self):
        report = self.report("CLOSED")
        with self.assertRaises(ValidationError):
            apply_transition(report, "ASSIGNED", self.resident, actor_role="SYSTEM")

    def test_system_closes_completed_report_immediately(self):
        report = self.report("COMPLETED")
        closed = _apply_system_transition(report, "CLOSED")
        self.assertEqual(closed.status, Report.Status.CLOSED)

    def test_reopening_after_three_days_returns_specific_validation_code(self):
        report = self.report("CLOSED")
        assignment = Assignment.objects.filter(report=report, completed_at__isnull=False).first()
        assignment.completed_at = timezone.now() - timedelta(days=4)
        assignment.save(update_fields=("completed_at",))
        with self.assertRaises(ValidationError) as context:
            apply_transition(report, "ASSIGNED", self.resident, reason="Still broken")
        self.assertEqual(context.exception.code, "reopen_window_closed")
