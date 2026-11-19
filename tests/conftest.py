"""Shared fixtures for the pytest suites (unit, integration, security, BDD, browser).

Fixtures follow the lecture pattern: reusable test data defined once in conftest.py
and injected by name. Every test starts from an empty, isolated database.
"""

from datetime import date, timedelta
from io import BytesIO

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from accounts.models import Building, RoomLocation, Unit, UnitKind, User
from reports.models import Category, Report, Subcategory
from reports.services import (
    add_comment,
    assign_technician,
    put_on_hold,
    reopen_report,
    start_review,
    start_work,
    submit_report,
)

PASSWORD = "Test-pass-12345!"


def make_user(username, role, **extra):
    return User.objects.create_user(
        username=username,
        email=f"{username}@example.test",
        password=PASSWORD,
        role=role,
        **extra,
    )


@pytest.fixture
def building(db):
    return Building.objects.create(name="Dormitory A", zone="Zone 1")


@pytest.fixture
def room(db):
    location, _ = RoomLocation.objects.get_or_create(
        code="A101",
        defaults={
            "name": "Dormitory A",
            "location_type": RoomLocation.LocationType.DORMITORY,
        },
    )
    return location


@pytest.fixture
def category(db):
    return Category.objects.create(name="Plumbing (test)")


@pytest.fixture
def subcategory(category):
    return Subcategory.objects.create(category=category, name="Water leak (test)")


@pytest.fixture
def unit(db):
    return Unit.objects.create(name="Test Unit", kind=UnitKind.INTERNAL)


@pytest.fixture
def other_unit(db):
    return Unit.objects.create(name="Other Unit", kind=UnitKind.CONTRACTOR)


@pytest.fixture
def resident(db):
    return make_user("st900001", User.Role.RESIDENT, name="Test Resident")


@pytest.fixture
def other_resident(db):
    return make_user("st900002", User.Role.RESIDENT, name="Other Resident")


@pytest.fixture
def staff(db):
    return make_user("staff_one", User.Role.CALL_CENTER_STAFF)


@pytest.fixture
def technician(unit):
    return make_user("tech_one", User.Role.TECHNICIAN_CONTRACTOR, unit=unit)


@pytest.fixture
def other_technician(unit):
    return make_user("tech_two", User.Role.TECHNICIAN_CONTRACTOR, unit=unit)


@pytest.fixture
def admin_user(db):
    return User.objects.create_user(
        username="admin_one",
        email="admin_one@example.test",
        password=PASSWORD,
        is_staff=True,
        is_superuser=True,
    )


@pytest.fixture
def report_data(building, room, category):
    """Valid input for submit_report(); override single fields in a test."""

    def build(**overrides):
        values = {
            "category": category,
            "building": building,
            "room_location": room.code,
            "room_verified": True,
            "title": "Leaking tap",
            "description": "The tap drips constantly.",
            "requested_urgency": "MEDIUM",
        }
        values.update(overrides)
        return values

    return build


@pytest.fixture
def new_report(resident, report_data):
    """Create a Submitted report for the resident (or another resident)."""

    def create(owner=None, **overrides):
        return submit_report(resident=owner or resident, **report_data(**overrides))

    return create


class Flow:
    """Drives a report through its life using the real service functions."""

    def __init__(self, staff, technician, unit):
        self.staff = staff
        self.technician = technician
        self.unit = unit

    @staticmethod
    def _fresh(report):
        report.refresh_from_db()
        return report

    def review(self, report):
        start_review(
            report_id=report.pk,
            actor=self.staff,
            expected_version=report.version,
            room_verified=True,
        )
        return self._fresh(report)

    def assign(self, report, technician=None, unit=None, priority="HIGH"):
        if report.status == Report.Status.SUBMITTED:
            self.review(report)
        assign_technician(
            report_id=report.pk,
            technician=technician or self.technician,
            assigned_by=self.staff,
            unit=unit or self.unit,
            priority=priority,
            expected_version=report.version,
        )
        return self._fresh(report)

    def start(self, report):
        start_work(
            report_id=report.pk,
            technician=self.technician,
            expected_version=report.version,
        )
        return self._fresh(report)

    def hold(self, report, reason="Waiting for parts", days=2):
        put_on_hold(
            report_id=report.pk,
            technician=self.technician,
            expected_version=report.version,
            reason=reason,
            expected_date=date.today() + timedelta(days=days),
        )
        return self._fresh(report)

    def complete(self, report, notes="Fixed the leak.", signed=True):
        from reports.services import complete_work as _complete

        _complete(
            report_id=report.pk,
            technician=self.technician,
            expected_version=report.version,
            completion_notes=notes,
            requester_signed_on_site=signed,
        )
        return self._fresh(report)

    def reopen(self, report, actor, reason="It is leaking again."):
        reopen_report(
            report_id=report.pk,
            actor=actor,
            expected_version=report.version,
            reason=reason,
        )
        return self._fresh(report)

    def comment(self, report, author, body="Any update?"):
        return add_comment(report_id=report.pk, author=author, body=body)


@pytest.fixture
def flow(staff, technician, unit):
    return Flow(staff, technician, unit)


@pytest.fixture
def assigned_report(new_report, flow):
    return flow.assign(new_report())


@pytest.fixture
def in_progress_report(assigned_report, flow):
    return flow.start(assigned_report)


@pytest.fixture
def closed_report(in_progress_report, flow):
    return flow.complete(in_progress_report)


@pytest.fixture
def client_as(client):
    """Return a function that logs the shared test client in as a user."""

    def login(user):
        client.force_login(user)
        return client

    return login


def jpeg_upload(name="photo.jpg", size=(8, 8)):
    output = BytesIO()
    Image.new("RGB", size, color="blue").save(output, format="JPEG")
    return SimpleUploadedFile(name, output.getvalue(), content_type="image/jpeg")


@pytest.fixture
def photo():
    return jpeg_upload()
