"""Regression tests: each one guards a defect that was found in this project and fixed.

Lecture 6.1: when fixing a bug, first write a failing test that reproduces it, then fix the
code, and keep the test so the bug cannot silently return.
"""

import os
from pathlib import Path
from unittest import mock

import pytest
from django.core.management import call_command
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.models import User
from reports.models import Report, Verification

pytestmark = [pytest.mark.regression, pytest.mark.django_db]

ROOT = Path(__file__).resolve().parents[2]


def test_R1_a_held_job_can_be_resumed_from_its_work_order_page(client, in_progress_report, flow, technician):
    """Found 19 Nov 2026 while mapping the hold flow: after 'hold' the page had no way to resume."""
    flow.hold(in_progress_report)
    client.force_login(technician)
    page = reverse("assignments:technician_report_detail", args=[in_progress_report.pk])

    assert "Resume work" in client.get(page).content.decode()
    client.post(
        reverse("assignments:start_work", args=[in_progress_report.pk]),
        {"version": in_progress_report.version},
    )
    in_progress_report.refresh_from_db()
    assert in_progress_report.status == "IN_PROGRESS"


def test_R2_reopening_after_verifying_replaces_the_verification_instead_of_crashing(
    client, closed_report, resident
):
    """Found 20 Nov 2026 by the end-to-end journey: verify then reopen raised a unique-constraint error."""
    client.force_login(resident)
    client.post(reverse("reports:verify", args=[closed_report.pk]), {"version": closed_report.version, "rating": 5})
    closed_report.refresh_from_db()

    response = client.post(
        reverse("reports:reopen", args=[closed_report.pk]),
        {"version": closed_report.version, "reason": "Dripping again"},
    )

    assert response.status_code == 302
    closed_report.refresh_from_db()
    assert closed_report.status == "ASSIGNED"
    row = Verification.objects.get(report=closed_report)
    assert (row.outcome, row.rating, row.comment) == ("REOPENED", None, "Dripping again")


def test_R3_a_search_the_form_cannot_read_shows_no_tickets_and_an_error(client, staff, new_report):
    """Found 20 Nov 2026: a ticket number longer than 30 characters silently listed every ticket."""
    new_report(title="Visible only when unfiltered")
    client.force_login(staff)

    response = client.get(reverse("accounts:officer_dashboard"), {"ticket_no": "x" * 31})

    body = response.content.decode()
    assert "Visible only when unfiltered" not in body
    assert "at most 30 characters" in body


def test_R4_unit_results_use_the_names_in_the_api_specification(staff):
    """Found 20 Nov 2026: the payload had longer names than the written specification."""
    client = APIClient()
    client.force_authenticate(staff)

    rows = client.get("/api/units/results/?period=all").json()

    assert rows == [] or {"unit", "jobs_completed", "average_hours"} <= set(rows[0])


def test_R5_login_accepts_the_email_in_any_letter_case(resident):
    """Found 14 Nov 2026: email lookup was case-sensitive in the first draft of the login."""
    from django.test import Client

    strict = Client(enforce_csrf_checks=True)
    token = strict.get("/accounts/csrf/").json()["csrfToken"]

    response = strict.post(
        "/api/auth/login/",
        {"email": resident.email.upper(), "password": "Test-pass-12345!"},
        content_type="application/json",
        HTTP_X_CSRFTOKEN=token,
    )

    assert response.status_code == 204


def test_R6_the_demo_seed_runs_to_the_end_on_a_fresh_database():
    """Found 20 Nov 2026: seed_demo_data raised NameError (technicians) and a TypeError on assignment."""
    with mock.patch.dict(os.environ, {"DEMO_USER_PASSWORD": "Regression-Pass-1!"}):
        call_command("seed_reference_data", verbosity=0)
        call_command("seed_campus_reference_data", verbosity=0)
        call_command("seed_demo_data", verbosity=0)

    assert Report.objects.filter(status="CLOSED").exists()
    assert User.objects.filter(username="demo_technician_01").exists()


def test_R7_subcategory_options_carry_their_category_so_the_page_can_filter_them(
    client, resident, category, subcategory
):
    """Found 20 Nov 2026: choosing a category then a stale subcategory gave a confusing error."""
    client.force_login(resident)

    body = client.get(reverse("reports:create")).content.decode()

    assert f'data-category="{category.pk}"' in body
    assert "Choose a category first" in body


def test_R8_the_progress_line_has_no_separate_done_step():
    """Found 17 Nov 2026: completion now closes the ticket, so 'Done' and 'Closed' were duplicates."""
    from reports.templatetags.ui import journey

    labels = [step["label"] for step in journey("CLOSED")["steps"]]

    assert "Done" not in labels
    assert labels[-1] == "Closed"


def test_R9_the_stylesheet_is_light_only_and_checkbox_labels_sit_beside_their_boxes():
    """Found 20 Nov 2026: the dark theme misaligned the layout; checkboxes were centred below labels."""
    css = (ROOT / "accounts" / "static" / "accounts" / "style.css").read_text(encoding="utf8")

    assert "prefers-color-scheme" not in css
    assert 'input[type="checkbox"]' in css


def test_R10_a_technician_loses_access_to_a_ticket_when_it_closes(client, in_progress_report, flow, technician):
    """Design rule (permission matrix): technicians only see jobs they actively hold."""
    flow.complete(in_progress_report)
    client.force_login(technician)

    response = client.get(reverse("assignments:technician_report_detail", args=[in_progress_report.pk]))

    assert response.status_code == 404


def test_R11_no_code_path_closes_a_ticket_after_a_waiting_period(settings):
    """Change list #3: the 15-day closure job and its setting were removed (OFAM, 11 Nov 2026)."""
    from django.core.management import get_commands

    for name in ("REPAIR_CLOSE_DAYS", "AUTO_CLOSE_COMPLETED_DAYS", "REOPEN_AFTER_CLOSED_DAYS"):
        assert not hasattr(settings, name), name
    assert not [command for command in get_commands() if "close" in command]


STALE_WORDS = ["Officer", "Unit Staff", "KPI", "mobile app", "15-day", "master request"]


@pytest.mark.parametrize("role", ["resident", "staff", "technician"])
def test_R12_no_page_uses_retired_wording(client, resident, staff, technician, closed_report, role):
    """Change list #21 and #22: no page shows 'Officer', 'Unit Staff', KPI, mobile apps or merging."""
    user = {"resident": resident, "staff": staff, "technician": technician}[role]
    urls = {
        "resident": [reverse("accounts:resident_dashboard"), reverse("reports:list"), reverse("reports:create"),
                     reverse("reports:detail", args=[closed_report.pk])],
        "staff": [reverse("accounts:officer_dashboard"), reverse("accounts:officer_create_report"),
                  reverse("accounts:unit_results"), reverse("accounts:officer_report_detail", args=[closed_report.pk])],
        "technician": [reverse("accounts:technician_dashboard"), reverse("accounts:unit_results")],
    }[role]
    client.force_login(user)

    for url in urls:
        body = client.get(url).content.decode()
        for word in STALE_WORDS:
            assert word not in body, f"{word!r} on {url}"


def test_R13_a_technician_sees_the_residents_photo_on_the_work_order_page(client, new_report, flow, technician):
    """Found 20 Nov 2026 in manual testing: the photo was only a text link that downloaded as a file."""
    from reports.models import Photo
    from reports.storage import private_photo_storage
    from tests.conftest import jpeg_upload

    report = new_report(photo=jpeg_upload())
    flow.assign(report)
    photo = Photo.objects.get(report=report)
    client.force_login(technician)
    url = reverse("reports:photo_download", args=[report.pk, photo.pk])

    page = client.get(reverse("assignments:technician_report_detail", args=[report.pk])).content.decode()
    response = client.get(url)
    disposition = response["Content-Disposition"]
    content_type = response["Content-Type"]
    for closer in response._resource_closers:  # release the file on Windows
        closer()
    saved = client.get(url + "?download=1")
    saved_disposition = saved["Content-Disposition"]
    for closer in saved._resource_closers:
        closer()
    private_photo_storage.delete(photo.file_path)

    assert f'<img class="photo-thumb" src="{url}"' in page
    assert (response.status_code, content_type) == (200, "image/jpeg")
    assert disposition.startswith("inline")
    assert saved_disposition.startswith("attachment")
