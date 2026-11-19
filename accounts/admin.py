from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import AdminUserCreationForm, UserChangeForm

from .models import Building, Role, RoomLocation, Unit, User


class RoleChecksMixin:
    """Catch the combinations the database would refuse, with a readable message."""

    def clean(self):
        cleaned = super().clean()
        role = cleaned.get("role")
        if role == Role.TECHNICIAN_CONTRACTOR and not cleaned.get("unit"):
            self.add_error("unit", "A Technician/Contractor must belong to a unit.")
        if not role and not cleaned.get("is_staff"):
            self.add_error(
                "role",
                "Choose a role, or tick Staff status for an administrator with no role.",
            )
        return cleaned


class CampusUserCreationForm(RoleChecksMixin, AdminUserCreationForm):
    pass


class CampusUserChangeForm(RoleChecksMixin, UserChangeForm):
    pass


@admin.register(User)
class CampusUserAdmin(UserAdmin):
    form = CampusUserChangeForm
    add_form = CampusUserCreationForm
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Personal info", {"fields": ("name", "first_name", "last_name", "email", "phone")}),
        ("Campus details", {"fields": ("role", "unit", "building")}),
        (
            "Permissions",
            {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")},
        ),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("username", "usable_password", "password1", "password2")}),
        ("Personal info", {"fields": ("name", "email", "phone")}),
        ("Campus details", {"fields": ("role", "unit", "building")}),
        ("Access to this admin site", {"fields": ("is_staff", "is_superuser")}),
    )
    list_display = ("username", "name", "email", "role", "unit", "building", "is_staff")
    list_filter = ("role", "unit", "building", "is_staff")
    search_fields = ("username", "name", "email", "first_name", "last_name")


@admin.register(Building)
class BuildingAdmin(admin.ModelAdmin):
    list_display = ("name", "zone", "is_active")
    list_filter = ("zone", "is_active")
    search_fields = ("name", "zone")


@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "is_active")
    list_filter = ("kind", "is_active")
    search_fields = ("name",)


@admin.register(RoomLocation)
class RoomLocationAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "location_type", "is_active")
    list_filter = ("location_type", "is_active")
    search_fields = ("code", "name")
