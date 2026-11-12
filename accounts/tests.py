from django.test import TestCase
from django.urls import reverse

from .models import Unit, UnitKind, User


class RoleDashboardTests(TestCase):
    def setUp(self):
        self.password = "test-password-only"

    def create_user(self, username, role):
        unit = None
        if role == User.Role.TECHNICIAN_CONTRACTOR:
            unit, _ = Unit.objects.get_or_create(
                name="Test Unit", defaults={"kind": UnitKind.INTERNAL}
            )
        return User.objects.create_user(
            username=username,
            password=self.password,
            email=f"{username}@example.test",
            role=role,
            unit=unit,
        )

    def test_login_redirects_each_role_to_its_dashboard(self):
        dashboards = {
            User.Role.RESIDENT: "accounts:resident_dashboard",
            User.Role.CALL_CENTER_STAFF: "accounts:officer_dashboard",
            User.Role.TECHNICIAN_CONTRACTOR: "accounts:technician_dashboard",
        }
        for role, dashboard_name in dashboards.items():
            with self.subTest(role=role):
                user = self.create_user(f"user_{role.lower()}", role)
                response = self.client.post(
                    reverse("accounts:login"),
                    {"username": user.username, "password": self.password},
                )
                self.assertRedirects(
                    response, reverse(dashboard_name), fetch_redirect_response=False
                )
                self.client.logout()

    def test_anonymous_user_is_redirected_to_login_from_dashboard(self):
        response = self.client.get(reverse("accounts:resident_dashboard"))

        self.assertRedirects(
            response,
            f"{reverse('accounts:login')}?next={reverse('accounts:resident_dashboard')}",
            fetch_redirect_response=False,
        )

    def test_home_redirects_anonymous_user_to_login(self):
        response = self.client.get(reverse("accounts:home"))

        self.assertRedirects(
            response,
            f"{reverse('accounts:login')}?next=/",
            fetch_redirect_response=False,
        )

    def test_home_redirects_authenticated_user_to_role_dashboard(self):
        user = self.create_user("resident_home", User.Role.RESIDENT)
        self.client.force_login(user)

        response = self.client.get(reverse("accounts:home"))

        self.assertRedirects(
            response,
            reverse("accounts:resident_dashboard"),
            fetch_redirect_response=False,
        )

    def test_resident_cannot_open_officer_or_technician_dashboard(self):
        user = self.create_user("resident", User.Role.RESIDENT)
        self.client.force_login(user)

        for dashboard_name in (
            "accounts:officer_dashboard",
            "accounts:technician_dashboard",
        ):
            with self.subTest(dashboard=dashboard_name):
                response = self.client.get(reverse(dashboard_name))
                self.assertEqual(response.status_code, 404)


class LoginRoleSelectionTests(TestCase):
    def test_login_does_not_accept_role_from_request_data(self):
        user = User.objects.create_user(
            username="resident",
            password="test-password-only",
            email="resident@example.test",
            role=User.Role.RESIDENT,
        )

        response = self.client.post(
            reverse("accounts:login"),
            {
                "username": user.username,
                "password": "test-password-only",
                "role": User.Role.CALL_CENTER_STAFF,
            },
        )

        self.assertRedirects(
            response,
            reverse("accounts:resident_dashboard"),
            fetch_redirect_response=False,
        )
        user.refresh_from_db()
        self.assertEqual(user.role, User.Role.RESIDENT)


class HealthCheckTests(TestCase):
    def test_health_check_returns_ok(self):
        response = self.client.get(reverse("health"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})
