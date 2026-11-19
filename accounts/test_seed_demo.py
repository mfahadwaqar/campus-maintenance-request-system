import os
from unittest import mock

from django.core.management import call_command
from django.test import TestCase

from accounts.models import User
from reports.models import Report


class SeedDemoDataTests(TestCase):
    """The setup steps in the README must work on a fresh database."""

    def seed(self):
        with mock.patch.dict(os.environ, {"DEMO_USER_PASSWORD": "Seed-Test-Pass-1!"}):
            call_command("seed_reference_data", verbosity=0)
            call_command("seed_campus_reference_data", verbosity=0)
            call_command("seed_demo_data", verbosity=0)

    def test_the_readme_sequence_creates_accounts_and_tickets_in_each_state(self):
        self.seed()

        self.assertEqual(User.objects.filter(role="RESIDENT").count(), 4)
        self.assertEqual(User.objects.filter(role="CALL_CENTER_STAFF").count(), 2)
        technicians = User.objects.filter(role="TECHNICIAN_CONTRACTOR")
        self.assertEqual(technicians.count(), 4)
        self.assertTrue(all(user.unit_id for user in technicians))
        self.assertTrue(
            User.objects.get(username="demo_officer_01").check_password("Seed-Test-Pass-1!")
        )
        statuses = set(Report.objects.values_list("status", flat=True))
        self.assertEqual(
            statuses, {"SUBMITTED", "UNDER_REVIEW", "ASSIGNED", "IN_PROGRESS", "CLOSED"}
        )

    def test_running_the_seed_twice_does_not_duplicate_anything(self):
        self.seed()
        users, reports = User.objects.count(), Report.objects.count()

        self.seed()

        self.assertEqual(User.objects.count(), users)
        self.assertEqual(Report.objects.count(), reports)
