"""Performance tests (lecture 6.1 'beyond functional correctness': does it stay responsive under load?).

Wall-clock timing is unreliable on a shared machine, so these tests measure something stable:
the number of database queries. A page whose query count grows with the number of tickets
(the 'N+1' problem) becomes slow as the system fills up.
"""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework.test import APIClient

pytestmark = [pytest.mark.performance, pytest.mark.greybox, pytest.mark.django_db]


def count_queries(fetch):
    with CaptureQueriesContext(connection) as queries:
        response = fetch()
    assert response.status_code == 200
    return len(queries)


def fill(new_report, flow, how_many):
    for index in range(how_many):
        report = new_report(title=f"Ticket {index}")
        if index % 2:
            flow.assign(report)


def api_client(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def test_the_staff_queue_does_not_run_more_queries_for_more_tickets(client, staff, new_report, flow):
    client.force_login(staff)
    fill(new_report, flow, 2)
    few = count_queries(lambda: client.get(reverse("accounts:officer_dashboard")))

    fill(new_report, flow, 14)
    many = count_queries(lambda: client.get(reverse("accounts:officer_dashboard")))

    assert many == few


def test_the_resident_list_does_not_run_more_queries_for_more_tickets(client, resident, new_report, flow):
    client.force_login(resident)
    fill(new_report, flow, 2)
    few = count_queries(lambda: client.get(reverse("reports:list")))

    fill(new_report, flow, 14)
    many = count_queries(lambda: client.get(reverse("reports:list")))

    assert many <= few + 2  # a small allowance; the point is that it does not grow per ticket


@pytest.mark.parametrize("role", ["resident", "staff"])
def test_the_api_list_does_not_run_more_queries_for_more_tickets(role, resident, staff, new_report, flow):
    client = api_client(resident if role == "resident" else staff)
    fill(new_report, flow, 2)
    few = count_queries(lambda: client.get("/api/reports/"))

    fill(new_report, flow, 14)
    many = count_queries(lambda: client.get("/api/reports/"))

    assert many == few


def test_the_staff_queue_is_paginated_at_25_tickets(client, staff, new_report):
    for index in range(30):
        new_report(title=f"Ticket {index}")
    client.force_login(staff)

    first = client.get(reverse("accounts:officer_dashboard"))
    second = client.get(reverse("accounts:officer_dashboard"), {"page": 2})

    assert len(first.context["reports"]) == 25
    assert len(second.context["reports"]) == 5


def test_the_api_list_is_paginated_at_20_tickets(staff, new_report):
    for index in range(25):
        new_report(title=f"Ticket {index}")

    data = api_client(staff).get("/api/reports/").json()

    assert (data["count"], len(data["results"])) == (25, 20)
    assert data["next"] is not None


def test_a_busy_system_still_answers_within_a_generous_time_budget(client, staff, new_report, flow):
    import time

    fill(new_report, flow, 40)
    client.force_login(staff)

    started = time.perf_counter()
    response = client.get(reverse("accounts:officer_dashboard"))
    elapsed = time.perf_counter() - started

    assert response.status_code == 200
    assert elapsed < 3.0  # a smoke check against gross regressions, not a benchmark
