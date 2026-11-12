from django.contrib import admin

from .models import Category, Photo, StatusHistory


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    search_fields = ("name",)


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
