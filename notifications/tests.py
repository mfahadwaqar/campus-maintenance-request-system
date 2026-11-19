from django.core import mail
from django.test import TestCase, override_settings

from accounts.models import Building, User
from notifications.models import Notification
from reports.models import Category
from reports.services import submit_report


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class ReportNotificationTests(TestCase):
    def setUp(self):
        self.officer = User.objects.create_user(
            username="officer",
            password="test-password",
            email="officer@example.test",
            role=User.Role.CALL_CENTER_STAFF,
        )
        self.resident = User.objects.create_user(
            username="resident",
            password="test-password",
            email="resident@example.test",
            role=User.Role.RESIDENT,
        )
        self.category = Category.objects.create(name="Electrical")
        self.building = Building.objects.create(name="East Hall", zone="East")

    def test_submission_notification_email_is_sent_after_commit_without_private_details(self):
        with self.captureOnCommitCallbacks(execute=True):
            report = submit_report(
                resident=self.resident,
                category=self.category,
                building=self.building,
                room_location="Private room 514",
                title="Private title",
                description="Private repair details",
                requested_urgency="MEDIUM",
            )

        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertIn(report.ticket_no, email.body)
        self.assertIn("was submitted", email.body)
        self.assertNotIn("Private room 514", email.body)
        self.assertNotIn("Private title", email.body)
        self.assertNotIn("Private repair details", email.body)

        notification = Notification.objects.get(report=report, user=self.officer)
        self.assertEqual(notification.status, Notification.Status.SENT)
