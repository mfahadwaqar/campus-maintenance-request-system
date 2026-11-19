import getpass
import os
import sys

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import Building, Unit, UnitKind, User
from reports.models import Category, Report
from reports.services import (
    assign_technician,
    complete_work,
    start_review,
    start_work,
    submit_report,
)


class Command(BaseCommand):
    help = "Create clearly labelled synthetic accounts and campus reference data."

    @transaction.atomic
    def handle(self, *args, **options):
        password = os.environ.get("DEMO_USER_PASSWORD")
        if not password:
            if not sys.stdin.isatty():
                raise CommandError(
                    "Set DEMO_USER_PASSWORD to create demo accounts non-interactively."
                )
            password = getpass.getpass("Password for all demo accounts: ")
        if not password:
            raise CommandError("The demo account password cannot be empty.")

        buildings = [
            Building.objects.get_or_create(name="Demo Building A", defaults={"zone": "Demo North"})[0],
            Building.objects.get_or_create(name="Demo Building B", defaults={"zone": "Demo South"})[0],
        ]
        units = [
            Unit.objects.get_or_create(name="Demo Technical Services", defaults={"kind": UnitKind.INTERNAL})[0],
            Unit.objects.get_or_create(name="Demo Pest Control", defaults={"kind": UnitKind.CONTRACTOR})[0],
            Unit.objects.get_or_create(name="Demo Accommodation", defaults={"kind": UnitKind.INTERNAL})[0],
        ]
        category_names = ("Demo Plumbing", "Demo Electrical", "Demo General Maintenance")
        categories = [
            Category.objects.get_or_create(name=name, defaults={"default_unit": units[index]})[0]
            for index, name in enumerate(category_names)
        ]

        users = []
        user_specs = [
            (f"demo_resident_{number:02d}", User.Role.RESIDENT, buildings[number % 2])
            for number in range(1, 5)
        ]
        user_specs.extend(
            (f"demo_officer_{number:02d}", User.Role.CALL_CENTER_STAFF, None)
            for number in range(1, 3)
        )
        user_specs.extend(
            (f"demo_technician_{number:02d}", User.Role.TECHNICIAN_CONTRACTOR, None)
            for number in range(1, 5)
        )
        for index, (username, role, building) in enumerate(user_specs):
            unit = units[index % len(units)] if role == User.Role.TECHNICIAN_CONTRACTOR else None
            user, created = User.objects.get_or_create(
                username=username,
                defaults={
                    "first_name": f"Demo {role.title()}",
                    "last_name": username.rsplit("_", 1)[-1],
                    "email": f"{username}@example.test",
                    "role": role,
                    "building": building,
                    "unit": unit,
                },
            )
            if created:
                user.set_password(password)
                user.save(update_fields=("password",))
            users.append(user)


        sample_reports = [
            ("Air conditioner is not cooling", "The room AC unit is not cooling.", "HIGH"),
            ("Water leaking under the sink", "There is water leaking from the sink pipe.", "MEDIUM"),
            ("Corridor lights are flickering", "Several corridor lights flicker intermittently.", "HIGH"),
            ("Blocked restroom drain", "The restroom floor drain is blocked.", "URGENT"),
            ("Hallway wall needs repainting", "The hallway wall paint is peeling.", "LOW"),
            ("Pest sighted in storeroom", "Small insects were sighted in the storeroom.", "MEDIUM"),
        ]
        sample_category = Category.objects.filter(name="Technical").first() or categories[-1]
        sample_buildings = list(Building.objects.exclude(name__startswith="Demo").order_by("name")[:2])
        residents = [user for user in users if user.role == User.Role.RESIDENT]
        officers = [user for user in users if user.role == User.Role.CALL_CENTER_STAFF]
        technicians = [user for user in users if user.role == User.Role.TECHNICIAN_CONTRACTOR]
        for index, (title, description, priority) in enumerate(sample_reports, start=1):
            if Report.objects.filter(title=title).exists():
                continue
            report = submit_report(
                resident=residents[index % len(residents)],
                category=sample_category,
                building=(sample_buildings[index % len(sample_buildings)] if sample_buildings else buildings[index % 2]),
                room_location=f"Sample room {100 + index}",
                title=title,
                description=description,
                requested_urgency=priority,
            )
            if index >= 2:
                report = start_review(
                    report_id=report.pk,
                    actor=officers[0],
                    expected_version=report.version,
                    room_verified=True,
                )
            if index >= 4:
                technician = technicians[index % len(technicians)]
                report = assign_technician(
                    report_id=report.pk,
                    technician=technician,
                    unit=technician.unit,
                    assigned_by=officers[0],
                    priority=priority,
                    expected_version=report.version,
                )
            if index >= 5:
                report = start_work(
                    report_id=report.pk,
                    technician=technicians[index % len(technicians)],
                    expected_version=report.version,
                )
            if index == 6:
                complete_work(
                    report_id=report.pk,
                    technician=technicians[index % len(technicians)],
                    expected_version=report.version,
                    completion_notes="Sample maintenance completed and tested.",
                )

        self.stdout.write(
            self.style.SUCCESS(
                "Created or verified 4 demo residents, 2 demo officers, "
                "4 demo technicians, 2 demo buildings, 3 demo categories, and sample reports."
            )
        )
