from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    OpenApiTypes,
    extend_schema,
    extend_schema_field,
)
from rest_framework import serializers, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import Building, RoomLocation, Unit, UnitKind
from accounts.room_validation import validate_room_location
from assignments.models import Assignment
from notifications.models import Notification

from .models import (
    Category,
    Comment,
    Photo,
    Report,
    StatusHistory,
    Subcategory,
)
from .services import (
    ReportConflict,
    add_comment,
    assign_technician,
    complete_work,
    enter_report_for_caller,
    put_on_hold,
    reject_report,
    reopen_report,
    start_review,
    start_work,
    submit_report,
    verify_report,
)

User = get_user_model()


def _person(user):
    if user is None:
        return None
    return {
        "id": user.pk,
        "name": user.name or user.get_full_name() or user.get_username(),
    }


def _assignment_payload(assignment):
    return {
        "id": assignment.pk,
        "unit": {"id": assignment.unit_id, "name": assignment.unit.name},
        "technician": _person(assignment.technician),
        "assigned_at": assignment.assigned_at,
        "started_at": assignment.started_at,
        "completed_at": assignment.completed_at,
        "is_active": assignment.is_active,
        "end_reason": assignment.end_reason,
    }


class ReportSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)
    subcategory_name = serializers.CharField(source="subcategory.name", read_only=True)
    building_name = serializers.CharField(source="building.name", read_only=True)
    room_verified = serializers.SerializerMethodField()
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    resident = serializers.SerializerMethodField()
    active_assignment = serializers.SerializerMethodField()
    assignments = serializers.SerializerMethodField()
    completion = serializers.SerializerMethodField()
    hold = serializers.SerializerMethodField()
    reopen = serializers.SerializerMethodField()
    verification = serializers.SerializerMethodField()
    photos = serializers.SerializerMethodField()

    def get_room_verified(self, report) -> bool:
        return report.location_verified_at is not None

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_resident(self, report):
        resident = report.resident
        return {
            **_person(resident),
            "student_id": resident.get_username(),
            "email": resident.email,
            "phone": resident.phone,
        }

    def _assignment_rows(self, report):
        return sorted(
            report.assignments.all(),
            key=lambda row: (row.assigned_at, row.pk),
            reverse=True,
        )

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_active_assignment(self, report):
        for row in self._assignment_rows(report):
            if row.is_active:
                return _assignment_payload(row)
        return None

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_assignments(self, report):
        return [_assignment_payload(row) for row in self._assignment_rows(report)]

    def _completion_assignment(self, report):
        done = [row for row in report.assignments.all() if row.completed_at]
        return max(done, key=lambda row: (row.completed_at, row.pk), default=None)

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_completion(self, report):
        row = self._completion_assignment(report)
        if row is None:
            return None
        return {
            "completed_at": row.completed_at,
            "completion_notes": row.completion_notes,
            "requester_signed_on_site": row.requester_signed_on_site,
            "completed_without_resident": not row.requester_signed_on_site,
        }

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_hold(self, report):
        if report.status != Report.Status.ON_HOLD:
            return None
        latest = (
            report.status_history.filter(new_status=Report.Status.ON_HOLD)
            .order_by("-changed_at", "-pk")
            .first()
        )
        return {
            "reason": latest.note if latest else "",
            "expected_date": report.expected_date,
        }

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_reopen(self, report):
        """Reopen window for a closed ticket. The front end still checks the role."""
        if report.status != Report.Status.CLOSED:
            return None
        row = self._completion_assignment(report)
        if row is None:
            return None
        days = getattr(settings, "REOPEN_WINDOW_DAYS", 3)
        deadline = row.completed_at + timedelta(days=days)
        remaining = (deadline - timezone.now()).total_seconds()
        return {
            "window_days": days,
            "deadline": deadline,
            "window_open": remaining >= 0,
            "seconds_remaining": max(0, int(remaining)),
        }

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_verification(self, report):
        rows = sorted(
            report.verifications.all(),
            key=lambda row: (row.created_at, row.pk),
            reverse=True,
        )
        if not rows:
            return None
        row = rows[0]
        return {
            "outcome": row.outcome,
            "rating": row.rating,
            "comment": row.comment,
            "created_at": row.created_at,
        }

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_photos(self, report):
        return [
            {
                "id": photo.pk,
                "stage": photo.stage,
                "url": reverse(
                    "api:report-photo",
                    kwargs={"report_id": report.pk, "photo_id": photo.pk},
                ),
            }
            for photo in sorted(report.photos.all(), key=lambda row: row.pk)
        ]

    class Meta:
        model = Report
        fields = (
            "id",
            "ticket_no",
            "category",
            "category_name",
            "subcategory",
            "subcategory_name",
            "building",
            "building_name",
            "room_location",
            "room_verified",
            "location_verified_by",
            "location_verified_at",
            "title",
            "description",
            "channel",
            "requested_urgency",
            "priority",
            "status",
            "expected_date",
            "version",
            "created_at",
            "updated_at",
            "status_label",
            "resident",
            "active_assignment",
            "assignments",
            "completion",
            "hold",
            "reopen",
            "verification",
            "photos",
        )
        read_only_fields = fields


class ApiErrorSerializer(serializers.Serializer):
    error = serializers.ChoiceField(
        choices=(
            "ticket_closed",
            "reopen_window_closed",
            "ticket_not_closed",
            "version_conflict",
        ),
        required=False,
    )
    detail = serializers.JSONField()


class ApiDetailErrorSerializer(serializers.Serializer):
    detail = serializers.JSONField()


class ReportCreateSerializer(serializers.Serializer):
    category = serializers.PrimaryKeyRelatedField(
        queryset=Category.objects.filter(is_active=True)
    )
    subcategory = serializers.PrimaryKeyRelatedField(
        queryset=Subcategory.objects.filter(is_active=True),
        required=False,
        allow_null=True,
    )
    building = serializers.PrimaryKeyRelatedField(
        queryset=Building.objects.filter(is_active=True)
    )
    room_location = serializers.CharField(max_length=100)
    room_verified = serializers.BooleanField()
    title = serializers.CharField(max_length=150)
    description = serializers.CharField()
    requested_urgency = serializers.ChoiceField(
        choices=settings.REQUESTED_URGENCY_CHOICES
    )
    photo = serializers.FileField(required=False, allow_null=True)

    def validate(self, attrs):
        if not attrs["room_verified"]:
            raise serializers.ValidationError(
                {"room_verified": "Confirm the building and room before creating the report."}
            )
        subcategory = attrs.get("subcategory")
        if subcategory and subcategory.category_id != attrs["category"].pk:
            raise serializers.ValidationError(
                {"subcategory": "Choose a subcategory within the selected category."}
            )
        try:
            attrs["room_location"] = validate_room_location(
                attrs["building"], attrs["room_location"]
            )
        except DjangoValidationError as exc:
            raise serializers.ValidationError(
                {"room_location": exc.messages}
            ) from exc
        return attrs

    def validate_photo(self, value):
        if value is None:
            return None
        from .photo_pipeline import validate_and_reencode_photo

        try:
            return validate_and_reencode_photo(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages) from exc


class AssignmentCreateSerializer(serializers.Serializer):
    unit = serializers.PrimaryKeyRelatedField(
        queryset=Unit.objects.filter(is_active=True),
    )
    technician = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(
            role=User.Role.TECHNICIAN_CONTRACTOR,
            is_active=True,
        ),
        required=False,
    )
    priority = serializers.ChoiceField(
        choices=settings.PRIORITY_CHOICES,
        required=False,
        allow_null=True,
        allow_blank=True,
    )
    version = serializers.IntegerField(min_value=0)

    def validate(self, attrs):
        unit = attrs.get("unit") or getattr(attrs.get("technician"), "unit", None)
        technician = attrs.get("technician")
        if unit is None:
            raise serializers.ValidationError({"unit": "Select an active unit."})
        if technician is not None and technician.unit_id != unit.pk:
            raise serializers.ValidationError(
                {"technician": "The Technician/Contractor must belong to the selected unit."}
            )
        attrs["unit"] = unit
        return attrs


class CallCenterReportCreateSerializer(ReportCreateSerializer):
    resident = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(role=User.Role.RESIDENT, is_active=True)
    )
    channel = serializers.ChoiceField(choices=("PHONE", "EMAIL", "WALK_IN"))
    unit = serializers.PrimaryKeyRelatedField(
        queryset=Unit.objects.filter(is_active=True),
        required=False,
        allow_null=True,
    )
    technician = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(
            role=User.Role.TECHNICIAN_CONTRACTOR, is_active=True
        ),
        required=False,
        allow_null=True,
    )
    priority = serializers.ChoiceField(
        choices=settings.PRIORITY_CHOICES,
        required=False,
        allow_null=True,
        allow_blank=True,
    )

    def validate(self, attrs):
        attrs = super().validate(attrs)
        unit = attrs.get("unit") or getattr(attrs.get("technician"), "unit", None)
        technician = attrs.get("technician")
        if technician and unit is not None and technician.unit_id != unit.pk:
            raise serializers.ValidationError(
                {"technician": "The Technician/Contractor must belong to the selected unit."}
            )
        if unit is not None:
            attrs["unit"] = unit
        return attrs

class ReportStatusUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=(
            Report.Status.UNDER_REVIEW,
            Report.Status.REJECTED,
            Report.Status.IN_PROGRESS,
            Report.Status.ON_HOLD,
            Report.Status.COMPLETED,
        )
    )
    version = serializers.IntegerField(min_value=0)
    reason = serializers.CharField(max_length=400, required=False, allow_blank=True)
    expected_date = serializers.DateField(required=False)
    completion_notes = serializers.CharField(
        max_length=2000, required=False, allow_blank=True
    )
    photo = serializers.FileField(required=False, allow_null=True)
    requester_signed_on_site = serializers.BooleanField(required=False, default=False)
    room_verified = serializers.BooleanField(required=False, default=False)


class VerificationSerializer(serializers.Serializer):
    rating = serializers.IntegerField(min_value=1, max_value=5, required=False, allow_null=True)
    comment = serializers.CharField(max_length=2000, required=False, allow_blank=True)
    version = serializers.IntegerField(min_value=0)


class ReopenSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=1000)
    version = serializers.IntegerField(min_value=0)


class CommentCreateSerializer(serializers.Serializer):
    body = serializers.CharField(max_length=2000)


class CommentSerializer(serializers.ModelSerializer):
    author_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = Comment
        fields = ("id", "author_id", "kind", "body", "created_at")
        read_only_fields = fields


class HistorySerializer(serializers.ModelSerializer):
    changed_by_id = serializers.IntegerField(read_only=True)
    assignment_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = StatusHistory
        fields = (
            "id",
            "old_status",
            "new_status",
            "changed_by_id",
            "assignment_id",
            "note",
            "changed_at",
        )
        read_only_fields = fields


class NotificationSerializer(serializers.ModelSerializer):
    report_id = serializers.IntegerField(read_only=True)
    ticket_no = serializers.CharField(source="report.ticket_no", read_only=True)

    class Meta:
        model = Notification
        fields = (
            "id",
            "report_id",
            "ticket_no",
            "message",
            "channel",
            "status",
            "created_at",
            "read_at",
        )
        read_only_fields = fields


class ReportPageSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)
    results = ReportSerializer(many=True)


class CommentPageSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)
    results = CommentSerializer(many=True)


class HistoryPageSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)
    results = HistorySerializer(many=True)


class NotificationPageSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)
    results = NotificationSerializer(many=True)


class BuildingSerializer(serializers.ModelSerializer):
    class Meta:
        model = Building
        fields = ("id", "name", "zone")


class RoomLocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = RoomLocation
        fields = ("id", "code", "name", "location_type")


class UnitSerializer(serializers.ModelSerializer):
    class Meta:
        model = Unit
        fields = ("id", "name", "kind")


class UnitResultSerializer(serializers.Serializer):
    unit = serializers.CharField(help_text="Unit name.")
    jobs_completed = serializers.IntegerField()
    average_hours = serializers.FloatField(allow_null=True)
    unit_id = serializers.IntegerField()
    unit_name = serializers.CharField()
    kind = serializers.ChoiceField(choices=UnitKind.choices)
    completed_jobs = serializers.IntegerField()
    average_completion_hours = serializers.FloatField(allow_null=True)
    period = serializers.ChoiceField(choices=("month", "quarter", "year", "all"))


class SubcategoryReferenceSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class CategoryReferenceSerializer(serializers.ModelSerializer):
    subcategories = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = ("id", "name", "subcategories")

    @extend_schema_field(SubcategoryReferenceSerializer(many=True))
    def get_subcategories(self, category):
        return [
            {"id": item.pk, "name": item.name}
            for item in category.subcategories.filter(is_active=True).order_by("name")
        ]


REPORT_PREFETCH = (
    "assignments__unit",
    "assignments__technician",
    "photos",
    "verifications",
)


def _report_for_user(user, report_id):
    return get_object_or_404(
        Report.objects.for_user(user)
        .select_related("category", "building", "resident", "subcategory")
        .prefetch_related(*REPORT_PREFETCH)
        .filter(pk=report_id)
    )


def _validation_response(exc):
    code = getattr(exc, "code", None)
    if code in {"ticket_closed", "ticket_not_closed", "reopen_window_closed"}:
        return Response(
            {"error": code, "detail": exc.messages[0]},
            status=status.HTTP_409_CONFLICT,
        )
    if hasattr(exc, "message_dict"):
        return Response(exc.message_dict, status=status.HTTP_400_BAD_REQUEST)
    return Response(
        {"detail": exc.messages},
        status=status.HTTP_400_BAD_REQUEST,
    )


def _conflict_response(exc):
    return Response(
        {"error": getattr(exc, "code", "version_conflict"), "detail": str(exc)},
        status=status.HTTP_409_CONFLICT,
    )


def _page_response(request, queryset, serializer_class, *, context=None):
    paginator = PageNumberPagination()
    paginator.page_size = settings.REST_FRAMEWORK["PAGE_SIZE"]
    page = paginator.paginate_queryset(queryset, request)
    data = serializer_class(page, many=True, context=context).data
    return paginator.get_paginated_response(data)


API_VALIDATION_RESPONSE = OpenApiResponse(
    description="A JSON object containing serializer field errors."
)
API_DETAIL_ERROR_RESPONSE = OpenApiResponse(
    response=ApiDetailErrorSerializer,
    description="A JSON error response with a detail message.",
)
API_CODED_ERROR_RESPONSE = OpenApiResponse(
    response=ApiErrorSerializer,
    description=(
        "A coded workflow error. The error value is ticket_closed, "
        "reopen_window_closed, ticket_not_closed, or version_conflict."
    ),
)


class ReportListCreateAPIView(APIView):
    permission_classes = (IsAuthenticated,)

    @extend_schema(
        operation_id="reports_list",
        parameters=[
            OpenApiParameter("page", int, description="One-based page number."),
            OpenApiParameter("ticket_no", str, description="Exact ticket-number search; Call Center Staff only."),
            OpenApiParameter("student_id", str, description="Exact resident username search; Call Center Staff only."),
            OpenApiParameter("room", str, description="Case-insensitive partial room search; Call Center Staff only."),
        ],
        responses={
            200: ReportPageSerializer,
            400: API_VALIDATION_RESPONSE,
            401: API_DETAIL_ERROR_RESPONSE,
            403: API_DETAIL_ERROR_RESPONSE,
        },
        description=(
            "Return a paginated report collection scoped to the signed-in user's role: "
            "residents see their own reports, Call Center Staff see all reports, and "
            "Technician/Contractor users see reports assigned to their named account. "
            "Call Center Staff may also filter by exact "
            "`ticket_no`, exact `student_id`, or case-insensitive partial `room`; these search parameters "
            "return 403 for other roles. Supports `page`."
        ),
    )
    def get(self, request):
        """GET /api/reports/: role-scoped, paginated collection; requires a signed-in session."""
        reports = (
            Report.objects.for_user(request.user)
            .select_related("category", "building", "resident", "subcategory")
            .prefetch_related(*REPORT_PREFETCH)
        )
        search_values = {
            key: request.query_params.get(key, "").strip()
            for key in ("ticket_no", "student_id", "room")
        }
        search_requested = any(
            key in request.query_params
            for key in ("ticket_no", "student_id", "room")
        )
        if search_requested and request.user.role != User.Role.CALL_CENTER_STAFF:
            return Response(
                {"detail": "Only Call Center Staff may search across reports."},
                status=status.HTTP_403_FORBIDDEN,
            )
        if search_values["ticket_no"]:
            reports = reports.filter(ticket_no=search_values["ticket_no"])
        if search_values["student_id"]:
            reports = reports.filter(resident__username=search_values["student_id"])
        if search_values["room"]:
            reports = reports.filter(room_location__icontains=search_values["room"])
        return _page_response(request, reports, ReportSerializer)

    @extend_schema(
        operation_id="reports_create",
        request=ReportCreateSerializer,
        responses={
            201: ReportSerializer,
            400: API_VALIDATION_RESPONSE,
            401: API_DETAIL_ERROR_RESPONSE,
            403: API_DETAIL_ERROR_RESPONSE,
        },
        description=(
            "Create a report for the authenticated resident. Accepts JSON or multipart "
            "form data with category/building IDs, an active room-location code, title, "
            "description, urgency, and optional validated photo. Ticket number, resident, "
            "channel, status, version, and audit history are assigned by the server."
        ),
    )
    def post(self, request):
        """POST /api/reports/: resident-only resource creation; server owns identity and initial state."""
        if request.user.role != User.Role.RESIDENT:
            return Response(
                {"detail": "Only residents may submit reports."},
                status=status.HTTP_403_FORBIDDEN,
            )
        serializer = ReportCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        try:
            report = submit_report(
                resident=request.user,
                category=values["category"],
                subcategory=values.get("subcategory"),
                building=values["building"],
                room_location=values["room_location"],
                title=values["title"],
                description=values["description"],
                requested_urgency=values["requested_urgency"],
                room_verified=values["room_verified"],
                photo=values.get("photo"),
            )
        except DjangoValidationError as exc:
            return _validation_response(exc)
        return Response(
            ReportSerializer(report).data,
            status=status.HTTP_201_CREATED,
        )


class CallCenterReportCreateAPIView(APIView):
    permission_classes = (IsAuthenticated,)

    @extend_schema(
        operation_id="call_center_reports_create",
        request=CallCenterReportCreateSerializer,
        responses={
            201: ReportSerializer,
            400: API_VALIDATION_RESPONSE,
            401: API_DETAIL_ERROR_RESPONSE,
            403: API_DETAIL_ERROR_RESPONSE,
            409: API_DETAIL_ERROR_RESPONSE,
        },
        description=(
            "Create a phone, email, or walk-in report on behalf of an active resident. "
            "Call Center Staff must confirm the room. When a unit is supplied, the "
            "report and ASSIGNED transition are committed together; Technician/Contractor is optional."
        ),
    )
    def post(self, request):
        """POST /api/officer/reports/: validated intake; optional unit assignment shares one transaction."""
        if request.user.role != User.Role.CALL_CENTER_STAFF:
            return Response(
                {"detail": "Only Call Center Staff may enter reports for residents."},
                status=status.HTTP_403_FORBIDDEN,
            )
        serializer = CallCenterReportCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        try:
            with transaction.atomic():
                report = enter_report_for_caller(
                    resident=values["resident"],
                    submitted_by=request.user,
                    channel=values["channel"],
                    category=values["category"],
                    subcategory=values.get("subcategory"),
                    building=values["building"],
                    room_location=values["room_location"],
                    title=values["title"],
                    description=values["description"],
                    requested_urgency=values["requested_urgency"],
                    room_verified=values["room_verified"],
                    photo=values.get("photo"),
                )
                if values.get("unit"):
                    report = assign_technician(
                        report_id=report.pk,
                        technician=values.get("technician"),
                        assigned_by=request.user,
                        priority=values.get("priority"),
                        expected_version=report.version,
                        unit=values["unit"],
                    )
        except DjangoValidationError as exc:
            return _validation_response(exc)
        except IntegrityError:
            return Response(
                {"detail": "The report could not be created or assigned; retry with current data."},
                status=status.HTTP_409_CONFLICT,
            )
        return Response(ReportSerializer(report).data, status=status.HTTP_201_CREATED)


class ReportDetailAPIView(APIView):
    permission_classes = (IsAuthenticated,)

    @extend_schema(
        operation_id="reports_retrieve",
        responses={
            200: ReportSerializer,
            401: API_DETAIL_ERROR_RESPONSE,
            404: API_DETAIL_ERROR_RESPONSE,
        },
        description=(
            "Retrieve one report if it is visible to the authenticated user. "
            "Object-level visibility follows the same resident/Call Center Staff/Technician-Contractor "
            "rules as the report collection; inaccessible and nonexistent IDs return 404."
        ),
    )
    def get(self, request, report_id):
        """GET /api/reports/{id}/: retrieve a visible report; hidden objects return 404."""
        report = _report_for_user(request.user, report_id)
        return Response(ReportSerializer(report).data)


class ReportStatusAPIView(APIView):
    permission_classes = (IsAuthenticated,)

    @extend_schema(
        operation_id="reports_update_status",
        request=ReportStatusUpdateSerializer,
        responses={
            200: ReportSerializer,
            400: API_VALIDATION_RESPONSE,
            401: API_DETAIL_ERROR_RESPONSE,
            403: API_DETAIL_ERROR_RESPONSE,
            404: API_DETAIL_ERROR_RESPONSE,
            409: API_CODED_ERROR_RESPONSE,
        },
        description=(
            "Apply one permitted workflow transition using the shared report service. "
            "Every request includes the report `version`; stale versions return 409. "
            "Call Center Staff transitions: UNDER_REVIEW or REJECTED (reason required). "
            "The assigned Technician/Contractor transitions: IN_PROGRESS, ON_HOLD (reason and "
            "expected_date required), or COMPLETED (completion_notes required; "
            "`requester_signed_on_site` is optional and defaults to false. A multipart "
            "`photo` is optional when that flag is true and rejected when false. The "
            "service immediately records CLOSED). "
            "Use the dedicated assign, verify, and reopen resources for other transitions."
        ),
    )
    def patch(self, request, report_id):
        """PATCH /api/reports/{id}/status/: role-gated workflow state change with optimistic concurrency."""
        report = _report_for_user(request.user, report_id)
        serializer = ReportStatusUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        new_status = values["status"]

        officer_actions = {Report.Status.UNDER_REVIEW, Report.Status.REJECTED}
        expected_role = (
            User.Role.CALL_CENTER_STAFF
            if new_status in officer_actions
            else User.Role.TECHNICIAN_CONTRACTOR
        )
        if request.user.role != expected_role:
            return Response(
                {"detail": "Your role may not perform this status transition."},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            if new_status == Report.Status.UNDER_REVIEW:
                updated = start_review(
                    report_id=report.pk,
                    actor=request.user,
                    expected_version=values["version"],
                    room_verified=values["room_verified"],
                )
            elif new_status == Report.Status.REJECTED:
                updated = reject_report(
                    report_id=report.pk,
                    actor=request.user,
                    reason=values.get("reason", ""),
                    expected_version=values["version"],
                )
            elif new_status == Report.Status.IN_PROGRESS:
                updated = start_work(
                    report_id=report.pk,
                    technician=request.user,
                    expected_version=values["version"],
                )
            elif new_status == Report.Status.ON_HOLD:
                updated = put_on_hold(
                    report_id=report.pk,
                    technician=request.user,
                    expected_version=values["version"],
                    reason=values.get("reason", ""),
                    expected_date=values.get("expected_date"),
                )
            else:
                updated = complete_work(
                    report_id=report.pk,
                    technician=request.user,
                    expected_version=values["version"],
                    completion_notes=values.get("completion_notes", ""),
                    photo=values.get("photo"),
                    requester_signed_on_site=values.get(
                        "requester_signed_on_site", False
                    ),
                )
        except ReportConflict as exc:
            return _conflict_response(exc)
        except DjangoValidationError as exc:
            return _validation_response(exc)
        return Response(ReportSerializer(updated).data)


class ReportAssignmentAPIView(APIView):
    permission_classes = (IsAuthenticated,)

    @extend_schema(
        operation_id="reports_assign",
        request=AssignmentCreateSerializer,
        responses={
            200: ReportSerializer,
            400: API_VALIDATION_RESPONSE,
            401: API_DETAIL_ERROR_RESPONSE,
            403: API_DETAIL_ERROR_RESPONSE,
            404: API_DETAIL_ERROR_RESPONSE,
            409: API_CODED_ERROR_RESPONSE,
        },
        description=(
            "Assign or reassign a report to an active unit. Call Center Staff only. "
            "Technician/Contractor is optional, but if supplied must be active and belong to that unit. The report version "
            "is required to prevent stale writes; initial assignment from UNDER_REVIEW "
            "also requires a priority. The service records assignment and status history "
            "atomically; stale versions and integrity conflicts return 409."
        ),
    )
    def post(self, request, report_id):
        """POST /api/reports/{id}/assign/: Call Center Staff assignment resource with version checks and audit history."""
        report = _report_for_user(request.user, report_id)
        if request.user.role != User.Role.CALL_CENTER_STAFF:
            return Response(
                {"detail": "Only Call Center Staff may assign a Technician/Contractor."},
                status=status.HTTP_403_FORBIDDEN,
            )
        serializer = AssignmentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        try:
            updated = assign_technician(
                report_id=report.pk,
                technician=values.get("technician"),
                assigned_by=request.user,
                priority=values.get("priority") or None,
                expected_version=values["version"],
                unit=values["unit"],
            )
        except ReportConflict as exc:
            return _conflict_response(exc)
        except IntegrityError:
            return Response(
                {"detail": "The report assignment changed. Refresh and try again."},
                status=status.HTTP_409_CONFLICT,
            )
        except DjangoValidationError as exc:
            return _validation_response(exc)
        return Response(ReportSerializer(updated).data)


class ReportVerificationAPIView(APIView):
    permission_classes = (IsAuthenticated,)

    @extend_schema(
        operation_id="reports_verify",
        request=VerificationSerializer,
        responses={
            200: ReportSerializer,
            400: API_VALIDATION_RESPONSE,
            401: API_DETAIL_ERROR_RESPONSE,
            403: API_DETAIL_ERROR_RESPONSE,
            404: API_DETAIL_ERROR_RESPONSE,
            409: API_CODED_ERROR_RESPONSE,
        },
        description=(
            "Record verification feedback only after the system has closed the "
            "authenticated resident's report. Rating (1-5) and comment are optional; "
            "the report status does not change. Stale versions return 409."
        ),
    )
    def post(self, request, report_id):
        """POST /api/reports/{id}/verify/: owner-only verification and rating; GET is not allowed."""
        report = _report_for_user(request.user, report_id)
        if request.user.role != User.Role.RESIDENT:
            return Response(
                {"detail": "Only the requesting resident may verify work."},
                status=status.HTTP_403_FORBIDDEN,
            )
        serializer = VerificationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            updated = verify_report(
                report_id=report.pk,
                resident=request.user,
                expected_version=serializer.validated_data["version"],
                rating=serializer.validated_data.get("rating"),
                comment=serializer.validated_data.get("comment", ""),
            )
        except ReportConflict as exc:
            return _conflict_response(exc)
        except DjangoValidationError as exc:
            return _validation_response(exc)
        return Response(ReportSerializer(updated).data)


class ReportReopenAPIView(APIView):
    permission_classes = (IsAuthenticated,)

    @extend_schema(
        operation_id="reports_reopen",
        request=ReopenSerializer,
        responses={
            200: ReportSerializer,
            400: API_VALIDATION_RESPONSE,
            401: API_DETAIL_ERROR_RESPONSE,
            403: API_DETAIL_ERROR_RESPONSE,
            404: API_DETAIL_ERROR_RESPONSE,
            409: API_CODED_ERROR_RESPONSE,
        },
        description=(
            "Reopen a closed ticket through exactly day three (inclusive). The owning resident or "
            "Call Center Staff must provide a nonblank reason and current version. "
            "The report moves to ASSIGNED, records the reason in history, and notifies Call Center Staff."
        ),
    )
    def post(self, request, report_id):
        """POST /api/reports/{id}/reopen/: owner-only reopen with required reason and version."""
        report = _report_for_user(request.user, report_id)
        if request.user.role not in {User.Role.RESIDENT, User.Role.CALL_CENTER_STAFF}:
            return Response(
                {"detail": "Only the requesting resident or Call Center Staff may reopen work."},
                status=status.HTTP_403_FORBIDDEN,
            )
        serializer = ReopenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            updated = reopen_report(
                report_id=report.pk,
                actor=request.user,
                expected_version=serializer.validated_data["version"],
                reason=serializer.validated_data["reason"],
            )
        except ReportConflict as exc:
            return _conflict_response(exc)
        except DjangoValidationError as exc:
            return _validation_response(exc)
        return Response(ReportSerializer(updated).data)


class ReportCommentsAPIView(APIView):
    permission_classes = (IsAuthenticated,)

    @extend_schema(
        operation_id="reports_comments_list",
        parameters=[
            OpenApiParameter("page", int, description="One-based page number."),
            OpenApiParameter("since", int, description="Return comment IDs greater than this non-negative ID, in ascending ID order."),
        ],
        responses={
            200: CommentPageSerializer,
            400: API_DETAIL_ERROR_RESPONSE,
            401: API_DETAIL_ERROR_RESPONSE,
            404: API_DETAIL_ERROR_RESPONSE,
        },
        description=(
            "Return paginated comments for a visible report. Access is restricted to "
            "the report's resident, Call Center Staff, or Technician/Contractor users allowed by the active "
            "assignment scope. Supports `page`."
        ),
    )
    def get(self, request, report_id):
        """GET /api/reports/{id}/comments/: list visible comments, scoped to the report's authorized audience."""
        report = _report_for_user(request.user, report_id)
        comments = Comment.objects.for_user(request.user, report).select_related("author")
        since = request.query_params.get("since")
        if since is not None:
            try:
                since_id = int(since)
                if since_id < 0:
                    raise ValueError
            except ValueError:
                return Response(
                    {"detail": "`since` must be a non-negative comment ID."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            comments = comments.filter(pk__gt=since_id)
            comments = comments.order_by("pk")
        return _page_response(request, comments, CommentSerializer)

    @extend_schema(
        operation_id="reports_comments_create",
        request=CommentCreateSerializer,
        responses={
            201: CommentSerializer,
            400: API_VALIDATION_RESPONSE,
            401: API_DETAIL_ERROR_RESPONSE,
            404: API_DETAIL_ERROR_RESPONSE,
            409: API_CODED_ERROR_RESPONSE,
        },
        description=(
            "Add a public comment to a visible, non-closed report. The author is always "
            "the authenticated user; comment kind and author cannot be supplied by the "
            "client. Closed tickets and unauthorized authors are rejected by the workflow service."
        ),
    )
    def post(self, request, report_id):
        """POST /api/reports/{id}/comments/: create an audited comment as the current user, never as a client-supplied author."""
        report = _report_for_user(request.user, report_id)
        serializer = CommentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            comment = add_comment(
                report_id=report.pk,
                author=request.user,
                body=serializer.validated_data["body"],
            )
        except DjangoValidationError as exc:
            return _validation_response(exc)
        return Response(
            CommentSerializer(comment).data,
            status=status.HTTP_201_CREATED,
        )


class ReportHistoryAPIView(APIView):
    permission_classes = (IsAuthenticated,)

    @extend_schema(
        operation_id="reports_history_list",
        parameters=[OpenApiParameter("page", int, description="One-based page number.")],
        responses={
            200: HistoryPageSerializer,
            401: API_DETAIL_ERROR_RESPONSE,
            404: API_DETAIL_ERROR_RESPONSE,
        },
        description=(
            "Return paginated, append-only status history for a visible report. "
            "Residents, Call Center Staff, and Technician/Contractor users use the "
            "same object-level report "
            "visibility rules. Supports `page`."
        ),
    )
    def get(self, request, report_id):
        """GET /api/reports/{id}/history/: read-only audit trail, available only to users who can see the report."""
        report = _report_for_user(request.user, report_id)
        history = StatusHistory.objects.filter(report=report).select_related(
            "changed_by"
        )
        return _page_response(request, history, HistorySerializer)


class ReportPhotoAPIView(APIView):
    permission_classes = (IsAuthenticated,)

    @extend_schema(
        operation_id="reports_photo_retrieve",
        responses={
            (200, "image/jpeg"): OpenApiTypes.BINARY,
            (200, "image/png"): OpenApiTypes.BINARY,
            401: API_DETAIL_ERROR_RESPONSE,
            404: API_DETAIL_ERROR_RESPONSE,
        },
        description=(
            "Download a photo only when the caller can retrieve the parent report: "
            "residents may access their own report photos, Call Center Staff may access "
            "all report photos, and Technician/Contractor users may access photos only "
            "for reports with their active assignment. Hidden and nonexistent photos return 404."
        ),
    )
    def get(self, request, report_id, photo_id):
        report = _report_for_user(request.user, report_id)
        photo = get_object_or_404(Photo, pk=photo_id, report=report)
        filename = Path(photo.file.name).name
        content_type = (
            "image/jpeg"
            if filename.lower().endswith((".jpg", ".jpeg"))
            else "image/png"
        )
        return FileResponse(
            photo.file.open("rb"),
            as_attachment=True,
            filename=filename,
            content_type=content_type,
        )


class NotificationListAPIView(APIView):
    permission_classes = (IsAuthenticated,)

    @extend_schema(
        operation_id="notifications_list",
        parameters=[
            OpenApiParameter("page", int, description="One-based page number."),
            OpenApiParameter("since", int, description="Return notification IDs greater than this non-negative ID, in ascending ID order."),
        ],
        responses={
            200: NotificationPageSerializer,
            400: API_DETAIL_ERROR_RESPONSE,
            401: API_DETAIL_ERROR_RESPONSE,
        },
        description=(
            "Return only notifications owned by the authenticated user, newest first "
            "without `since`, and ascending by record ID when `since` is supplied. "
            "The response includes the ticket identifier and notification event, not "
            "resident room, contact details, comments, or photos. Supports `page`."
        ),
    )
    def get(self, request):
        """GET /api/notifications/: return only the authenticated user's paginated notification records."""
        notifications = Notification.objects.filter(user=request.user).select_related(
            "report"
        )
        since = request.query_params.get("since")
        if since is not None:
            try:
                since_id = int(since)
                if since_id < 0:
                    raise ValueError
            except ValueError:
                return Response(
                    {"detail": "`since` must be a non-negative notification ID."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            notifications = notifications.filter(pk__gt=since_id)
            notifications = notifications.order_by("pk")
        return _page_response(request, notifications, NotificationSerializer)


class BuildingListAPIView(APIView):
    permission_classes = (IsAuthenticated,)

    @extend_schema(
        operation_id="buildings_list",
        responses={
            200: BuildingSerializer(many=True),
            401: API_DETAIL_ERROR_RESPONSE,
        },
        description="Return active buildings, including their zone, for report-location selectors.",
    )
    def get(self, request):
        return Response(BuildingSerializer(
            Building.objects.filter(is_active=True).order_by("zone", "name"),
            many=True,
        ).data)


class RoomLocationListAPIView(APIView):
    permission_classes = (IsAuthenticated,)

    @extend_schema(
        operation_id="room_locations_list",
        parameters=[
            OpenApiParameter("building", int, description="Filter by active building ID.")
        ],
        responses={
            200: RoomLocationSerializer(many=True),
            400: API_DETAIL_ERROR_RESPONSE,
            401: API_DETAIL_ERROR_RESPONSE,
        },
        description=(
            "Return active seeded dorm-room and village reference codes. Village room "
            "entries are validated against the provisional SV{NN}{UNIT}{ROOM} pattern "
            "on report creation."
        ),
    )
    def get(self, request):
        locations = RoomLocation.objects.filter(is_active=True)
        building_id = request.query_params.get("building")
        if building_id:
            try:
                building = Building.objects.get(pk=building_id, is_active=True)
            except (Building.DoesNotExist, ValueError):
                return Response(
                    {"detail": "Choose an active building."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if building.name.startswith("SV") and building.name[2:].isdigit():
                locations = locations.filter(code=building.name)
            else:
                locations = locations.filter(name=building.name)
        return Response(RoomLocationSerializer(locations.order_by("code"), many=True).data)


class CategoryListAPIView(APIView):
    permission_classes = (IsAuthenticated,)

    @extend_schema(
        operation_id="categories_list",
        responses={
            200: CategoryReferenceSerializer(many=True),
            401: API_DETAIL_ERROR_RESPONSE,
        },
        description="Return active categories and their active subcategories for report forms.",
    )
    def get(self, request):
        categories = Category.objects.filter(is_active=True).order_by("name")
        return Response(CategoryReferenceSerializer(categories, many=True).data)


class UnitListAPIView(APIView):
    permission_classes = (IsAuthenticated,)

    @extend_schema(
        operation_id="units_list",
        responses={
            200: UnitSerializer(many=True),
            401: API_DETAIL_ERROR_RESPONSE,
        },
        description="Return active maintenance units and their internal/contractor kind.",
    )
    def get(self, request):
        units = Unit.objects.filter(is_active=True).order_by("name")
        return Response(UnitSerializer(units, many=True).data)


class UnitResultsAPIView(APIView):
    permission_classes = (IsAuthenticated,)

    @extend_schema(
        operation_id="unit_results",
        parameters=[
            OpenApiParameter(
                "period",
                str,
                enum=("month", "quarter", "year", "all"),
                default="quarter",
                description="Date window used to count completed assignments.",
            )
        ],
        responses={
            200: UnitResultSerializer(many=True),
            400: API_DETAIL_ERROR_RESPONSE,
            401: API_DETAIL_ERROR_RESPONSE,
            403: API_DETAIL_ERROR_RESPONSE,
        },
        description=(
            "Return jobs completed and average work duration for the selected period "
            "(month, quarter, year, or all). Technician/Contractor users see only their "
            "own active unit; Call Center Staff see all active units. No targets, scores, "
            "or rankings are returned."
        ),
    )
    def get(self, request):
        if request.user.role == User.Role.TECHNICIAN_CONTRACTOR:
            units = Unit.objects.filter(pk=request.user.unit_id, is_active=True)
        elif request.user.role == User.Role.CALL_CENTER_STAFF:
            units = Unit.objects.filter(is_active=True)
        else:
            return Response(
                {"detail": "This role may not access unit results."},
                status=status.HTTP_403_FORBIDDEN,
            )
        period = request.query_params.get("period", "quarter")
        days = {"month": 30, "quarter": 90, "year": 365}
        if period not in {*days, "all"}:
            return Response(
                {"detail": "Choose month, quarter, year, or all for period."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        start = timezone.now() - timedelta(days=days[period]) if period != "all" else None
        results = []
        for unit in units.order_by("name"):
            assignments = Assignment.objects.filter(
                unit=unit,
                completed_at__isnull=False,
            )
            if start is not None:
                assignments = assignments.filter(completed_at__gte=start)
            durations = [
                (assignment.completed_at - assignment.started_at).total_seconds()
                for assignment in assignments.filter(started_at__isnull=False).only(
                    "started_at", "completed_at"
                )
            ]
            completed_jobs = assignments.count()
            average_hours = (
                round(sum(durations) / len(durations) / 3600, 2) if durations else None
            )
            results.append({
                # The two measures named in the API specification.
                "unit": unit.name,
                "jobs_completed": completed_jobs,
                "average_hours": average_hours,
                # Longer names kept for existing callers.
                "unit_id": unit.pk,
                "unit_name": unit.name,
                "kind": unit.kind,
                "completed_jobs": completed_jobs,
                "average_completion_hours": average_hours,
                "period": period,
            })
        return Response(results)
