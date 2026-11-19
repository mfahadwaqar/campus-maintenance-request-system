from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import Building, Unit, UnitKind
from reports.models import Category, Subcategory

DORMS_BY_ZONE = {
    "Zone 1": ("A", "B", "C", "D", "F", "G", "H"),
    "Zone 2": ("E", "J", "K"),
    "Zone 3": ("L", "M", "N", "P3", "Q", "R", "S"),
    "Zone 4": ("T", "U", "V", "W", "X", "Y"),
}
VILLAGE_RANGES = (
    ("Student Village I", range(1, 26)),
    ("Student Village II", range(26, 51)),
    ("Student Village III", range(51, 71)),
)
UNIT_DEFAULTS = {
    "Electrical Services": (
        UnitKind.CONTRACTOR,
        (("Technical", "Electrical Services"), ("Technical", "Lighting"), ("Technical", "Television")),
    ),
    "Plumbing and Water": (
        UnitKind.CONTRACTOR,
        (("Technical", "Water Leakage"), ("Technical", "Sanitation"), ("Janitorial", "Sanitation")),
    ),
    "Air Conditioning (HVAC)": (
        UnitKind.CONTRACTOR,
        (("Technical", "Heating Ventilation & Air Conditioning"), ("Technical", "Air Condition")),
    ),
    "Carpentry and Furniture": (
        UnitKind.CONTRACTOR,
        (("Technical", "Furniture"), ("Technical", "Building Service")),
    ),
    "Painting and Finishing": (UnitKind.CONTRACTOR, (("Technical", "Painting"),)),
    "Pest Control": (
        UnitKind.CONTRACTOR,
        tuple(("Pest Control", name) for name in ("Special Pest Control", "Bug Control", "Termite Control", "Others Pest")),
    ),
    "Housekeeping": (
        UnitKind.CONTRACTOR,
        (("Janitorial", "Building cleaning"), ("Janitorial", "Trash removal")),
    ),
    "Gardening": (
        UnitKind.CONTRACTOR,
        (("Landscape", "Ground Maintenance"), ("Landscape", "Other Gardening"), ("Landscape", "Trash removal")),
    ),
    "Accommodation": (
        UnitKind.INTERNAL,
        (("Accommodation", "Key request"), ("Accommodation", "Other accommodation")),
    ),
}


class Command(BaseCommand):
    help = "Add campus buildings and unit defaults without overwriting existing category or unit data."

    @transaction.atomic
    def handle(self, *args, **options):
        created_buildings = 0
        for zone, dorms in DORMS_BY_ZONE.items():
            for dorm in dorms:
                building, created = Building.objects.get_or_create(
                    name=f"Dormitory {dorm}",
                    defaults={"zone": zone, "is_active": True},
                )
                if not created:
                    Building.objects.filter(pk=building.pk).update(zone=zone, is_active=True)
                created_buildings += created
        for zone, villages in VILLAGE_RANGES:
            for number in villages:
                code = f"SV{number}"
                building, created = Building.objects.get_or_create(
                    name=code,
                    defaults={"zone": zone, "is_active": True},
                )
                if not created:
                    Building.objects.filter(pk=building.pk).update(zone=zone, is_active=True)
                created_buildings += created

        subcategories = {}
        for unit_name, (_, mappings) in UNIT_DEFAULTS.items():
            for category_name, subcategory_name in mappings:
                category = Category.objects.filter(name=category_name).first()
                if category is None:
                    raise CommandError(
                        f"Category {category_name!r} is missing; run seed_reference_data first."
                    )
                subcategory = Subcategory.objects.filter(
                    category=category, name=subcategory_name
                ).first()
                if subcategory is None:
                    raise CommandError(
                        f"Subcategory {category_name}/{subcategory_name} is missing; "
                        "run seed_reference_data first."
                    )
                subcategories[(category_name, subcategory_name)] = subcategory

        for unit_name, (kind, mappings) in UNIT_DEFAULTS.items():
            unit, _ = Unit.objects.get_or_create(
                name=unit_name,
                defaults={"kind": kind, "is_active": True},
            )
            for key in mappings:
                subcategory = subcategories[key]
                if subcategory.default_unit_id != unit.pk:
                    Subcategory.objects.filter(pk=subcategory.pk).update(default_unit=unit)

        self.stdout.write(
            self.style.SUCCESS(
                f"Added/activated {created_buildings} dorm and village buildings and applied "
                f"{sum(len(mappings) for _, mappings in UNIT_DEFAULTS.values())} unit defaults."
            )
        )
