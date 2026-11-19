"""Integration tests: URL -> view -> ORM -> database -> response, through the real pages.

Grey-box design (lecture 6.1): drive the public pages like a user, then use our knowledge of
the data model to check the exact database state after each step.
"""

import pytest
from django.urls import reverse

from assignments.models import Assignment
from reports.models import Comment, Photo, Report, StatusHistory, Verification
from tests.conftest import jpeg_upload

pytestmark = [pytest.mark.integration, pytest.mark.greybox, pytest.mark.django_db]


def statuses(report):
    return list(
        StatusHistory.objects.filter(report=report)
        .order_by("pk")
        .values_list("new_status", flat=True)
    )


def release(response):
    """Close a streamed file so Windows can delete it (response.close() would close the test DB)."""
    for closer in getattr(response, "_resource_closers", ()):
        closer()


def test_a_ticket_travels_from_submission_to_a_reopened_assignment(
    client, resident, staff, technician, unit, building, room, category, subcategory
):
    # --- resident submits
    client.force_login(resident)
    response = client.post(
        reverse("reports:create"),
        {
            "category": category.pk,
            "subcategory": subcategory.pk,
            "building": building.pk,
            "room_location": room.code,
            "room_verified": "on",
            "title": "Leaking tap in A101",
            "description": "Drips all night.",
            "requested_urgency": "HIGH",
        },
    )
    report = Report.objects.get()
    assert response.status_code == 302
    assert (report.resident, report.status, report.channel) == (resident, "SUBMITTED", "WEB")
    assert report.ticket_no.startswith("CMR-2026-900001-")

    # --- staff review, priority and assignment
    client.force_login(staff)
    client.post(
        reverse("accounts:begin_report_review", args=[report.pk]),
        {"version": report.version, "room_verified": "on"},
    )
    report.refresh_from_db()
    assert (report.status, report.location_verified_by) == ("UNDER_REVIEW", staff)

    client.post(
        reverse("assignments:assign_report", args=[report.pk]),
        {"unit": unit.pk, "technician": technician.pk, "priority": "HIGH", "version": report.version},
    )
    report.refresh_from_db()
    assignment = Assignment.objects.get(report=report, is_active=True)
    assert (report.status, report.priority) == ("ASSIGNED", "HIGH")
    assert (assignment.unit, assignment.technician) == (unit, technician)

    # --- technician starts, holds, resumes and completes
    client.force_login(technician)
    for url_name, data in (
        ("assignments:start_work", {}),
        ("assignments:put_on_hold", {"reason": "Waiting for a washer", "expected_date": "2030-01-01"}),
        ("assignments:start_work", {}),
    ):
        report.refresh_from_db()
        client.post(reverse(url_name, args=[report.pk]), {"version": report.version, **data})
    report.refresh_from_db()
    assert report.status == "IN_PROGRESS"

    client.post(
        reverse("assignments:complete_work", args=[report.pk]),
        {"version": report.version, "completion_notes": "Replaced the washer."},
    )
    report.refresh_from_db()
    assert report.status == "CLOSED"
    assert Assignment.objects.get(report=report, completed_at__isnull=False).completion_notes == "Replaced the washer."

    # --- resident verifies, then reopens
    client.force_login(resident)
    client.post(
        reverse("reports:verify", args=[report.pk]),
        {"version": report.version, "rating": 4, "comment": "Good"},
    )
    assert Verification.objects.get(report=report).rating == 4
    report.refresh_from_db()
    client.post(
        reverse("reports:reopen", args=[report.pk]),
        {"version": report.version, "reason": "Dripping again"},
    )
    report.refresh_from_db()
    assert report.status == "ASSIGNED"

    # --- the audit trail tells the whole story in order
    assert statuses(report) == [
        "SUBMITTED", "UNDER_REVIEW", "ASSIGNED", "IN_PROGRESS", "ON_HOLD",
        "IN_PROGRESS", "COMPLETED", "CLOSED", "ASSIGNED",  # reopen is one row: CLOSED -> ASSIGNED, with the reason as its note
    ]
    assert StatusHistory.objects.filter(report=report).order_by("pk").last().note == "Dripping again"


@pytest.mark.parametrize(
    "data,field",
    [
        ({"room_location": "A999"}, "room_location"),       # invalid room
        ({"room_verified": ""}, "room_verified"),           # confirmation missing
        ({"title": ""}, "title"),                           # required text missing
        ({"requested_urgency": "EXTREME"}, "requested_urgency"),  # not a choice
    ],
)
def test_invalid_submissions_show_the_error_and_create_nothing(
    client, resident, building, room, category, data, field
):
    client.force_login(resident)
    payload = {
        "category": category.pk,
        "building": building.pk,
        "room_location": room.code,
        "room_verified": "on",
        "title": "Leaking tap",
        "description": "Drips.",
        "requested_urgency": "LOW",
    }
    payload.update(data)

    response = client.post(reverse("reports:create"), payload)

    assert response.status_code == 200
    assert field in response.context["form"].errors
    assert Report.objects.count() == 0


def test_a_subcategory_from_another_category_is_refused(
    client, resident, building, room, category, subcategory
):
    from reports.models import Category, Subcategory

    other = Subcategory.objects.create(category=Category.objects.create(name="Other"), name="Elsewhere")
    client.force_login(resident)

    response = client.post(
        reverse("reports:create"),
        {
            "category": category.pk,
            "subcategory": other.pk,
            "building": building.pk,
            "room_location": room.code,
            "room_verified": "on",
            "title": "t",
            "description": "d",
            "requested_urgency": "LOW",
        },
    )

    assert "subcategory" in response.context["form"].errors
    assert Report.objects.count() == 0


# ---------------------------------------------------------------- role matrix (black-box)
PAGES = {
    "resident": ["accounts:resident_dashboard", "reports:create"],
    "staff": ["accounts:officer_dashboard", "accounts:officer_create_report", "accounts:unit_results"],
    "technician": ["accounts:technician_dashboard", "accounts:unit_results"],
}


@pytest.mark.parametrize("owner", ["resident", "staff", "technician"])
@pytest.mark.parametrize("page_owner", ["resident", "staff", "technician"])
def test_each_page_opens_for_its_role_and_is_hidden_from_the_others(
    client, resident, staff, technician, owner, page_owner
):
    users = {"resident": resident, "staff": staff, "technician": technician}
    client.force_login(users[owner])

    for name in PAGES[page_owner]:
        response = client.get(reverse(name))
        shared = name == "accounts:unit_results" and owner in {"staff", "technician"}
        expected = 200 if (owner == page_owner or shared) else 404
        assert response.status_code == expected, f"{owner} -> {name}"


# ---------------------------------------------------------------- forged requests change nothing
def test_a_resident_cannot_review_assign_or_complete_by_posting_directly(
    client, resident, new_report, unit, technician
):
    report = new_report()
    version = report.version
    client.force_login(resident)

    forged = [
        ("accounts:begin_report_review", {"version": version, "room_verified": "on"}),
        ("accounts:reject_report", {"version": version, "reason": "no"}),
        ("assignments:assign_report", {"unit": unit.pk, "technician": technician.pk, "priority": "HIGH", "version": version}),
        ("assignments:start_work", {"version": version}),
        ("assignments:complete_work", {"version": version, "completion_notes": "done"}),
    ]
    for name, data in forged:
        assert client.post(reverse(name, args=[report.pk]), data).status_code == 404, name

    report.refresh_from_db()
    assert (report.status, report.version) == ("SUBMITTED", version)
    assert statuses(report) == ["SUBMITTED"]


def test_a_technician_cannot_work_on_someone_elses_job(client, assigned_report, other_technician):
    client.force_login(other_technician)

    response = client.post(
        reverse("assignments:start_work", args=[assigned_report.pk]),
        {"version": assigned_report.version},
    )

    assert response.status_code == 404
    assigned_report.refresh_from_db()
    assert assigned_report.status == "ASSIGNED"


# ---------------------------------------------------------------- queue search (black-box)
def test_staff_find_tickets_by_room_ticket_number_and_student_id(
    client, staff, resident, other_resident, new_report, report_data, room
):
    from accounts.models import RoomLocation

    RoomLocation.objects.get_or_create(
        code="A205", defaults={"name": "Dormitory A", "location_type": "DORMITORY"}
    )
    a = new_report(title="Ticket in A101")
    b = new_report(title="Ticket in A205", room_location="A205")
    c = new_report(owner=other_resident, title="Other resident ticket")
    client.force_login(staff)
    url = reverse("accounts:officer_dashboard")

    def titles(query):
        body = client.get(url, query).content.decode()
        return {t for t in ("Ticket in A101", "Ticket in A205", "Other resident ticket") if t in body}

    assert titles({"room": "A2"}) == {"Ticket in A205"}              # partial room match
    assert titles({"room": "a205"}) == {"Ticket in A205"}            # case-insensitive
    assert titles({"ticket_no": a.ticket_no}) == {"Ticket in A101"}  # exact ticket number
    assert titles({"ticket_no": a.ticket_no[:-1]}) == set()          # a prefix is not a match
    assert titles({"student_id": other_resident.username}) == {"Other resident ticket"}
    assert titles({}) == {"Ticket in A101", "Ticket in A205", "Other resident ticket"}


# ---------------------------------------------------------------- comments and photos
def test_a_comment_posted_on_the_page_is_saved_and_a_closed_ticket_refuses_it(
    client, resident, in_progress_report, flow
):
    client.force_login(resident)
    url = reverse("reports:comments", args=[in_progress_report.pk])

    client.post(url, {"body": "Any update?"})
    assert Comment.objects.filter(report=in_progress_report, body="Any update?").count() == 1

    flow.complete(in_progress_report)
    response = client.post(url, {"body": "Still dripping"}, follow=True)

    assert Comment.objects.filter(report=in_progress_report).count() == 1
    assert "closed" in response.content.decode().lower()


def test_an_uploaded_photo_is_stored_and_only_visible_to_the_right_people(
    client, resident, other_resident, staff, building, room, category
):
    client.force_login(resident)
    client.post(
        reverse("reports:create"),
        {
            "category": category.pk,
            "building": building.pk,
            "room_location": room.code,
            "room_verified": "on",
            "title": "With photo",
            "description": "d",
            "requested_urgency": "LOW",
            "photo": jpeg_upload(),
        },
    )
    report = Report.objects.get()
    photo = Photo.objects.get(report=report)
    url = reverse("reports:photo_download", args=[report.pk, photo.pk])
    assert photo.stage == "REPORT"

    results = {}
    for name, user in (("owner", resident), ("staff", staff), ("stranger", other_resident)):
        client.force_login(user)
        response = client.get(url)
        results[name] = response.status_code
        release(response)

    assert results == {"owner": 200, "staff": 200, "stranger": 404}
    from reports.storage import private_photo_storage

    private_photo_storage.delete(photo.file_path)
