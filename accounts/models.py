from django.contrib.auth.models import AbstractUser
from django.db import models


class Building(models.Model):
    name = models.CharField(max_length=120)
    zone = models.CharField(max_length=120)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("name", "zone"), name="unique_building_name_per_zone"
            )
        ]
        ordering = ("zone", "name")

    def __str__(self):
        return f"{self.name} ({self.zone})"


class User(AbstractUser):
    class Role(models.TextChoices):
        RESIDENT = "RESIDENT", "Resident"
        OFFICER = "OFFICER", "Officer"
        TECHNICIAN = "TECHNICIAN", "Technician"

    role = models.CharField(
        max_length=16, choices=Role.choices, default=Role.RESIDENT
    )
    building = models.ForeignKey(
        Building,
        on_delete=models.PROTECT,
        related_name="users",
        null=True,
        blank=True,
    )
    phone = models.CharField(max_length=32, blank=True)

    def __str__(self):
        return self.get_full_name() or self.username
