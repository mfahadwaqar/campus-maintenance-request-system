from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import RoomLocation


DORMITORIES = {
    "Zone 1": (4, ["A", "B", "C", "D", "F", "G", "H"]),
    "Zone 2": (3, ["E", "J", "K"]),
    "Zone 3": (4, ["L", "M", "N", "P3", "Q", "R", "S"]),
    "Zone 4": (4, ["T", "U", "V", "W", "X", "Y"]),
}

STUDENT_VILLAGES = {
    1: [f"SV{number}" for number in range(1, 26)],
    2: [f"SV{number}" for number in range(26, 51)],
    3: [f"SV{number}" for number in range(51, 71)],
}


class Command(BaseCommand):
    help = "Seed dormitory room and Student Village choices."

    @transaction.atomic
    def handle(self, *args, **options):
        created = 0
        for _, (floors, dorms) in DORMITORIES.items():
            for dorm in dorms:
                for floor in range(1, floors + 1):
                    for room in range(1, 11):
                        code = f"{dorm}{floor}{room:02d}"
                        _, was_created = RoomLocation.objects.get_or_create(
                            code=code,
                            defaults={
                                "name": f"Dormitory {dorm}",
                                "location_type": RoomLocation.LocationType.DORMITORY,
                                "is_active": True,
                            },
                        )
                        created += was_created

        for village, codes in STUDENT_VILLAGES.items():
            for code in codes:
                _, was_created = RoomLocation.objects.get_or_create(
                    code=code,
                    defaults={
                        "name": f"Student Village {village}",
                        "location_type": RoomLocation.LocationType.STUDENT_VILLAGE,
                        "is_active": True,
                    },
                )
                created += was_created

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {RoomLocation.objects.count()} room and Student Village choices "
                f"({created} newly created)."
            )
        )
