import os

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import Unit, User

ROLE = User.Role
ACCOUNTS = (
    ("staff.sarah", "Sarah Thompson", ROLE.CALL_CENTER_STAFF, None),
    ("resident.ali", "Ali Hassan", ROLE.RESIDENT, None),
    ("resident.mai", "Mai Nguyen", ROLE.RESIDENT, None),
    ("tech.plumbing", "Somchai Prasert", ROLE.TECHNICIAN_CONTRACTOR, "Plumbing and Water"),
    ("tech.electrical", "Kittipong Wong", ROLE.TECHNICIAN_CONTRACTOR, "Electrical Services"),
    ("tech.hvac", "Narin Chaiyo", ROLE.TECHNICIAN_CONTRACTOR, "Air Conditioning (HVAC)"),
    ("tech.carpentry", "Prasit Meesuk", ROLE.TECHNICIAN_CONTRACTOR, "Carpentry and Furniture"),
    ("tech.painting", "Anan Boonmee", ROLE.TECHNICIAN_CONTRACTOR, "Painting and Finishing"),
    ("tech.housekeeping", "Malee Saetang", ROLE.TECHNICIAN_CONTRACTOR, "Housekeeping"),
    ("tech.pest", "Wichai Srisuk", ROLE.TECHNICIAN_CONTRACTOR, "Pest Control"),
    ("tech.gardening", "Boonlert Kaew", ROLE.TECHNICIAN_CONTRACTOR, "Gardening"),
    ("tech.accommodation", "Pimchanok Daeng", ROLE.TECHNICIAN_CONTRACTOR, "Accommodation"),
)


class Command(BaseCommand):
    help = (
        "Create the accounts used in the presentation: one Call Center Staff, two residents and one "
        "technician in each maintenance unit. The password comes from PRESENTATION_USER_PASSWORD. "
        "Safe to run again; it never creates duplicates."
    )

    @transaction.atomic
    def handle(self, *args, **options):
        password = os.environ.get("PRESENTATION_USER_PASSWORD", "")
        if not password:
            raise CommandError("Set PRESENTATION_USER_PASSWORD before running this command.")
        units = {unit.name: unit for unit in Unit.objects.all()}
        missing = sorted({name for *_, name in ACCOUNTS if name and name not in units})
        if missing:
            raise CommandError(
                "These units do not exist yet: "
                + ", ".join(missing)
                + ". Run seed_reference_data and seed_campus_reference_data first."
            )
        for username, name, role, unit_name in ACCOUNTS:
            unit = units[unit_name] if unit_name else None
            user, _ = User.objects.get_or_create(
                username=username,
                defaults={"email": f"{username}@example.test", "role": role, "name": name, "unit": unit},
            )
            user.name, user.role, user.unit, user.is_active = name, role, unit, True
            user.set_password(password)
            user.save()
        self.stdout.write(self.style.SUCCESS(f"{len(ACCOUNTS)} presentation accounts are ready."))
