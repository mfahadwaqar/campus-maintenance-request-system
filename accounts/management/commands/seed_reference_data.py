from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import Building
from reports.models import Category, Subcategory

LOCATIONS = [
    "AI Center",
    "Admin",
    "AITCC",
    "AITCC Dinning",
    "AIT International School",
    "AIT Solutions",
    "Auxiliary Arcade",
    "AUX Other Rentals",
    "AUX Outreach Building",
    "Cafeteria",
    "COEN",
    "EXTENSION",
    "Entrepreneurship Center",
    "Faculty/Staff Residents",
    "General/Others",
    "GIC",
    "Habitec",
    "Internet Education and Research Laboratory (intERLab)",
    "Language",
    "Laundry",
    "Library",
    "Motorpool & labourpool",
    "OFAM",
    "OUTREACH",
    "SDCC",
    "SERD",
    "SET",
    "SOM",
    "Student Residents",
    "Telecom",
]

CATEGORIES = [
    "General",
    "Technical",
    "Janitorial",
    "Landscape",
    "Pest Control",
    "Security",
    "Accommodation",
    "Internal Mail",
    "Motor Pool",
    "Labor Pool",
]

SUBCATEGORIES = {
    "Technical": [
        "Electrical Services",
        "Equipment",
        "Fire Protection",
        "Furniture",
        "Heating Ventilation & Air Conditioning",
        "Kitchen Equipment",
        "Building Service",
        "Painting",
        "Television",
        "Air Condition",
        "Lighting",
        "Drafting request",
        "Water Leakage",
        "Sanitation",
        "Main Utilities Shutdown",
        "Health & Safety",
        "Other technical maintenance",
    ],
    "Janitorial": [
        "Sanitation",
        "Building cleaning",
        "Trash removal",
        "Other Janitorial",
    ],
    "Landscape": ["Ground", "Ground Maintenance", "Trash removal", "Other Gardening"],
    "Pest Control": [
        "Special Pest Control",
        "Bug Control",
        "Termite Control",
        "Others Pest",
    ],
    "Security": [
        "Health Issues",
        "Fire accidents",
        "Fight/dispute issues",
        "Theft Issues",
        "Others Security",
    ],
    "Accommodation": ["Gas", "Unit Special clean", "Key request", "Other accommodation"],
    "Internal Mail": ["Mail delivery request", "Other Internal mail issues"],
}


class Command(BaseCommand):
    help = "Seed campus locations, maintenance categories, and subcategories."

    @transaction.atomic
    def handle(self, *args, **options):
        for name in LOCATIONS:
            Building.objects.get_or_create(name=name, defaults={"is_active": True})

        categories = {}
        for name in CATEGORIES:
            categories[name], _ = Category.objects.get_or_create(
                name=name, defaults={"is_active": True}
            )

        count = 0
        for category_name, names in SUBCATEGORIES.items():
            for name in names:
                _, created = Subcategory.objects.get_or_create(
                    category=categories[category_name],
                    name=name,
                    defaults={"is_active": True},
                )
                count += created

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {len(LOCATIONS)} locations, {len(CATEGORIES)} categories, "
                f"and {count} new subcategory rows."
            )
        )
