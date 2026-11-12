from django.db import migrations


DORMITORIES = {
    "Category 1": (4, ["A", "B", "C", "D", "F", "G", "H"]),
    "Category 2": (3, ["E", "J", "K"]),
    "Category 3": (4, ["L", "M", "N", "P3", "Q", "R", "S"]),
    "Category 4": (4, ["T", "U", "V", "W", "X", "Y"]),
}


def seed_locations(apps, schema_editor):
    RoomLocation = apps.get_model("accounts", "RoomLocation")
    for _, (floors, dorms) in DORMITORIES.items():
        for dorm in dorms:
            for floor in range(1, floors + 1):
                for room in range(1, 11):
                    code = f"{dorm}{floor}{room:02d}"
                    RoomLocation.objects.get_or_create(
                        code=code,
                        defaults={
                            "name": f"Dormitory {dorm}",
                            "location_type": "DORMITORY",
                            "is_active": True,
                        },
                    )
    for village in range(1, 4):
        start, end = ((1, 26), (26, 51), (51, 71))[village - 1]
        for number in range(start, end):
            code = f"SV{number}"
            RoomLocation.objects.get_or_create(
                code=code,
                defaults={
                    "name": f"Student Village {village}",
                    "location_type": "STUDENT_VILLAGE",
                    "is_active": True,
                },
            )


def remove_locations(apps, schema_editor):
    RoomLocation = apps.get_model("accounts", "RoomLocation")
    RoomLocation.objects.filter(location_type__in=("DORMITORY", "STUDENT_VILLAGE")).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0002_roomlocation"),
    ]

    operations = [
        migrations.RunPython(seed_locations, remove_locations),
    ]
