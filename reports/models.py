from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import Q


class ReportStatus(models.TextChoices):
    SUBMITTED = "SUBMITTED", "Submitted"
    UNDER_REVIEW = "UNDER_REVIEW", "Under review"
    ASSIGNED = "ASSIGNED", "Assigned"
    IN_PROGRESS = "IN_PROGRESS", "In progress"
    ON_HOLD = "ON_HOLD", "On hold"
    COMPLETED = "COMPLETED", "Completed"
    CLOSED = "CLOSED", "Closed"
    REOPENED = "REOPENED", "Reopened"
    REJECTED = "REJECTED", "Rejected"


class Channel(models.TextChoices):
    WEB = "WEB", "Web"
    PHONE = "PHONE", "Phone"
    EMAIL = "EMAIL", "Email"
    WALK_IN = "WALK_IN", "Walk in"


class Priority(models.TextChoices):
    LOW = "LOW", "Low"
    MEDIUM = "MEDIUM", "Medium"
    HIGH = "HIGH", "High"
    URGENT = "URGENT", "Urgent"


class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    default_unit = models.ForeignKey("accounts.Unit", null=True, blank=True, on_delete=models.PROTECT, related_name="default_categories")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name


class Subcategory(models.Model):
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="subcategories")
    name = models.CharField(max_length=100)
    default_unit = models.ForeignKey("accounts.Unit", null=True, blank=True, on_delete=models.PROTECT, related_name="default_subcategories")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("category__name", "name")
        constraints = [
            models.UniqueConstraint(fields=("category", "name"), name="subcategory_unique_per_category"),
            models.UniqueConstraint(fields=("id", "category"), name="subcategory_id_category_uq"),
        ]

    def __str__(self):
        return self.name


class ReportManager(models.Manager):
    def for_user(self, user):
        if getattr(user, "role", None) == "RESIDENT":
            return self.filter(resident=user)
        if getattr(user, "role", None) == "CALL_CENTER_STAFF":
            return self.get_queryset()
        if getattr(user, "role", None) == "TECHNICIAN_CONTRACTOR":
            if not getattr(user, "pk", None):
                return self.none()
            assignment_scope = Q(assignments__technician_id=user.pk)
            if user.unit_id is not None:
                assignment_scope |= Q(assignments__unit_id=user.unit_id)
            return (
                self.get_queryset()
                .filter(assignments__is_active=True)
                .filter(assignment_scope)
                .distinct()
            )
        return self.none()


class Report(models.Model):
    Status = ReportStatus

    objects = ReportManager()

    ticket_no = models.CharField(
        max_length=30,
        unique=True,
        validators=[RegexValidator(r"^CMR-2026-[0-9]+-[0-9]{6}$", "Enter a ticket number in CMR-2026-studentID-sequence format.")],
    )
    resident = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="reports", limit_choices_to={"role": "RESIDENT"})
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="entered_reports", null=True, blank=True)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="reports")
    subcategory = models.ForeignKey(Subcategory, on_delete=models.PROTECT, related_name="reports", null=True, blank=True)
    building = models.ForeignKey("accounts.Building", on_delete=models.PROTECT, related_name="reports")
    room_location = models.CharField(max_length=100)
    title = models.CharField(max_length=150)
    description = models.TextField()
    channel = models.CharField(max_length=10, choices=Channel.choices)
    requested_urgency = models.CharField(max_length=10, choices=Priority.choices, null=True, blank=True)
    priority = models.CharField(max_length=10, choices=Priority.choices, null=True, blank=True)
    status = models.CharField(max_length=20, choices=ReportStatus.choices, default=ReportStatus.SUBMITTED)
    expected_date = models.DateField(null=True, blank=True)
    location_verified_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="verified_reports", null=True, blank=True)
    location_verified_at = models.DateTimeField(null=True, blank=True)
    version = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    awaiting_call_center_response = models.BooleanField(default=False)

    class Meta:
        ordering = ("-created_at", "-pk")
        indexes = [
            models.Index(fields=("status",), name="report_status_idx"),
            models.Index(fields=("resident",), name="report_resident_idx"),
            models.Index(fields=("created_at",), name="report_created_idx"),
        ]
        constraints = [
            models.CheckConstraint(condition=models.Q(status__in=ReportStatus.values), name="report_status_valid"),
            models.CheckConstraint(condition=models.Q(priority__isnull=True) | models.Q(priority__in=Priority.values), name="report_priority_valid"),
            models.CheckConstraint(condition=models.Q(requested_urgency__isnull=True) | models.Q(requested_urgency__in=Priority.values), name="report_urgency_valid"),
            models.CheckConstraint(condition=models.Q(channel__in=Channel.values), name="report_channel_valid"),
            models.CheckConstraint(condition=models.Q(location_verified_by__isnull=True, location_verified_at__isnull=True) | models.Q(location_verified_by__isnull=False, location_verified_at__isnull=False), name="report_location_check_pair"),
        ]

    def __str__(self):
        return f"Request #{self.pk}: {self.title}"


class Verification(models.Model):
    class Outcome(models.TextChoices):
        VERIFIED = "VERIFIED", "Verified"
        REOPENED = "REOPENED", "Reopened"

    report = models.ForeignKey(Report, on_delete=models.PROTECT, related_name="verifications")
    resident = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="report_verifications")
    assignment = models.ForeignKey("assignments.Assignment", on_delete=models.PROTECT, related_name="verifications")
    outcome = models.CharField(max_length=10, choices=Outcome.choices)
    rating = models.PositiveSmallIntegerField(null=True, blank=True)
    comment = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("report", "assignment"), name="unique_report_assignment_verification"),
            models.CheckConstraint(condition=models.Q(rating__isnull=True) | models.Q(rating__gte=1, rating__lte=5), name="verification_rating_range"),
            models.CheckConstraint(condition=models.Q(outcome="REOPENED", rating__isnull=True, comment__gt="") | ~models.Q(outcome="REOPENED"), name="verification_reopened_rules"),
        ]


class CommentManager(models.Manager):
    def for_user(self, user, report):
        if Report.objects.for_user(user).filter(pk=report.pk).exists():
            return self.filter(report=report)
        return self.none()


class Comment(models.Model):
    objects = CommentManager()

    class Kind(models.TextChoices):
        COMMENT = "COMMENT", "Comment"
        FOLLOW_UP = "FOLLOW_UP", "Follow up"

    report = models.ForeignKey(Report, on_delete=models.PROTECT, related_name="comments")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="report_comments")
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.COMMENT)
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("created_at", "pk")
        constraints = [models.CheckConstraint(condition=models.Q(body__gt=""), name="comment_body_not_blank")]


class Photo(models.Model):
    class Stage(models.TextChoices):
        REPORT = "REPORT", "Report"
        COMPLETION = "COMPLETION", "Completion"

    report = models.ForeignKey(Report, on_delete=models.PROTECT, related_name="photos")
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="uploaded_report_photos")
    assignment = models.ForeignKey("assignments.Assignment", on_delete=models.PROTECT, related_name="photos", null=True, blank=True)
    stage = models.CharField(max_length=12, choices=Stage.choices)
    file_path = models.CharField(max_length=255, unique=True)
    content_type = models.CharField(max_length=20)
    size_bytes = models.PositiveIntegerField()

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(stage="COMPLETION", assignment__isnull=False) | models.Q(stage="REPORT", assignment__isnull=True), name="photo_completion_has_assignment"),
            models.CheckConstraint(condition=models.Q(size_bytes__gt=0), name="photo_size_positive"),
        ]

    @property
    def file(self):
        class StoredFile:
            def __init__(self, owner):
                self.owner = owner

            @property
            def name(self):
                return self.owner.file_path

            def open(self, mode="rb"):
                from .storage import private_photo_storage
                return private_photo_storage.open(self.owner.file_path, mode)

            def delete(self, save=False):
                return None

        return StoredFile(self)

    @file.setter
    def file(self, uploaded_file):
        self.file_path = f"reports/{getattr(uploaded_file, 'name', 'photo')}"
        self.content_type = getattr(uploaded_file, "content_type", "image/jpeg")
        self.size_bytes = getattr(uploaded_file, "size", 0) or 1


class StatusHistoryQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Status history records are append-only.")

    def delete(self):
        raise ValidationError("Status history records are append-only.")


class StatusHistory(models.Model):
    objects = StatusHistoryQuerySet.as_manager()
    report = models.ForeignKey(Report, on_delete=models.PROTECT, related_name="status_history")
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="report_status_changes")
    assignment = models.ForeignKey("assignments.Assignment", on_delete=models.PROTECT, related_name="status_history", null=True, blank=True)
    old_status = models.CharField(max_length=20, choices=ReportStatus.choices, null=True, blank=True)
    new_status = models.CharField(max_length=20, choices=ReportStatus.choices)
    note = models.CharField(max_length=500, blank=True, default="")
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("changed_at", "pk")
        constraints = [
            models.CheckConstraint(condition=models.Q(new_status__in=ReportStatus.values), name="history_new_status_valid"),
            models.CheckConstraint(condition=models.Q(old_status__isnull=True) | models.Q(old_status="") | models.Q(old_status__in=ReportStatus.values), name="history_old_status_valid"),
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Status history records are append-only.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Status history records are append-only.")


class AllowedTransition(models.Model):
    from_status = models.CharField(max_length=20, choices=ReportStatus.choices)
    to_status = models.CharField(max_length=20, choices=ReportStatus.choices)
    actor_role = models.CharField(
        max_length=32,
        choices=(
            ("RESIDENT", "Resident"),
            ("CALL_CENTER_STAFF", "Call Center Staff"),
            ("TECHNICIAN_CONTRACTOR", "Technician/Contractor"),
            ("SYSTEM", "System"),
        ),
    )

    class Meta:
        constraints = [models.UniqueConstraint(fields=("from_status", "to_status", "actor_role"), name="allowed_transition_unique")]
