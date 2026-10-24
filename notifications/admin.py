from django.contrib import admin

from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "report", "channel", "status", "created_at")
    list_filter = ("channel", "status")
    search_fields = ("user__username", "report__id", "message")
    readonly_fields = (
        "user",
        "report",
        "message",
        "channel",
        "status",
        "created_at",
        "read_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
