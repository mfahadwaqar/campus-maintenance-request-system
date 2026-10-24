from django.contrib import admin

from .models import Assignment, TechnicianSpecialization


@admin.register(TechnicianSpecialization)
class TechnicianSpecializationAdmin(admin.ModelAdmin):
    list_display = ("technician", "category")
    list_filter = ("category",)
    search_fields = ("technician__username", "category__name")


@admin.register(Assignment)
class AssignmentAdmin(admin.ModelAdmin):
    list_display = (
        "report",
        "technician",
        "assigned_by",
        "assigned_at",
        "is_active",
    )
    list_filter = ("is_active",)
    readonly_fields = (
        "report",
        "technician",
        "assigned_by",
        "assigned_at",
        "is_active",
        "ended_at",
        "end_reason",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
