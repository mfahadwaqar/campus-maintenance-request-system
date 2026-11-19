from django.test import Client, TestCase
from rest_framework.test import APIClient

from accounts.models import Unit, UnitKind, User

FRONTEND = "http://192.41.170.180:5173"
PASSWORD = "test-password-123"


class AuthApiTests(TestCase):
    def setUp(self):
        self.unit = Unit.objects.create(name="Auth Test Unit", kind=UnitKind.INTERNAL)
        self.resident = User.objects.create_user(
            username="st100001",
            email="Resident.One@Example.Test",
            password=PASSWORD,
            role=User.Role.RESIDENT,
            name="Resident One",
        )
        self.technician = User.objects.create_user(
            username="tech_auth",
            email="tech.auth@example.test",
            password=PASSWORD,
            role=User.Role.TECHNICIAN_CONTRACTOR,
            unit=self.unit,
        )
        self.admin = User.objects.create_user(
            username="admin_auth",
            email="admin.auth@example.test",
            password=PASSWORD,
            is_staff=True,
        )

    def csrf_client(self):
        """A client that enforces CSRF, with the token already fetched."""
        client = Client(enforce_csrf_checks=True)
        response = client.get("/accounts/csrf/")
        return client, response.json()["csrfToken"]

    def login(self, client, token, email="resident.one@example.test", password=PASSWORD):
        return client.post(
            "/api/auth/login/",
            data={"email": email, "password": password},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=token,
        )

    def test_csrf_endpoint_sets_cookie_and_returns_token(self):
        response = Client().get("/accounts/csrf/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["detail"], "CSRF cookie set")
        self.assertTrue(response.json()["csrfToken"])
        self.assertIn("csrftoken", response.cookies)

    def test_login_without_csrf_token_returns_json_403(self):
        client = Client(enforce_csrf_checks=True)

        response = client.post(
            "/api/auth/login/",
            data={"email": "resident.one@example.test", "password": PASSWORD},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response["Content-Type"], "application/json")
        self.assertIn("CSRF", response.json()["detail"])

    def test_login_succeeds_with_204_and_session_cookie(self):
        client, token = self.csrf_client()

        response = self.login(client, token)

        self.assertEqual(response.status_code, 204)
        self.assertIn("sessionid", response.cookies)
        self.assertTrue(response.cookies["sessionid"]["httponly"])

    def test_login_email_is_case_insensitive(self):
        client, token = self.csrf_client()

        response = self.login(client, token, email="RESIDENT.ONE@EXAMPLE.TEST")

        self.assertEqual(response.status_code, 204)

    def test_login_with_wrong_password_returns_401(self):
        client, token = self.csrf_client()

        response = self.login(client, token, password="wrong")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"detail": "Invalid email or password."})
        self.assertNotIn("sessionid", response.cookies)

    def test_login_with_unknown_email_returns_the_same_401(self):
        client, token = self.csrf_client()

        response = self.login(client, token, email="nobody@example.test")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"detail": "Invalid email or password."})

    def test_login_for_inactive_user_returns_401(self):
        self.resident.is_active = False
        self.resident.save(update_fields=("is_active",))
        client, token = self.csrf_client()

        response = self.login(client, token)

        self.assertEqual(response.status_code, 401)

    def test_login_with_missing_fields_returns_400(self):
        client, token = self.csrf_client()

        response = client.post(
            "/api/auth/login/",
            data={"email": "resident.one@example.test"},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=token,
        )

        self.assertEqual(response.status_code, 400)

    def test_login_with_invalid_json_returns_400(self):
        client, token = self.csrf_client()

        response = client.post(
            "/api/auth/login/",
            data="not json",
            content_type="application/json",
            HTTP_X_CSRFTOKEN=token,
        )

        self.assertEqual(response.status_code, 400)

    def test_login_rejects_get(self):
        response = Client().get("/api/auth/login/")

        self.assertEqual(response.status_code, 405)

    def test_me_requires_a_session(self):
        response = APIClient().get("/api/auth/me/")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response["Content-Type"], "application/json")

    def test_me_returns_the_resident_and_role(self):
        client = APIClient()
        client.force_authenticate(self.resident)

        data = client.get("/api/auth/me/").json()

        self.assertEqual(data["role"], "RESIDENT")
        self.assertEqual(data["role_label"], "Resident")
        self.assertEqual(data["student_id"], "st100001")
        self.assertEqual(data["full_name"], "Resident One")
        self.assertIsNone(data["unit"])
        self.assertNotIn("password", data)

    def test_me_returns_the_technician_unit(self):
        client = APIClient()
        client.force_authenticate(self.technician)

        data = client.get("/api/auth/me/").json()

        self.assertEqual(data["role"], "TECHNICIAN_CONTRACTOR")
        self.assertEqual(data["role_label"], "Technician/Contractor")
        self.assertEqual(data["unit"], {"id": self.unit.pk, "name": "Auth Test Unit"})

    def test_me_returns_a_null_role_for_an_administrator(self):
        client = APIClient()
        client.force_authenticate(self.admin)

        data = client.get("/api/auth/me/").json()

        self.assertIsNone(data["role"])
        self.assertEqual(data["role_label"], "")
        self.assertTrue(data["is_staff"])

    def test_login_then_me_then_logout_flow(self):
        client, token = self.csrf_client()
        self.assertEqual(self.login(client, token).status_code, 204)

        me = client.get("/api/auth/me/")
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["role"], "RESIDENT")
        self.assertEqual(client.get("/api/reports/").status_code, 200)

        refreshed = client.get("/accounts/csrf/").json()["csrfToken"]
        logout = client.post("/api/auth/logout/", HTTP_X_CSRFTOKEN=refreshed)
        self.assertEqual(logout.status_code, 204)
        self.assertEqual(client.get("/api/auth/me/").status_code, 401)

    def test_logout_requires_csrf_when_signed_in(self):
        client, token = self.csrf_client()
        self.login(client, token)

        response = client.post("/api/auth/logout/")

        self.assertEqual(response.status_code, 403)

    def test_logout_requires_a_session(self):
        response = APIClient().post("/api/auth/logout/")

        self.assertEqual(response.status_code, 401)

    def test_cors_preflight_allows_the_react_origin_with_credentials(self):
        response = Client().options(
            "/api/auth/login/",
            HTTP_ORIGIN=FRONTEND,
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
            HTTP_ACCESS_CONTROL_REQUEST_HEADERS="content-type, x-csrftoken",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Access-Control-Allow-Origin"], FRONTEND)
        self.assertEqual(response["Access-Control-Allow-Credentials"], "true")
        self.assertIn("x-csrftoken", response["Access-Control-Allow-Headers"].lower())

    def test_cors_applies_to_api_responses_and_the_csrf_endpoint(self):
        for path in ("/accounts/csrf/", "/api/buildings/"):
            with self.subTest(path=path):
                response = Client().get(path, HTTP_ORIGIN=FRONTEND)
                self.assertEqual(response["Access-Control-Allow-Origin"], FRONTEND)

    def test_cors_does_not_allow_an_unknown_origin(self):
        response = Client().options(
            "/api/auth/login/",
            HTTP_ORIGIN="http://evil.example",
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
        )

        self.assertNotIn("Access-Control-Allow-Origin", response)

    def test_cors_does_not_apply_to_the_django_pages(self):
        response = Client().get("/login/", HTTP_ORIGIN=FRONTEND)

        self.assertNotIn("Access-Control-Allow-Origin", response)

    def test_auth_endpoints_are_listed_in_the_api_schema(self):
        response = APIClient().get("/api/schema/?format=json")

        self.assertEqual(response.status_code, 200)
        paths = response.json()["paths"]
        for path in (
            "/accounts/csrf/",
            "/api/auth/login/",
            "/api/auth/logout/",
            "/api/auth/me/",
        ):
            with self.subTest(path=path):
                self.assertIn(path, paths)
