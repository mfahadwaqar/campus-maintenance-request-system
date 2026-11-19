from datetime import date, timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Building, RoomLocation, Unit, UnitKind, User
from assignments.models import Assignment
from notifications.models import Notification

from .models import Category, Report
from .services import (
    assign_technician,
    complete_work,
    put_on_hold,
    start_review,
    start_work,
    submit_report,
)
from .templatetags.ui import journey


class RequestPageNotesTests(TestCase):
    """Hold details, completion record and the reopen window on the request pages."""

    def setUp(self):
        self.building = Building.objects.create(name="Dormitory A", zone="Zone 1")
        self.category = Category.objects.create(name="Notes Plumbing")
        RoomLocation.objects.get_or_create(
            code="A101",
            defaults={
                "name": "Dormitory A",
                "location_type": RoomLocation.LocationType.DORMITORY,
            },
        )
        self.unit = Unit.objects.create(name="Notes Unit", kind=UnitKind.INTERNAL)
        self.resident = User.objects.create_user(
            username="st400001",
            email="notes.resident@example.test",
            password="test-password",
            role=User.Role.RESIDENT,
        )
        self.staff = User.objects.create_user(
            username="notes_staff",
            email="notes.staff@example.test",
            password="test-password",
            role=User.Role.CALL_CENTER_STAFF,
        )
        self.technician = User.objects.create_user(
            username="notes_tech",
            email="notes.tech@example.test",
            password="test-password",
            role=User.Role.TECHNICIAN_CONTRACTOR,
            unit=self.unit,
        )
        report = submit_report(
            resident=self.resident,
            category=self.category,
            building=self.building,
            room_location="A101",
            room_verified=True,
            title="Leaking tap",
            description="Dripping all night.",
            requested_urgency="MEDIUM",
        )
        start_review(
            report_id=report.pk,
            actor=self.staff,
            expected_version=report.version,
            room_verified=True,
        )
        report.refresh_from_db()
        assign_technician(
            report_id=report.pk,
            technician=self.technician,
            assigned_by=self.staff,
            unit=self.unit,
            priority="HIGH",
            expected_version=report.version,
        )
        self.report = Report.objects.get(pk=report.pk)

    def start(self):
        self.report.refresh_from_db()
        start_work(
            report_id=self.report.pk,
            technician=self.technician,
            expected_version=self.report.version,
        )
        self.report.refresh_from_db()

    def complete(self, signed=True):
        self.start()
        complete_work(
            report_id=self.report.pk,
            technician=self.technician,
            expected_version=self.report.version,
            completion_notes="Replaced the washer.",
            requester_signed_on_site=signed,
        )
        self.report.refresh_from_db()

    def resident_page(self):
        self.client.force_login(self.resident)
        return self.client.get(reverse("reports:detail", args=[self.report.pk]))

    def test_closed_ticket_shows_completion_record_and_time_left(self):
        self.complete()

        response = self.resident_page()

        self.assertContains(response, "Completion record")
        self.assertContains(response, "Replaced the washer.")
        self.assertContains(response, "Signed on site")
        self.assertContains(response, "Reopen window open")
        self.assertContains(response, "left (until")
        self.assertContains(response, "Reopen request")

    def test_completion_without_the_resident_is_marked(self):
        self.complete(signed=False)

        response = self.resident_page()

        self.assertContains(response, "Completed without the resident present")

    def test_expired_window_says_so_and_offers_no_reopen_form(self):
        self.complete()
        Assignment.objects.filter(report=self.report).update(
            completed_at=timezone.now() - timedelta(days=4)
        )

        response = self.resident_page()

        self.assertContains(response, "3-day reopen window closed on")
        self.assertNotContains(response, "Reopen window open")
        self.assertNotContains(response, 'action="%s"' % reverse("reports:reopen", args=[self.report.pk]))

    def test_staff_see_the_completion_record(self):
        self.complete(signed=False)
        self.client.force_login(self.staff)

        response = self.client.get(
            reverse("accounts:officer_report_detail", args=[self.report.pk])
        )

        self.assertContains(response, "Completion record")
        self.assertContains(response, "Completed without the resident present")

    def test_technician_no_longer_sees_a_closed_ticket(self):
        self.complete()
        self.client.force_login(self.technician)

        response = self.client.get(
            reverse("assignments:technician_report_detail", args=[self.report.pk])
        )

        self.assertEqual(response.status_code, 404)

    def test_hold_reason_and_date_are_visible_to_everyone_involved(self):
        self.start()
        expected = date.today() + timedelta(days=5)
        put_on_hold(
            report_id=self.report.pk,
            technician=self.technician,
            expected_version=self.report.version,
            reason="Waiting for a replacement valve",
            expected_date=expected,
        )
        pages = {
            self.resident: reverse("reports:detail", args=[self.report.pk]),
            self.staff: reverse("accounts:officer_report_detail", args=[self.report.pk]),
            self.technician: reverse("assignments:technician_report_detail", args=[self.report.pk]),
        }

        for user, url in pages.items():
            with self.subTest(role=user.role):
                self.client.force_login(user)
                response = self.client.get(url)
                self.assertContains(response, "Work is on hold")
                self.assertContains(response, "Waiting for a replacement valve")
                self.assertContains(response, expected.strftime("%b"))

    def test_open_ticket_shows_no_completion_record(self):
        response = self.resident_page()

        self.assertNotContains(response, "Completion record")
        self.assertNotContains(response, "Work is on hold")

    def test_journey_ends_at_closed_without_a_separate_done_step(self):
        steps = journey("CLOSED")["steps"]

        self.assertEqual(
            [step["label"] for step in steps],
            ["Sent", "Review", "Assigned", "In progress", "Closed"],
        )
        self.assertTrue(all(step["state"] == "done" for step in steps))

    def test_journey_treats_completed_like_closed(self):
        self.assertEqual(journey("COMPLETED")["steps"][-1]["state"], "done")

    def test_completion_notice_leads_with_the_outcome(self):
        self.complete()

        notice = Notification.objects.filter(
            report=self.report, message__contains="automatically closed after completion"
        ).get()

        self.assertTrue(notice.message.startswith("Your repair is complete."))
        self.assertIn(self.report.ticket_no, notice.message)

    def test_unit_results_page_has_no_scoring_language(self):
        self.client.force_login(self.staff)

        response = self.client.get(reverse("accounts:unit_results"))

        self.assertContains(response, "Unit results")
        self.assertNotContains(response, "KPI")
