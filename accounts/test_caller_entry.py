from django.test import TestCase
from django.urls import reverse

from accounts.models import Building, RoomLocation, Unit, UnitKind, User
from reports.models import Category, Report


class CallerEntryScreenTests(TestCase):
    """Call Center Staff enter a request on behalf of a caller."""

    def setUp(self):
        self.building = Building.objects.create(name="Dormitory A", zone="Zone 1")
        self.category = Category.objects.create(name="Caller Plumbing")
        RoomLocation.objects.get_or_create(
            code="A101",
            defaults={
                "name": "Dormitory A",
                "location_type": RoomLocation.LocationType.DORMITORY,
            },
        )
        self.unit = Unit.objects.create(name="Caller Unit", kind=UnitKind.INTERNAL)
        self.other_unit = Unit.objects.create(name="Other Unit", kind=UnitKind.CONTRACTOR)
        self.resident = User.objects.create_user(
            username="st300001",
            email="caller.resident@example.test",
            password="test-password",
            role=User.Role.RESIDENT,
            name="Caller Resident",
        )
        self.staff = User.objects.create_user(
            username="caller_staff",
            email="caller.staff@example.test",
            password="test-password",
            role=User.Role.CALL_CENTER_STAFF,
        )
        self.technician = User.objects.create_user(
            username="caller_tech",
            email="caller.tech@example.test",
            password="test-password",
            role=User.Role.TECHNICIAN_CONTRACTOR,
            unit=self.unit,
        )
        self.url = reverse("accounts:officer_create_report")

    def payload(self, **overrides):
        values = {
            "resident": self.resident.pk,
            "channel": "PHONE",
            "category": self.category.pk,
            "building": self.building.pk,
            "room_location": "A101",
            "room_verified": "on",
            "title": "Gas smell in the kitchen",
            "description": "Caller reports a strong gas smell.",
            "requested_urgency": "HIGH",
        }
        values.update(overrides)
        return values

    def test_staff_see_the_form_and_a_nav_link(self):
        self.client.force_login(self.staff)

        response = self.client.get(self.url)

        self.assertContains(response, "Enter a request for a caller")
        self.assertContains(response, "Caller (resident account)")
        self.assertContains(response, "Caller Resident (st300001)")
        self.assertContains(response, "New ticket")

    def test_residents_and_technicians_cannot_open_the_form(self):
        for user in (self.resident, self.technician):
            with self.subTest(role=user.role):
                self.client.force_login(user)
                self.assertEqual(self.client.get(self.url).status_code, 404)
                self.assertEqual(self.client.post(self.url, self.payload()).status_code, 404)
        self.assertEqual(Report.objects.count(), 0)

    def test_phone_request_is_created_for_the_resident_and_stays_submitted(self):
        self.client.force_login(self.staff)

        response = self.client.post(self.url, self.payload())

        report = Report.objects.get()
        self.assertRedirects(
            response, reverse("accounts:officer_report_detail", args=[report.pk])
        )
        self.assertEqual(report.resident, self.resident)
        self.assertEqual(report.submitted_by, self.staff)
        self.assertEqual(report.channel, "PHONE")
        self.assertEqual(report.status, "SUBMITTED")
        self.assertEqual(report.location_verified_by, self.staff)
        self.assertIsNotNone(report.location_verified_at)

    def test_serious_fault_is_created_and_assigned_in_one_step(self):
        self.client.force_login(self.staff)

        response = self.client.post(
            self.url,
            self.payload(unit=self.unit.pk, technician=self.technician.pk, priority="URGENT"),
        )

        report = Report.objects.get()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(report.status, "ASSIGNED")
        self.assertEqual(report.priority, "URGENT")
        assignment = report.assignments.get(is_active=True)
        self.assertEqual(assignment.unit, self.unit)
        self.assertEqual(assignment.technician, self.technician)

    def test_a_unit_without_a_technician_can_be_assigned(self):
        self.client.force_login(self.staff)

        self.client.post(self.url, self.payload(unit=self.unit.pk, priority="HIGH"))

        report = Report.objects.get()
        self.assertEqual(report.status, "ASSIGNED")
        self.assertIsNone(report.assignments.get(is_active=True).technician)

    def test_the_technician_alone_fills_in_the_unit(self):
        self.client.force_login(self.staff)

        self.client.post(self.url, self.payload(technician=self.technician.pk, priority="HIGH"))

        self.assertEqual(Report.objects.get().assignments.get().unit, self.unit)

    def test_room_must_be_verified_with_the_caller(self):
        self.client.force_login(self.staff)
        data = self.payload()
        del data["room_verified"]

        response = self.client.post(self.url, data)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "This field is required")
        self.assertEqual(Report.objects.count(), 0)

    def test_assigning_now_requires_a_priority(self):
        self.client.force_login(self.staff)

        response = self.client.post(self.url, self.payload(unit=self.unit.pk))

        self.assertContains(response, "Choose a priority when assigning now.")
        self.assertEqual(Report.objects.count(), 0)

    def test_technician_must_belong_to_the_chosen_unit(self):
        self.client.force_login(self.staff)

        response = self.client.post(
            self.url,
            self.payload(unit=self.other_unit.pk, technician=self.technician.pk, priority="HIGH"),
        )

        self.assertContains(response, "must belong to the selected unit")
        self.assertEqual(Report.objects.count(), 0)

    def test_an_invalid_room_is_refused(self):
        self.client.force_login(self.staff)

        response = self.client.post(self.url, self.payload(room_location="A999"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Report.objects.count(), 0)

    def test_only_resident_accounts_can_be_chosen_as_the_caller(self):
        self.client.force_login(self.staff)

        response = self.client.post(self.url, self.payload(resident=self.technician.pk))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Report.objects.count(), 0)

    def test_dashboard_links_to_the_form_and_shows_the_unit_when_no_technician(self):
        self.client.force_login(self.staff)
        self.client.post(self.url, self.payload(unit=self.unit.pk, priority="HIGH"))

        response = self.client.get(reverse("accounts:officer_dashboard"))

        self.assertContains(response, reverse("accounts:officer_create_report"))
        self.assertContains(response, "Assigned to: Caller Unit")
