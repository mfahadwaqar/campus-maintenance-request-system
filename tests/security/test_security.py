"""Security tests (lecture 6.1 'beyond functional correctness' and 6.2 security analysis).

A clean scanner output does not prove access control is safe, so these tests attack the
running application: forged requests, missing CSRF tokens, hostile input, and other users'
data. Negative tests also assert that the database did not change.
"""

import pytest
from django.test import Client
from django.urls import reverse
from rest_framework.test import APIClient

from reports.models import Report
from tests.conftest import PASSWORD

pytestmark = [pytest.mark.security, pytest.mark.blackbox, pytest.mark.django_db]


# ---------------------------------------------------------------- authentication
PROTECTED = [
    "accounts:resident_dashboard",
    "accounts:officer_dashboard",
    "accounts:technician_dashboard",
    "accounts:officer_create_report",
    "accounts:unit_results",
    "reports:list",
    "reports:create",
]


@pytest.mark.parametrize("name", PROTECTED)
def test_anonymous_visitors_are_sent_to_the_login_page(client, name):
    response = client.get(reverse(name))

    assert response.status_code == 302
    assert "/login/" in response["Location"]


def test_anonymous_api_calls_get_a_json_401(client):
    response = APIClient().get("/api/reports/")

    assert response.status_code == 401
    assert response["Content-Type"] == "application/json"


def test_logging_out_ends_the_session(client, resident):
    client.force_login(resident)
    assert client.get(reverse("reports:list")).status_code == 200

    client.post(reverse("accounts:logout"))

    assert client.get(reverse("reports:list")).status_code == 302


def test_the_session_cookie_is_not_readable_by_scripts(client, resident):
    response = client.post(reverse("accounts:login"), {"username": resident.username, "password": PASSWORD})

    assert response.cookies["sessionid"]["httponly"]


def test_a_wrong_password_does_not_log_in_and_does_not_say_which_part_was_wrong(client, resident):
    response = client.post(reverse("accounts:login"), {"username": resident.username, "password": "wrong"})

    assert response.status_code == 200
    assert "_auth_user_id" not in client.session
    api = Client(enforce_csrf_checks=True)
    token = api.get("/accounts/csrf/").json()["csrfToken"]
    unknown = api.post("/api/auth/login/", {"email": "nobody@example.test", "password": "x"}, content_type="application/json", HTTP_X_CSRFTOKEN=token)
    known = api.post("/api/auth/login/", {"email": resident.email, "password": "x"}, content_type="application/json", HTTP_X_CSRFTOKEN=token)
    assert unknown.json() == known.json()


def test_login_does_not_redirect_to_another_site(client, resident):
    response = client.post(
        reverse("accounts:login") + "?next=https://evil.example/steal",
        {"username": resident.username, "password": PASSWORD},
    )

    assert response.status_code == 302
    assert "evil.example" not in response["Location"]


# ---------------------------------------------------------------- CSRF
CSRF_POSTS = [
    ("reports:create", None),
    ("accounts:officer_create_report", None),
    ("assignments:start_work", "report"),
    ("assignments:assign_report", "report"),
    ("reports:reopen", "report"),
    ("reports:verify", "report"),
    ("reports:comments", "report"),
]


@pytest.mark.parametrize("name,needs_report", CSRF_POSTS)
def test_state_changing_pages_reject_a_post_without_a_csrf_token(
    resident, staff, technician, new_report, name, needs_report
):
    report = new_report()
    user = staff if name in {"accounts:officer_create_report", "assignments:assign_report"} else (
        technician if name == "assignments:start_work" else resident
    )
    strict = Client(enforce_csrf_checks=True)
    strict.force_login(user)
    args = [report.pk] if needs_report else []
    before = (Report.objects.count(), report.version)

    response = strict.post(reverse(name, args=args), {"body": "x", "version": report.version})

    assert response.status_code == 403
    report.refresh_from_db()
    assert (Report.objects.count(), report.version) == before


def test_the_api_also_demands_the_csrf_header_for_signed_in_users(resident, new_report):
    strict = APIClient(enforce_csrf_checks=True)
    strict.force_login(resident)

    response = strict.post("/api/auth/logout/")

    assert response.status_code == 403


# ---------------------------------------------------------------- hostile input
XSS = '<script>alert("x")</script>'


def test_html_in_a_title_is_escaped_on_every_page_that_shows_it(
    client, resident, staff, new_report
):
    report = new_report(title=XSS, description=XSS)
    pages = [
        (resident, reverse("reports:detail", args=[report.pk])),
        (resident, reverse("reports:list")),
        (staff, reverse("accounts:officer_dashboard")),
        (staff, reverse("accounts:officer_report_detail", args=[report.pk])),
    ]
    for user, url in pages:
        client.force_login(user)
        body = client.get(url).content.decode()
        assert XSS not in body, url
        assert "&lt;script&gt;" in body, url
    client.force_login(resident)  # the history page does not show titles, but must not echo raw HTML either
    assert XSS not in client.get(reverse("reports:history", args=[report.pk])).content.decode()


def test_html_in_a_comment_is_escaped(client, resident, in_progress_report, flow):
    flow.comment(in_progress_report, resident, XSS)
    client.force_login(resident)

    body = client.get(reverse("reports:detail", args=[in_progress_report.pk])).content.decode()

    assert XSS not in body
    assert "&lt;script&gt;" in body


@pytest.mark.parametrize("hostile", ["' OR '1'='1", "'; DROP TABLE reports; --", "%", "A101\" OR 1=1 --"])
def test_search_input_is_treated_as_data_not_as_sql(client, staff, new_report, hostile):
    new_report(title="Only ticket")
    client.force_login(staff)
    url = reverse("accounts:officer_dashboard")

    for field in ("ticket_no", "student_id"):
        response = client.get(url, {field: hostile})
        assert response.status_code == 200
        assert "Only ticket" not in response.content.decode()
    assert Report.objects.count() == 1  # the table is still there


# ---------------------------------------------------------------- privilege and data isolation (API)
def api_as(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def test_a_resident_cannot_use_staff_or_technician_api_actions(resident, new_report, unit, technician):
    report = new_report()
    client = api_as(resident)

    calls = [
        ("patch", f"/api/reports/{report.pk}/status/", {"status": "UNDER_REVIEW", "version": report.version}),
        ("post", f"/api/reports/{report.pk}/assign/", {"unit": unit.pk, "priority": "HIGH", "version": report.version}),
        ("get", "/api/reports/?room=A1", None),
        ("get", "/api/units/results/", None),
    ]
    for method, url, data in calls:
        response = getattr(client, method)(url, data, format="json") if data else getattr(client, method)(url)
        assert response.status_code == 403, url
    report.refresh_from_db()
    assert report.status == "SUBMITTED"


def test_mass_assignment_cannot_set_status_owner_or_ticket_number(resident, other_resident, building, room, category):
    client = api_as(resident)

    response = client.post(
        "/api/reports/",
        {
            "category": category.pk,
            "building": building.pk,
            "room_location": room.code,
            "room_verified": True,
            "title": "Hack",
            "description": "d",
            "requested_urgency": "LOW",
            "status": "CLOSED",
            "resident": other_resident.pk,
            "ticket_no": "CMR-2026-000000-000001",
            "version": 99,
            "priority": "URGENT",
        },
        format="json",
    )

    assert response.status_code == 201
    report = Report.objects.get()
    assert report.status == "SUBMITTED"
    assert report.resident == resident
    assert report.ticket_no != "CMR-2026-000000-000001"
    assert report.priority is None


READ_ENDPOINTS = ["/api/reports/{id}/", "/api/reports/{id}/comments/", "/api/reports/{id}/history/"]


@pytest.mark.parametrize("template", READ_ENDPOINTS)
def test_another_resident_gets_404_not_403_on_every_ticket_endpoint(other_resident, new_report, template):
    report = new_report()

    response = api_as(other_resident).get(template.format(id=report.pk))

    assert response.status_code == 404


def test_an_unassigned_technician_cannot_read_or_comment(other_technician, assigned_report):
    client = api_as(other_technician)

    assert client.get(f"/api/reports/{assigned_report.pk}/").status_code == 404
    assert client.post(f"/api/reports/{assigned_report.pk}/comments/", {"body": "hi"}, format="json").status_code in {404, 403, 400}
    assert assigned_report.comments.count() == 0


def test_no_password_data_is_ever_returned(resident, staff, new_report):
    new_report()
    for user in (resident, staff):
        client = api_as(user)
        for url in ("/api/auth/me/", "/api/reports/"):
            body = client.get(url).content.decode().lower()
            assert "password" not in body
            assert "pbkdf2" not in body


def test_pages_forbid_framing_and_sniffing(client, resident):
    client.force_login(resident)

    response = client.get(reverse("accounts:resident_dashboard"))

    assert response["X-Frame-Options"] == "DENY"
    assert response["X-Content-Type-Options"] == "nosniff"


def test_the_admin_site_is_closed_to_ordinary_users(client, resident, staff):
    for user in (resident, staff):
        client.force_login(user)
        response = client.get("/admin/")
        assert response.status_code == 302
        assert "/admin/login/" in response["Location"]


def test_an_administrator_with_no_role_cannot_use_the_workflow_pages(client, admin_user):
    client.force_login(admin_user)

    assert client.get(reverse("accounts:officer_dashboard")).status_code == 404
    assert client.get(reverse("reports:create")).status_code == 404
