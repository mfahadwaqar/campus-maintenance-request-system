from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from .storage import private_photo_storage


class ReportStatus(models.TextChoices):
    SUBMITTED = "SUBMITTED", "Submitted"
    UNDER_REVIEW = "UNDER_REVIEW", "Under review"
    ASSIGNED = "ASSIGNED", "Assigned"
    IN_PROGRESS = "IN_PROGRESS", "In progress"
    COMPLETED = "COMPLETED", "Completed"
    CLOSED = "CLOSED", "Closed"
    REOPENED = "REOPENED", "Reopened"
    REJECTED = "REJECTED", "Rejected"
    MERGED = "MERGED", "Merged"


class Category(models.Model):
    name = models.CharField(max_length=120, unique=True)

    class Meta:
        ordering = ("name",)
        verbose_name_plural = "categories"

    def __str__(self):
        return self.name


class ReportQuerySet(models.QuerySet):
    def for_user(self, user):
        """Return only reports visible to this account's stored role."""

        if not user.is_authenticated:
            return self.none()

        role = getattr(user, "role", None)
        if role == "RESIDENT":
            return self.filter(resident=user)
        if role == "OFFICER":
            return self
        if role == "TECHNICIAN":
            try:
                from assignments.models import Assignment

                assigned_report_ids = Assignment.objects.filter(
                    technician=user
                ).values("report_id")
                return self.filter(pk__in=assigned_report_ids)
            except ImportError:
                return self.none()
        return self.none()


class Report(models.Model):
    Status = ReportStatus

    resident = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="reports",
        limit_choices_to={"role": "RESIDENT"},
    )
    category = models.ForeignKey(
        Category, on_delete=models.PROTECT, related_name="reports"
    )
    building = models.ForeignKey(
        "accounts.Building", on_delete=models.PROTECT, related_name="reports"
    )
    room_location = models.CharField(max_length=120)
    title = models.CharField(max_length=160)
    description = models.TextField()
    requested_urgency = models.CharField(
        max_length=16, choices=settings.REQUESTED_URGENCY_CHOICES
    )
    priority = models.CharField(
        max_length=16, choices=settings.PRIORITY_CHOICES, blank=True
    )
    status = models.CharField(
        max_length=16, choices=ReportStatus.choices, default=ReportStatus.SUBMITTED
    )
    merged_into = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        related_name="merged_reports",
        null=True,
        blank=True,
    )
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ReportQuerySet.as_manager()

    class Meta:
        ordering = ("-created_at", "-pk")
        indexes = [
            models.Index(fields=("status",), name="report_status_idx"),
            models.Index(fields=("resident",), name="report_resident_idx"),
            models.Index(fields=("created_at",), name="report_created_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=ReportStatus.values),
                name="report_status_valid",
            )
        ]

    def __str__(self):
        return f"Request #{self.pk}: {self.title}"


def photo_upload_path(instance, filename):
    extension = ".jpg" if filename.lower().endswith((".jpg", ".jpeg")) else ".png"
    return f"reports/{uuid4().hex}{extension}"


class AppendOnlyQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Status history entries cannot be changed.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError("Status history entries cannot be changed.")

    def delete(self):
        raise ValidationError("Status history entries cannot be deleted.")


class Verification(models.Model):
    class Outcome(models.TextChoices):
        VERIFIED = "VERIFIED", "Verified"
        REOPENED = "REOPENED", "Reopened"

    report = models.ForeignKey(
        Report, on_delete=models.PROTECT, related_name="verifications"
    )
    resident = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="report_verifications",
    )
    outcome = models.CharField(max_length=12, choices=Outcome.choices)
    rating = models.PositiveSmallIntegerField(null=True, blank=True)
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("created_at", "pk")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(rating__isnull=True)
                | models.Q(rating__gte=1, rating__lte=5),
                name="verification_rating_range",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(outcome="VERIFIED", rating__gte=1, rating__lte=5)
                    | models.Q(outcome="REOPENED", rating__isnull=True)
                ),
                name="verification_outcome_rating_match",
            ),
        ]

    def __str__(self):
        return f"Report #{self.report_id}: {self.get_outcome_display()}"


class CommentQuerySet(models.QuerySet):
    def for_user(self, user, report=None):
        """Filter comments by report access and internal-comment visibility."""

        if not user.is_authenticated:
            return self.none()
        visible_reports = Report.objects.for_user(user)
        queryset = self.filter(report__in=visible_reports)
        if report is not None:
            queryset = queryset.filter(report=report)
        if user.role == "RESIDENT":
            queryset = queryset.filter(is_internal=False)
        return queryset


class Comment(models.Model):
    report = models.ForeignKey(
        Report, on_delete=models.PROTECT, related_name="comments"
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="report_comments",
    )
    body = models.TextField(max_length=2000)
    is_internal = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = CommentQuerySet.as_manager()

    class Meta:
        ordering = ("created_at", "pk")
        indexes = [
            models.Index(fields=("report", "created_at"), name="comment_report_date_idx")
        ]

    def __str__(self):
        return f"Comment on report #{self.report_id} by {self.author}"


class Photo(models.Model):
    class Stage(models.TextChoices):
        REPORT = "REPORT", "Report"
        COMPLETION = "COMPLETION", "Completion"

    report = models.ForeignKey(
        Report, on_delete=models.PROTECT, related_name="photos"
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="uploaded_report_photos",
    )
    stage = models.CharField(max_length=16, choices=Stage.choices)
    file = models.ImageField(
        upload_to=photo_upload_path,
        storage=private_photo_storage,
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("uploaded_at", "pk")
        indexes = [models.Index(fields=("report", "stage"), name="photo_report_stage_idx")]

    def __str__(self):
        return f"{self.get_stage_display()} photo for report #{self.report_id}"


class StatusHistory(models.Model):
    report = models.ForeignKey(
        Report, on_delete=models.PROTECT, related_name="status_history"
    )
    old_status = models.CharField(
        max_length=16, choices=Report.Status.choices, blank=True
    )
    new_status = models.CharField(max_length=16, choices=Report.Status.choices)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="report_status_changes",
    )
    note = models.CharField(max_length=500, blank=True)
    changed_at = models.DateTimeField(auto_now_add=True)

    objects = AppendOnlyQuerySet.as_manager()

    class Meta:
        ordering = ("changed_at", "pk")
        indexes = [
            models.Index(fields=("report", "changed_at"), name="history_report_date_idx")
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(new_status__in=Report.Status.values),
                name="history_new_status_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(old_status="") | models.Q(old_status__in=Report.Status.values),
                name="history_old_status_valid",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValidationError("Status history entries cannot be changed.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Status history entries cannot be deleted.")

    def __str__(self):
        return f"Report #{self.report_id}: {self.old_status or 'NEW'} → {self.new_status}"
