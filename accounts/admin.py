from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Building, User


@admin.register(User)
class CampusUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ("Campus details", {"fields": ("role", "building", "phone")}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("Campus details", {"fields": ("role", "building", "phone")}),
    )
    list_display = ("username", "email", "role", "building", "is_staff")
    list_filter = ("role", "building", "is_staff")


@admin.register(Building)
class BuildingAdmin(admin.ModelAdmin):
    list_display = ("name", "zone")
    search_fields = ("name", "zone")
