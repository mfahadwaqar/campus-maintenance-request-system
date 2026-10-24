import getpass
import os
import sys

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import Building, User
from assignments.models import TechnicianSpecialization
from reports.models import Category


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
            Building.objects.get_or_create(name="Demo Building A", zone="Demo North")[0],
            Building.objects.get_or_create(name="Demo Building B", zone="Demo South")[0],
        ]
        categories = [
            Category.objects.get_or_create(name=name)[0]
            for name in ("Demo Plumbing", "Demo Electrical", "Demo General Maintenance")
        ]

        users = []
        user_specs = [
            (f"demo_resident_{number:02d}", User.Role.RESIDENT, buildings[number % 2])
            for number in range(1, 5)
        ]
        user_specs.extend(
            (f"demo_officer_{number:02d}", User.Role.OFFICER, None)
            for number in range(1, 3)
        )
        user_specs.extend(
            (f"demo_technician_{number:02d}", User.Role.TECHNICIAN, None)
            for number in range(1, 5)
        )
        for username, role, building in user_specs:
            user, created = User.objects.get_or_create(
                username=username,
                defaults={
                    "first_name": f"Demo {role.title()}",
                    "last_name": username.rsplit("_", 1)[-1],
                    "email": f"{username}@example.test",
                    "role": role,
                    "building": building,
                },
            )
            if created:
                user.set_password(password)
                user.save(update_fields=("password",))
            users.append(user)

        technicians = [user for user in users if user.role == User.Role.TECHNICIAN]
        for index, technician in enumerate(technicians):
            technician_categories = (
                categories[index % len(categories)],
                categories[(index + 1) % len(categories)],
            )
            for category in technician_categories:
                TechnicianSpecialization.objects.get_or_create(
                    technician=technician, category=category
                )

        self.stdout.write(
            self.style.SUCCESS(
                "Created or verified 4 demo residents, 2 demo officers, "
                "4 demo technicians, 2 demo buildings, and 3 demo categories."
            )
        )
