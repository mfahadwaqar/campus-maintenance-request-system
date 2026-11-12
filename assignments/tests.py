from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.core.exceptions import ValidationError
from django.db import close_old_connections, connections
from django.test import TestCase, TransactionTestCase, skipUnlessDBFeature
from django.urls import reverse

from accounts.models import Building, Unit, UnitKind, User
from reports.models import Category, Report, StatusHistory
from reports.services import (
    ReportConflict,
    assign_technician,
    reject_report,
    set_priority,
    start_review,
    submit_report,
)
from .models import Assignment


class OfficerAssignmentWorkflowTests(TestCase):
    def setUp(self):
        self.building = Building.objects.create(name="Assignment Building", zone="Zone A")
        self.category = Category.objects.create(name="Assignment Plumbing")
        self.unit = Unit.objects.create(name="Assignment Unit", kind=UnitKind.INTERNAL)
        self.resident = User.objects.create_user(
            username="assignment_resident",
            password="test-password",
            role=User.Role.RESIDENT,
        )
        self.officer = User.objects.create_user(
            username="assignment_officer",
            password="test-password",
            role=User.Role.CALL_CENTER_STAFF,
        )
        self.technician_one = User.objects.create_user(
            username="technician_one",
            password="test-password",
            role=User.Role.TECHNICIAN_CONTRACTOR,
            unit=self.unit,
        )
        self.technician_two = User.objects.create_user(
            username="technician_two",
            password="test-password",
            role=User.Role.TECHNICIAN_CONTRACTOR,
            unit=self.unit,
        )
        self.report = submit_report(
            resident=self.resident,
            category=self.category,
            building=self.building,
            room_location="Room 12",
            title="Broken tap",
            description="The tap is leaking.",
            requested_urgency="MEDIUM",
        )
        self.client.force_login(self.officer)

    def review_url(self):
        return reverse("accounts:begin_report_review", args=(self.report.pk,))

    def assign_url(self):
        return reverse("assignments:assign_report", args=(self.report.pk,))

    def begin_review(self):
        return self.client.post(self.review_url(), {"version": self.report.version})

    def test_officer_dashboard_shows_review_then_assignment_option(self):
        dashboard = reverse("accounts:officer_dashboard")
        response = self.client.get(dashboard)

        self.assertContains(response, "Begin review")
        self.assertNotContains(response, "Assign technician")

        self.begin_review()
        response = self.client.get(dashboard)

        self.assertContains(response, "Assign technician")
        self.assertContains(
            response,
            reverse("accounts:officer_report_detail", args=(self.report.pk,)),
        )

    def test_officer_assigns_and_reassigns_technician_with_history(self):
        self.begin_review()
        self.report.refresh_from_db()

        response = self.client.post(
            self.assign_url(),
            {
                "technician": self.technician_one.pk,
                "priority": "HIGH",
                "version": self.report.version,
            },
        )

        self.assertRedirects(response, reverse("accounts:officer_dashboard"))
        first_assignment = Assignment.objects.get()
        self.report.refresh_from_db()
        self.assertEqual(self.report.status, Report.Status.ASSIGNED)
        self.assertEqual(self.report.priority, "HIGH")
        self.assertEqual(self.report.version, 3)
        self.assertTrue(first_assignment.is_active)

        response = self.client.post(
            self.assign_url(),
            {
                "technician": self.technician_two.pk,
                "priority": "",
                "version": self.report.version,
            },
        )

        self.assertRedirects(response, reverse("accounts:officer_dashboard"))
        first_assignment.refresh_from_db()
        self.report.refresh_from_db()
        active_assignments = Assignment.objects.filter(
            report=self.report, is_active=True
        )
        self.assertFalse(first_assignment.is_active)
        self.assertEqual(Assignment.objects.count(), 2)
        self.assertEqual(active_assignments.count(), 1)
        self.assertEqual(active_assignments.get().technician, self.technician_two)
        self.assertEqual(self.report.version, 4)
        self.assertEqual(
            list(
                StatusHistory.objects.filter(report=self.report).values_list(
                    "new_status", flat=True
                )
            ),
            [
                Report.Status.SUBMITTED,
                Report.Status.UNDER_REVIEW,
                Report.Status.ASSIGNED,
                Report.Status.ASSIGNED,
            ],
        )

    def test_assignment_requires_priority_on_initial_assignment(self):
        self.begin_review()
        self.report.refresh_from_db()

        response = self.client.post(
            self.assign_url(),
            {
                "technician": self.technician_one.pk,
                "priority": "",
                "version": self.report.version,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "This field is required.")
        self.assertEqual(Assignment.objects.count(), 0)
        self.report.refresh_from_db()
        self.assertEqual(self.report.status, Report.Status.UNDER_REVIEW)

    def test_officer_can_open_assignment_form_before_saving_priority(self):
        self.begin_review()
        self.report.refresh_from_db()

        dashboard = self.client.get(reverse("accounts:officer_dashboard"))
        assignment_form = self.client.get(self.assign_url())

        self.assertContains(dashboard, reverse("assignments:assign_report", args=(self.report.pk,)))
        self.assertEqual(assignment_form.status_code, 200)
        self.assertContains(assignment_form, 'name="technician"')
        self.assertContains(assignment_form, 'name="priority"')
        self.assertContains(assignment_form, "Confirm assignment")

    def test_stale_assignment_version_returns_conflict_without_changes(self):
        self.begin_review()

        response = self.client.post(
            self.assign_url(),
            {
                "technician": self.technician_one.pk,
                "priority": "MEDIUM",
                "version": 1,
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Assignment.objects.count(), 1)
        self.report.refresh_from_db()
        self.assertEqual(self.report.status, Report.Status.ASSIGNED)

    def test_resident_cannot_open_officer_assignment_form(self):
        self.client.force_login(self.resident)

        response = self.client.get(self.assign_url())

        self.assertEqual(response.status_code, 404)

    def test_assignment_is_not_performed_by_get(self):
        self.begin_review()
        self.report.refresh_from_db()

        response = self.client.get(self.assign_url())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Assignment.objects.count(), 0)
        self.assertEqual(self.report.status, Report.Status.UNDER_REVIEW)

    def test_start_review_updates_status_version_and_history(self):
        response = self.begin_review()

        self.assertRedirects(response, reverse("accounts:officer_dashboard"))
        self.report.refresh_from_db()
        self.assertEqual(self.report.status, Report.Status.UNDER_REVIEW)
        self.assertEqual(self.report.version, 2)
        history = StatusHistory.objects.get(report=self.report, new_status="UNDER_REVIEW")
        self.assertEqual(history.changed_by, self.officer)

    def test_priority_update_records_auditable_change(self):
        self.begin_review()
        self.report.refresh_from_db()

        updated = set_priority(
            report_id=self.report.pk,
            priority="HIGH",
            actor=self.officer,
            expected_version=self.report.version,
        )

        self.assertEqual(updated.priority, "HIGH")
        self.assertEqual(updated.version, 3)
        history = StatusHistory.objects.filter(report=self.report).latest("pk")
        self.assertEqual(history.old_status, Report.Status.UNDER_REVIEW)
        self.assertEqual(history.new_status, Report.Status.UNDER_REVIEW)
        self.assertIn("unset to HIGH", history.note)


class AssignmentUATTests(TestCase):
    def setUp(self):
        self.unit = Unit.objects.create(name="UAT Unit", kind=UnitKind.INTERNAL)
        self.building = Building.objects.create(name="UAT Building")
        self.category = Category.objects.create(name="UAT Category")
        self.resident = User.objects.create_user(username="uat_resident", email="uat_resident@example.com", password="test", role=User.Role.RESIDENT)
        self.officer = User.objects.create_user(username="uat_officer", email="uat_officer@example.com", password="test", role=User.Role.CALL_CENTER_STAFF)
        self.technician = User.objects.create_user(username="uat_technician", email="uat_technician@example.com", password="test", role=User.Role.TECHNICIAN_CONTRACTOR, unit=self.unit)
        self.other_technician = User.objects.create_user(username="uat_technician_2", email="uat_technician_2@example.com", password="test", role=User.Role.TECHNICIAN_CONTRACTOR, unit=self.unit)
        self.report = submit_report(resident=self.resident, category=self.category, building=self.building, room_location="R1", title="UAT repair", description="Repair requested", requested_urgency="MEDIUM")

    def test_uat_04_initial_assignment_creates_one_active_assignment(self):
        from .services import assign_technician
        assign_technician(self.report, self.unit, self.technician, self.officer)
        self.report.refresh_from_db()
        active = Assignment.objects.get(report=self.report, is_active=True)
        self.assertEqual(self.report.status, Report.Status.ASSIGNED)
        self.assertEqual(active.unit, self.unit)
        self.assertEqual(active.technician, self.technician)

    def test_uat_06_reassignment_creates_history_for_new_assignment(self):
        from .services import assign_technician, reassign
        assign_technician(self.report, self.unit, self.technician, self.officer)
        old = Assignment.objects.get(report=self.report, is_active=True)
        reassign(self.report, self.unit, self.other_technician, self.officer)
        old.refresh_from_db()
        new = Assignment.objects.get(report=self.report, is_active=True)
        self.assertFalse(old.is_active)
        self.assertEqual(old.end_reason, "REASSIGNED")
        self.assertEqual(new.technician, self.other_technician)
        self.assertTrue(StatusHistory.objects.filter(report=self.report, assignment=new, old_status="ASSIGNED", new_status="ASSIGNED").exists())


@skipUnlessDBFeature("has_select_for_update")
class AssignmentConcurrencyUATTests(TransactionTestCase):
    reset_sequences = True

    def test_uat_05_concurrent_reassignment_produces_one_active_assignment_and_one_refusal(self):
        unit = Unit.objects.create(name="Concurrent Unit", kind=UnitKind.INTERNAL)
        building = Building.objects.create(name="Concurrent Building")
        category = Category.objects.create(name="Concurrent Category")
        resident = User.objects.create_user(username="concurrent_resident", email="concurrent_resident@example.com", password="test", role=User.Role.RESIDENT)
        officer = User.objects.create_user(username="concurrent_officer", email="concurrent_officer@example.com", password="test", role=User.Role.CALL_CENTER_STAFF)
        technician = User.objects.create_user(username="concurrent_old", email="concurrent_old@example.com", password="test", role=User.Role.TECHNICIAN_CONTRACTOR, unit=unit)
        target = User.objects.create_user(username="concurrent_target", email="concurrent_target@example.com", password="test", role=User.Role.TECHNICIAN_CONTRACTOR, unit=unit)
        report = submit_report(resident=resident, category=category, building=building, room_location="R1", title="Concurrent repair", description="Repair requested", requested_urgency="MEDIUM")

        from .services import assign_technician
        assign_technician(report, unit, technician, officer)

        barrier = Barrier(3)
        results = []
        def worker():
            close_old_connections()
            try:
                from .services import reassign
                barrier.wait()
                reassign(Report.objects.get(pk=report.pk), Unit.objects.get(pk=unit.pk), User.objects.get(pk=target.pk), User.objects.get(pk=officer.pk))
                results.append("success")
            except ValidationError as exc:
                results.append("refused")
            finally:
                connections.close_all()
                barrier.wait()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(worker) for _ in range(2)]
            barrier.wait()
            barrier.wait()
            for future in futures:
                future.result()

        self.assertEqual(sorted(results), ["refused", "success"])
        self.assertEqual(Assignment.objects.filter(report_id=report.pk, is_active=True).count(), 1)
