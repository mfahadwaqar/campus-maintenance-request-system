from django.contrib.auth.models import AbstractUser
from django.db import models


class Role(models.TextChoices):
    RESIDENT = "RESIDENT", "Resident"
    CALL_CENTER_STAFF = "CALL_CENTER_STAFF", "Call Center Staff"
    TECHNICIAN_CONTRACTOR = "TECHNICIAN_CONTRACTOR", "Technician/Contractor"


class UnitKind(models.TextChoices):
    CONTRACTOR = "CONTRACTOR", "Contractor"
    INTERNAL = "INTERNAL", "Internal"


class Building(models.Model):
    name = models.CharField(max_length=100, unique=True)
    zone = models.CharField(max_length=50, null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name


class RoomLocation(models.Model):
    class LocationType(models.TextChoices):
        DORMITORY = "DORMITORY", "Dormitory room"
        STUDENT_VILLAGE = "STUDENT_VILLAGE", "Student village"

    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=100)
    location_type = models.CharField(max_length=20, choices=LocationType.choices)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("location_type", "name", "code")

    def __str__(self):
        return f"{self.name} - {self.code}"


class Unit(models.Model):
    name = models.CharField(max_length=100, unique=True)
    kind = models.CharField(max_length=10, choices=UnitKind.choices)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name


class User(AbstractUser):
    Role = Role
    email = models.EmailField(max_length=254, unique=True)
    name = models.CharField(max_length=150, blank=True)
    role = models.CharField(max_length=32, choices=Role.choices, null=True, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    building = models.ForeignKey(
        Building,
        on_delete=models.PROTECT,
        related_name="residents",
        null=True,
        blank=True,
    )
    unit = models.ForeignKey(
        Unit,
        on_delete=models.PROTECT,
        related_name="staff",
        null=True,
        blank=True,
    )

    class Meta(AbstractUser.Meta):
        constraints = [
            models.CheckConstraint(condition=models.Q(role__isnull=False) | models.Q(is_staff=True), name="user_role_or_staff"),
            models.CheckConstraint(condition=models.Q(role__isnull=True) | models.Q(role__in=Role.values), name="user_role_valid"),
            models.CheckConstraint(condition=~models.Q(role="TECHNICIAN_CONTRACTOR") | models.Q(unit__isnull=False), name="user_technician_has_unit"),
        ]

    def save(self, *args, **kwargs):
        if not self.email:
            self.email = f"{self.username}@local.invalid"
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.name or self.get_full_name() or self.username
