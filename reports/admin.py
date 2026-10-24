from django.contrib import admin

from .models import Category, Photo, Report, StatusHistory


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    search_fields = ("name",)


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "resident", "status", "created_at")
    list_filter = ("status", "category", "building")
    search_fields = ("title", "resident__username")
    readonly_fields = (
        "resident",
        "category",
        "building",
        "room_location",
        "title",
        "description",
        "requested_urgency",
        "priority",
        "status",
        "merged_into",
        "version",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Photo)
class PhotoAdmin(admin.ModelAdmin):
    list_display = ("id", "report", "uploaded_by", "stage", "uploaded_at")
    readonly_fields = (
        "report",
        "uploaded_by",
        "stage",
        "private_filename",
        "uploaded_at",
    )

    @admin.display(description="Stored file")
    def private_filename(self, obj):
        return obj.file.name

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(StatusHistory)
class StatusHistoryAdmin(admin.ModelAdmin):
    list_display = ("report", "old_status", "new_status", "changed_by", "changed_at")
    readonly_fields = (
        "report",
        "old_status",
        "new_status",
        "changed_by",
        "note",
        "changed_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
