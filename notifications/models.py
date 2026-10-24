from django.conf import settings
from django.db import models


class Notification(models.Model):
    class Channel(models.TextChoices):
        EMAIL = "EMAIL", "Email"
        IN_APP = "IN_APP", "In app"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        SENT = "SENT", "Sent"
        FAILED = "FAILED", "Failed"
        READ = "READ", "Read"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="notifications",
    )
    report = models.ForeignKey(
        "reports.Report", on_delete=models.PROTECT, related_name="notifications"
    )
    message = models.CharField(max_length=250)
    channel = models.CharField(max_length=16, choices=Channel.choices)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING
    )
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at", "-pk")
        indexes = [
            models.Index(fields=("user", "status"), name="notification_user_status_idx")
        ]

    def __str__(self):
        return f"{self.get_channel_display()} notification for report #{self.report_id}"
