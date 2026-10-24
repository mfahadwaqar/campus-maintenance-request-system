from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.core.exceptions import ValidationError
from django.db import connections
from django.test import TestCase, TransactionTestCase, skipUnlessDBFeature
from django.urls import reverse

from accounts.models import Building, User
from reports.models import Category, Report, StatusHistory
from reports.services import (
    ReportConflict,
    assign_technician,
    mark_duplicate,
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
        self.resident = User.objects.create_user(
            username="assignment_resident",
            password="test-password",
            role=User.Role.RESIDENT,
        )
        self.officer = User.objects.create_user(
            username="assignment_officer",
            password="test-password",
            role=User.Role.OFFICER,
        )
        self.technician_one = User.objects.create_user(
            username="technician_one",
            password="test-password",
            role=User.Role.TECHNICIAN,
        )
        self.technician_two = User.objects.create_user(
            username="technician_two",
            password="test-password",
            role=User.Role.TECHNICIAN,
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

        self.assertEqual(response.status_code, 409)
        self.assertContains(response, "changed", status_code=409)
        self.assertEqual(Assignment.objects.count(), 0)
        self.report.refresh_from_db()
        self.assertEqual(self.report.status, Report.Status.UNDER_REVIEW)

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

    def test_reject_requires_reason_and_records_reason_in_history(self):
        self.begin_review()
        self.report.refresh_from_db()

        with self.assertRaisesMessage(ValidationError, "A rejection reason is required"):
            reject_report(
                report_id=self.report.pk,
                reason="  ",
                actor=self.officer,
                expected_version=self.report.version,
            )
        self.assertEqual(Report.objects.get(pk=self.report.pk).status, Report.Status.UNDER_REVIEW)

        rejected = reject_report(
            report_id=self.report.pk,
            reason="Outside campus maintenance scope.",
            actor=self.officer,
            expected_version=self.report.version,
        )

        self.assertEqual(rejected.status, Report.Status.REJECTED)
        self.assertEqual(rejected.version, 3)
        self.assertEqual(
            StatusHistory.objects.filter(report=rejected).latest("pk").note,
            "Outside campus maintenance scope.",
        )

    def test_mark_duplicate_keeps_duplicate_history_and_links_master(self):
        master = submit_report(
            resident=self.resident,
            category=self.category,
            building=self.building,
            room_location="Room 13",
            title="Master leak request",
            description="Master report.",
            requested_urgency="LOW",
        )
        self.begin_review()
        self.report.refresh_from_db()
        existing_history = self.report.status_history.count()

        duplicate = mark_duplicate(
            report_id=self.report.pk,
            master_report_id=master.pk,
            actor=self.officer,
            expected_version=self.report.version,
        )

        self.assertEqual(duplicate.status, Report.Status.MERGED)
        self.assertEqual(duplicate.merged_into, master)
        self.assertEqual(duplicate.status_history.count(), existing_history + 1)
        self.assertEqual(duplicate.status_history.latest("pk").new_status, Report.Status.MERGED)
        self.assertEqual(master.status, Report.Status.SUBMITTED)

    def test_mark_duplicate_rejects_merged_or_rejected_master_without_changes(self):
        self.begin_review()
        self.report.refresh_from_db()
        master = submit_report(
            resident=self.resident,
            category=self.category,
            building=self.building,
            room_location="Room 13",
            title="Rejected master",
            description="Cannot be used as master.",
            requested_urgency="LOW",
        )
        start_review(
            report_id=master.pk,
            actor=self.officer,
            expected_version=master.version,
        )
        master.refresh_from_db()
        reject_report(
            report_id=master.pk,
            reason="This report cannot be a master.",
            actor=self.officer,
            expected_version=master.version,
        )
        history_count = self.report.status_history.count()

        with self.assertRaisesMessage(ValidationError, "must not be merged or rejected"):
            mark_duplicate(
                report_id=self.report.pk,
                master_report_id=master.pk,
                actor=self.officer,
                expected_version=self.report.version,
            )

        self.report.refresh_from_db()
        self.assertEqual(self.report.status, Report.Status.UNDER_REVIEW)
        self.assertIsNone(self.report.merged_into)
        self.assertEqual(self.report.status_history.count(), history_count)

    def test_wrong_role_or_invalid_assignment_transition_changes_nothing(self):
        original_history_count = self.report.status_history.count()
        with self.assertRaises(ValidationError):
            start_review(
                report_id=self.report.pk,
                actor=self.resident,
                expected_version=self.report.version,
            )
        with self.assertRaises(ValidationError):
            assign_technician(
                report_id=self.report.pk,
                technician=self.technician_one,
                assigned_by=self.officer,
                priority="HIGH",
                expected_version=self.report.version,
            )

        self.report.refresh_from_db()
        self.assertEqual(self.report.status, Report.Status.SUBMITTED)
        self.assertEqual(self.report.version, 1)
        self.assertEqual(Assignment.objects.count(), 0)
        self.assertEqual(self.report.status_history.count(), original_history_count)

    def test_wrong_role_cannot_set_priority_reject_or_mark_duplicate(self):
        self.begin_review()
        self.report.refresh_from_db()
        history_count = self.report.status_history.count()
        master = submit_report(
            resident=self.resident,
            category=self.category,
            building=self.building,
            room_location="Room 14",
            title="Potential master",
            description="Another report.",
            requested_urgency="LOW",
        )

        for action in (
            lambda: set_priority(
                report_id=self.report.pk,
                priority="HIGH",
                actor=self.resident,
                expected_version=self.report.version,
            ),
            lambda: reject_report(
                report_id=self.report.pk,
                reason="Not allowed",
                actor=self.resident,
                expected_version=self.report.version,
            ),
            lambda: mark_duplicate(
                report_id=self.report.pk,
                master_report_id=master.pk,
                actor=self.resident,
                expected_version=self.report.version,
            ),
        ):
            with self.subTest(action=action):
                with self.assertRaises(ValidationError):
                    action()
                self.report.refresh_from_db()
                self.assertEqual(self.report.status, Report.Status.UNDER_REVIEW)
                self.assertEqual(self.report.version, 2)
                self.assertEqual(self.report.status_history.count(), history_count)

    def test_mismatched_specialization_is_noted_in_history(self):
        self.begin_review()
        self.report.refresh_from_db()

        assign_technician(
            report_id=self.report.pk,
            technician=self.technician_one,
            assigned_by=self.officer,
            priority="MEDIUM",
            expected_version=self.report.version,
        )

        self.assertIn(
            "specialization does not match",
            StatusHistory.objects.filter(report=self.report).latest("pk").note,
        )

    def test_officer_queue_filters_and_paginates(self):
        self.begin_review()
        self.report.refresh_from_db()
        set_priority(
            report_id=self.report.pk,
            priority="HIGH",
            actor=self.officer,
            expected_version=self.report.version,
        )
        other_category = Category.objects.create(name="Assignment Electrical")
        for index in range(26):
            submit_report(
                resident=self.resident,
                category=other_category,
                building=self.building,
                room_location=f"Room {100 + index}",
                title=f"Electrical request {index}",
                description="A separate report.",
                requested_urgency="LOW",
            )

        response = self.client.get(
            reverse("accounts:officer_dashboard"),
            {"category": self.category.pk, "priority": "HIGH"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["page_obj"].paginator.count, 1)
        self.assertContains(response, self.report.title)
        self.assertNotContains(response, "Electrical request")

        response = self.client.get(reverse("accounts:officer_dashboard"))
        self.assertEqual(response.context["page_obj"].paginator.num_pages, 2)

    def test_officer_detail_contains_triage_forms(self):
        response = self.client.get(
            reverse("accounts:officer_report_detail", args=(self.report.pk,))
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Begin review")
        self.assertContains(response, self.report.room_location)

    def test_resident_cannot_use_triage_endpoints(self):
        self.client.force_login(self.resident)

        response = self.client.post(
            reverse("accounts:reject_report", args=(self.report.pk,)),
            {"reason": "No", "version": self.report.version},
        )

        self.assertEqual(response.status_code, 404)
        self.report.refresh_from_db()
        self.assertEqual(self.report.status, Report.Status.SUBMITTED)


@skipUnlessDBFeature("has_select_for_update")
class ConcurrentAssignmentTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.building = Building.objects.create(name="Concurrent Building", zone="Zone C")
        self.category = Category.objects.create(name="Concurrent Plumbing")
        self.resident = User.objects.create_user(
            username="concurrent_resident", role=User.Role.RESIDENT
        )
        self.officers = [
            User.objects.create_user(
                username=f"concurrent_officer_{index}", role=User.Role.OFFICER
            )
            for index in range(2)
        ]
        self.technicians = [
            User.objects.create_user(
                username=f"concurrent_technician_{index}", role=User.Role.TECHNICIAN
            )
            for index in range(2)
        ]
        self.report = submit_report(
            resident=self.resident,
            category=self.category,
            building=self.building,
            room_location="Room C1",
            title="Concurrent assignment request",
            description="Request for concurrency test.",
            requested_urgency="MEDIUM",
        )
        self.report = start_review(
            report_id=self.report.pk,
            actor=self.officers[0],
            expected_version=self.report.version,
        )
        self.report = set_priority(
            report_id=self.report.pk,
            priority="MEDIUM",
            actor=self.officers[0],
            expected_version=self.report.version,
        )

    def test_simultaneous_assignments_allow_exactly_one_active_assignment(self):
        barrier = Barrier(2)

        def attempt(index):
            barrier.wait(timeout=10)
            try:
                assign_technician(
                    report_id=self.report.pk,
                    technician=self.technicians[index],
                    assigned_by=self.officers[index],
                    priority="MEDIUM",
                    expected_version=self.report.version,
                )
                return "success"
            except ReportConflict:
                return "conflict"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(attempt, range(2)))

        self.assertCountEqual(outcomes, ["success", "conflict"])
        assignments = Assignment.objects.filter(report=self.report)
        self.assertEqual(assignments.count(), 1)
        self.assertEqual(assignments.filter(is_active=True).count(), 1)
        self.report.refresh_from_db()
        self.assertEqual(self.report.status, Report.Status.ASSIGNED)
        self.assertEqual(self.report.version, 4)
