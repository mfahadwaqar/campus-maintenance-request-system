from django.test import TestCase
from django.urls import reverse

from accounts.models import Building, Role, Unit, UnitKind, User

PASSWORD = "Admin-test-pass-123!"


class UserAdminTests(TestCase):
    def setUp(self):
        self.unit = Unit.objects.create(name="Admin Unit", kind=UnitKind.CONTRACTOR)
        self.building = Building.objects.create(name="Admin Dorm", zone="Zone 1")
        self.superuser = User.objects.create_superuser(
            username="boss", email="boss@example.test", password=PASSWORD
        )
        self.client.force_login(self.superuser)
        self.add_url = reverse("admin:accounts_user_add")

    def add_payload(self, **overrides):
        values = {
            "username": "new_person",
            "usable_password": "true",
            "password1": PASSWORD,
            "password2": PASSWORD,
            "name": "New Person",
            "email": "new.person@example.test",
            "phone": "",
        }
        values.update(overrides)
        return values

    def test_add_form_shows_name_email_role_and_unit(self):
        response = self.client.get(self.add_url)

        for field in ("name", "email", "role", "unit", "is_staff"):
            with self.subTest(field=field):
                self.assertContains(response, f'name="{field}"')

    def test_call_center_staff_can_be_created(self):
        response = self.client.post(
            self.add_url, self.add_payload(role=Role.CALL_CENTER_STAFF)
        )

        self.assertEqual(response.status_code, 302, getattr(response, "context", None) and response.context["adminform"].form.errors)
        user = User.objects.get(username="new_person")
        self.assertEqual(user.role, Role.CALL_CENTER_STAFF)
        self.assertEqual(user.email, "new.person@example.test")
        self.assertEqual(user.name, "New Person")

    def test_a_technician_can_be_created_with_a_unit(self):
        response = self.client.post(
            self.add_url,
            self.add_payload(role=Role.TECHNICIAN_CONTRACTOR, unit=self.unit.pk),
        )

        self.assertEqual(response.status_code, 302)
        user = User.objects.get(username="new_person")
        self.assertEqual(user.unit, self.unit)

    def test_a_technician_without_a_unit_gets_a_message_not_an_error_page(self):
        response = self.client.post(
            self.add_url, self.add_payload(role=Role.TECHNICIAN_CONTRACTOR)
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "must belong to a unit")
        self.assertFalse(User.objects.filter(username="new_person").exists())

    def test_a_user_with_no_role_must_be_staff(self):
        response = self.client.post(self.add_url, self.add_payload())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Choose a role, or tick Staff status")

    def test_an_administrator_can_be_created_without_a_role(self):
        response = self.client.post(
            self.add_url,
            self.add_payload(username="second_admin", is_staff="on", is_superuser="on"),
        )

        self.assertEqual(response.status_code, 302)
        admin = User.objects.get(username="second_admin")
        self.assertIsNone(admin.role)
        self.assertTrue(admin.is_superuser)

    def test_the_new_tables_are_available_in_the_admin(self):
        for name in (
            "accounts_unit",
            "accounts_building",
            "accounts_roomlocation",
            "reports_report",
            "reports_comment",
            "reports_verification",
            "reports_subcategory",
        ):
            with self.subTest(table=name):
                response = self.client.get(reverse(f"admin:{name}_changelist"))
                self.assertEqual(response.status_code, 200)

    def test_reports_cannot_be_added_changed_or_deleted_in_the_admin(self):
        self.assertEqual(self.client.get(reverse("admin:reports_report_add")).status_code, 403)

    def test_user_list_can_be_searched_and_filtered_by_role(self):
        User.objects.create_user(
            username="findable", email="findable@example.test", password="x",
            role=Role.RESIDENT, name="Findable Person",
        )

        response = self.client.get(
            reverse("admin:accounts_user_changelist"), {"q": "Findable", "role__exact": "RESIDENT"}
        )

        self.assertContains(response, "findable@example.test")
