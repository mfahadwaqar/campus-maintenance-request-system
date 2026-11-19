"""Step definitions for features/request_lifecycle.feature (pytest-bdd).

The feature file says WHAT the system should do in business language; these functions say HOW
each step is checked. Steps drive the real pages with the Django test client and then verify
database effects, because a redirect alone is not proof that the rule worked (lecture 6.2).
"""

from datetime import date, timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from pytest_bdd import given, parsers, scenarios, then, when

from accounts.models import RoomLocation
from assignments.models import Assignment
from notifications.models import Notification
from reports.models import Comment, Report, StatusHistory

pytestmark = [pytest.mark.bdd, pytest.mark.integration, pytest.mark.django_db]

scenarios("features/request_lifecycle.feature")


@pytest.fixture
def ctx():
    """Values handed from one step to the next."""
    return {}


# ---------------------------------------------------------------- Given
@given("I am logged in as a resident")
def logged_in_resident(client, resident):
    client.force_login(resident)


@given("I am logged in as call center staff")
def logged_in_staff(client, staff):
    client.force_login(staff)


@given("a ticket that the technician has started", target_fixture="report")
def started_ticket(in_progress_report):
    return in_progress_report


@given(parsers.parse("a closed ticket that was completed {days:d} days ago"), target_fixture="report")
def closed_ticket_aged(closed_report, days):
    Assignment.objects.filter(report=closed_report, completed_at__isnull=False).update(
        completed_at=timezone.now() - timedelta(days=days)
    )
    return closed_report


@given("a ticket that belongs to another resident", target_fixture="report")
def others_ticket(new_report, other_resident):
    return new_report(owner=other_resident)


@given("two tickets exist in different rooms from different residents")
def two_tickets(new_report, other_resident):
    RoomLocation.objects.get_or_create(
        code="A205", defaults={"name": "Dormitory A", "location_type": "DORMITORY"}
    )
    new_report(title="In room A101")
    new_report(owner=other_resident, title="In room A205", room_location="A205")


# ---------------------------------------------------------------- When
@when(parsers.parse('I submit a request for room "{code}"'), target_fixture="response")
def submit_request(client, building, category, code):
    return client.post(
        reverse("reports:create"),
        {
            "category": category.pk,
            "building": building.pk,
            "room_location": code,
            "room_verified": "on",
            "title": "Leaking tap",
            "description": "Drips constantly.",
            "requested_urgency": "MEDIUM",
        },
    )


@when(parsers.parse('the technician completes the job with notes "{notes}"'))
def technician_completes(flow, report, notes):
    flow.complete(report, notes=notes)


@when(parsers.parse('the technician puts the job on hold because "{reason}"'))
def technician_holds(flow, report, reason):
    flow.hold(report, reason=reason)


@when(parsers.parse('the resident reopens it because "{reason}"'))
def resident_reopens(client, resident, report, reason):
    client.force_login(resident)
    report.refresh_from_db()
    client.post(reverse("reports:reopen", args=[report.pk]), {"version": report.version, "reason": reason})


@when(parsers.parse('the resident tries to reopen it because "{reason}"'), target_fixture="response")
def resident_tries_to_reopen(client, resident, report, reason):
    client.force_login(resident)
    report.refresh_from_db()
    return client.post(
        reverse("reports:reopen", args=[report.pk]),
        {"version": report.version, "reason": reason},
        follow=True,
    )


@when(parsers.parse('the resident comments "{text}"'))
def resident_comments(client, resident, report, text):
    client.force_login(resident)
    client.post(reverse("reports:comments", args=[report.pk]), {"body": text})


@when("I open that ticket", target_fixture="response")
def open_ticket(client, report):
    return client.get(reverse("reports:detail", args=[report.pk]))


@when(
    parsers.parse(
        'I enter a phone request for the caller and assign it to the unit with priority "{priority}"'
    )
)
def staff_enter_and_assign(client, resident, building, room, category, unit, technician, priority):
    client.post(
        reverse("accounts:officer_create_report"),
        {
            "resident": resident.pk,
            "channel": "PHONE",
            "category": category.pk,
            "building": building.pk,
            "room_location": room.code,
            "room_verified": "on",
            "title": "Gas smell",
            "description": "Strong smell of gas.",
            "requested_urgency": "HIGH",
            "unit": unit.pk,
            "technician": technician.pk,
            "priority": priority,
        },
    )


@when(parsers.parse('I search the queue by {field} "{value}"'), target_fixture="response")
def search_queue(client, field, value):
    key = {"room": "room", "student ID": "student_id", "ticket number": "ticket_no"}[field]
    return client.get(reverse("accounts:officer_dashboard"), {key: value})


# ---------------------------------------------------------------- Then
@then(parsers.parse('one ticket exists with status "{status}"'))
def one_ticket_with_status(status):
    assert Report.objects.get().status == status


@then(parsers.parse('the ticket status is "{status}"'))
def ticket_status_is(report, status):
    report.refresh_from_db()
    assert report.status == status


@then("the ticket belongs to me")
def ticket_belongs_to_me(resident):
    assert Report.objects.get().resident == resident


@then("no ticket exists")
def no_ticket():
    assert Report.objects.count() == 0


@then(parsers.parse('I am shown the error "{text}"'))
def error_shown(response, text):
    assert response.status_code == 200
    assert text in str(response.context["form"].errors)


@then(parsers.parse('the history ends with "{first}" then "{second}"'))
def history_ends_with(report, first, second):
    rows = list(
        StatusHistory.objects.filter(report=report).order_by("-pk").values_list("new_status", flat=True)[:2]
    )
    assert rows == [second, first]


@then("the reopen reason is recorded in the history")
def reopen_reason_recorded(report):
    assert StatusHistory.objects.filter(report=report).order_by("pk").last().note == "It is dripping again"


@then("I am told the reopening window has expired")
def told_window_expired(response):
    assert "three-day reopening window has expired" in response.content.decode()


@then("no comment was saved")
def no_comment(report):
    assert Comment.objects.filter(report=report).count() == 0


@then("one comment was saved")
def one_comment(report):
    assert Comment.objects.filter(report=report).count() == 1


@then("the resident is notified that the work is on hold")
def resident_told_of_hold(report, resident):
    message = Notification.objects.get(report=report, user=resident, message__contains="on hold").message
    assert "Waiting for a replacement valve" in message
    assert (date.today() + timedelta(days=2)).isoformat() in message


@then("the page is not found")
def page_not_found(response):
    assert response.status_code == 404


@then(parsers.parse('its priority is "{priority}"'))
def priority_is(priority):
    assert Report.objects.get().priority == priority


@then(parsers.parse('the queue lists only the ticket titled "{title}"'))
def queue_lists_only(response, title):
    body = response.content.decode()
    shown = {t for t in ("In room A101", "In room A205") if t in body}
    assert shown == {title}
