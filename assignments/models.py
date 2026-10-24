from django.db.models import Q
from django.conf import settings
from django.db import models

from reports.models import Category


class TechnicianSpecialization(models.Model):
    technician = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="specializations",
        limit_choices_to={"role": "TECHNICIAN"},
    )
    category = models.ForeignKey(
        Category, on_delete=models.PROTECT, related_name="technician_specializations"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("technician", "category"),
                name="unique_technician_specialization",
            )
        ]
        ordering = ("technician__username", "category__name")

    def __str__(self):
        return f"{self.technician} — {self.category}"


class Assignment(models.Model):
    report = models.ForeignKey(
        "reports.Report", on_delete=models.PROTECT, related_name="assignments"
    )
    technician = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="assignments_received",
        limit_choices_to={"role": "TECHNICIAN"},
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="assignments_made",
        limit_choices_to={"role": "OFFICER"},
    )
    assigned_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    end_reason = models.CharField(max_length=250, blank=True)

    class Meta:
        ordering = ("-assigned_at", "-pk")
        indexes = [
            models.Index(
                fields=("technician", "is_active"), name="assign_tech_active_idx"
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("report",),
                condition=Q(is_active=True),
                name="one_active_assignment_per_report",
            )
        ]

    def __str__(self):
        return f"Report #{self.report_id} → {self.technician}"
