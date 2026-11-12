from django.conf import settings
from django.db import models
from django.utils import timezone


class EndReason(models.TextChoices):
    REASSIGNED = "REASSIGNED", "Reassigned"
    COMPLETED = "COMPLETED", "Completed"


class Assignment(models.Model):
    report = models.ForeignKey("reports.Report", on_delete=models.PROTECT, related_name="assignments")
    unit = models.ForeignKey("accounts.Unit", on_delete=models.PROTECT, related_name="assignments")
    technician = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="assignments_received", null=True, blank=True)
    assigned_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="assignments_made")
    assigned_at = models.DateTimeField(default=timezone.now)
    is_active = models.BooleanField(default=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    completion_notes = models.TextField(null=True, blank=True)
    requester_signed_on_site = models.BooleanField(default=False)
    ended_at = models.DateTimeField(null=True, blank=True)
    end_reason = models.CharField(max_length=12, choices=EndReason.choices, null=True, blank=True)

    class Meta:
        ordering = ("-assigned_at", "-pk")
        indexes = [models.Index(fields=("unit",), condition=models.Q(is_active=True), name="assignment_active_by_unit_idx")]
        constraints = [
            models.UniqueConstraint(fields=("report",), condition=models.Q(is_active=True), name="one_active_assignment_per_report"),
            models.CheckConstraint(condition=models.Q(is_active=True, ended_at__isnull=True) | models.Q(is_active=False, ended_at__isnull=False), name="assignment_active_matches_ended"),
            models.CheckConstraint(condition=(models.Q(ended_at__isnull=True, end_reason__isnull=True) | models.Q(ended_at__isnull=False, end_reason__isnull=False)), name="assignment_end_reason_matches_ended"),
            models.CheckConstraint(condition=~models.Q(end_reason="COMPLETED") | (models.Q(completed_at__isnull=False) & models.Q(completion_notes__isnull=False) & ~models.Q(completion_notes="")), name="assignment_completed_has_notes"),
        ]
