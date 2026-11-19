from django.contrib import admin

from .models import (
    Category,
    Comment,
    Photo,
    Report,
    StatusHistory,
    Subcategory,
    Verification,
)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "default_unit", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name",)


@admin.register(Subcategory)
class SubcategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "default_unit", "is_active")
    list_filter = ("category", "is_active")
    search_fields = ("name", "category__name")


class ReadOnlyAdmin(admin.ModelAdmin):
    """Reports and their records change only through the workflow, which keeps the audit trail."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Report)
class ReportAdmin(ReadOnlyAdmin):
    list_display = (
        "ticket_no",
        "title",
        "status",
        "resident",
        "building",
        "room_location",
        "priority",
        "created_at",
    )
    list_filter = ("status", "priority", "channel", "building", "category")
    search_fields = ("ticket_no", "title", "room_location", "resident__username", "resident__email")
    date_hierarchy = "created_at"


@admin.register(Comment)
class CommentAdmin(ReadOnlyAdmin):
    list_display = ("report", "author", "kind", "created_at")
    list_filter = ("kind",)
    search_fields = ("body", "report__ticket_no")


@admin.register(Verification)
class VerificationAdmin(ReadOnlyAdmin):
    list_display = ("report", "resident", "outcome", "rating", "created_at")
    list_filter = ("outcome", "rating")


@admin.register(Photo)
class PhotoAdmin(admin.ModelAdmin):
    list_display = ("id", "report", "uploaded_by", "stage", "file_path")
    readonly_fields = (
        "report",
        "uploaded_by",
        "stage",
        "file_path",
        "content_type",
        "size_bytes",
    )

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
