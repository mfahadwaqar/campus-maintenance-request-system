from django.db import DatabaseError, connection, transaction
from django.test import TestCase

from accounts.models import Building, User
from .models import Category, Report, StatusHistory
from .services import submit_report


class DatabaseGuardTests(TestCase):
    def setUp(self):
        self.building = Building.objects.create(name="Guard Building")
        self.category = Category.objects.create(name="Guard Category")
        self.resident = User.objects.create_user(
            username="guard_resident",
            email="guard_resident@example.test",
            password="test",
            role=User.Role.RESIDENT,
        )
        self.report = submit_report(
            resident=self.resident,
            category=self.category,
            building=self.building,
            room_location="Room 1",
            title="Guard test",
            description="Guard test",
            requested_urgency="LOW",
        )

    def test_direct_illegal_status_update_is_refused(self):
        with connection.cursor() as cursor:
            cursor.execute("SELECT set_config('app.current_user_role', 'CALL_CENTER_STAFF', true)")
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                Report.objects.filter(pk=self.report.pk).update(status=Report.Status.CLOSED)
        self.report.refresh_from_db()
        self.assertEqual(self.report.status, Report.Status.SUBMITTED)

    def test_insert_with_non_submitted_status_is_refused(self):
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                Report.objects.create(
                    ticket_no="CMR-2026-guard-000001",
                    resident=self.resident,
                    category=self.category,
                    building=self.building,
                    room_location="Room 2",
                    title="Illegal insert",
                    description="Illegal insert",
                    channel="WEB",
                    status=Report.Status.ASSIGNED,
                )

    def test_status_change_without_role_is_refused(self):
        with connection.cursor() as cursor:
            cursor.execute("SELECT set_config('app.current_user_role', '', true)")
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                Report.objects.filter(pk=self.report.pk).update(status=Report.Status.REJECTED)
        self.report.refresh_from_db()
        self.assertEqual(self.report.status, Report.Status.SUBMITTED)

    def test_uat_12_status_history_update_is_refused_and_row_is_unchanged(self):
        history = StatusHistory.objects.get(report=self.report)
        original_note = history.note

        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(
                        "UPDATE reports_statushistory SET note = %s WHERE id = %s",
                        ["tampered", history.pk],
                    )

        history.refresh_from_db()
        self.assertEqual(history.note, original_note)
