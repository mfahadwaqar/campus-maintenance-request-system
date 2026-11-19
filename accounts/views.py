from datetime import timedelta
from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, redirect_to_login
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Prefetch
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.models import Unit
from assignments.forms import (
    CallCenterQueueFilterForm,
    RejectReportForm,
    ReviewReportForm,
    SetPriorityForm,
)
from assignments.models import Assignment
from reports.forms import CallerReportForm, CommentForm, ReopenReportForm
from reports.models import Comment, Report
from reports.services import (
    ReportConflict,
    assign_technician,
    enter_report_for_caller,
    reject_report,
    reopen_report,
    set_priority,
    start_review,
)

from .models import User


class RoleLoginView(LoginView):
    template_name = "accounts/login.html"

    def get_success_url(self):
        next_url = self.get_redirect_url()
        if next_url and next_url != "/":
            return next_url
        return dashboard_url_for_role(self.request.user.role)


def dashboard_url_for_role(role):
    if role is None:
        return "/admin/"
    dashboards = {
        User.Role.RESIDENT: "accounts:resident_dashboard",
        User.Role.CALL_CENTER_STAFF: "accounts:officer_dashboard",
        User.Role.TECHNICIAN_CONTRACTOR: "accounts:technician_dashboard",
    }
    destination = dashboards.get(role)
    if destination is None:
        raise Http404
    return reverse(destination)


def role_required(role):
    """Restrict a dashboard to an authenticated user with the specified role."""

    def decorator(view_func):
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            if request.user.role != role:
                raise Http404
            return view_func(request, *args, **kwargs)

        return wrapped

    return decorator


def dashboard_redirect(request):
    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())
    return redirect(dashboard_url_for_role(request.user.role))


@role_required(User.Role.RESIDENT)
def resident_dashboard(request):
    return render(request, "accounts/resident_dashboard.html")


@role_required(User.Role.CALL_CENTER_STAFF)
def officer_dashboard(request):
    filter_form = CallCenterQueueFilterForm(request.GET or None)
    reports = Report.objects.for_user(request.user).select_related(
        "resident", "category", "building"
    ).prefetch_related(
        Prefetch(
            "assignments",
            queryset=Assignment.objects.filter(is_active=True).select_related(
                "technician", "unit"
            ),
            to_attr="active_assignments",
        )
    )
    if filter_form.is_valid():
        filters = filter_form.cleaned_data
        for field in ("status", "priority"):
            if filters[field]:
                reports = reports.filter(**{field: filters[field]})
        if filters["category"]:
            reports = reports.filter(category=filters["category"])
        if filters["building"]:
            reports = reports.filter(building=filters["building"])
        if filters["ticket_no"]:
            reports = reports.filter(ticket_no=filters["ticket_no"])
        if filters["student_id"]:
            reports = reports.filter(resident__username=filters["student_id"])
        if filters["room"]:
            reports = reports.filter(room_location__icontains=filters["room"])
        if filters["follow_up"]:
            reports = reports.filter(
                comments__author__role=User.Role.RESIDENT,
                awaiting_call_center_response=True,
            ).distinct()
    elif filter_form.is_bound:
        # A search the form cannot read (for example a ticket number that is too long)
        # must not quietly list every ticket; show no results and the form's error.
        reports = reports.none()

    page = Paginator(reports, 25).get_page(request.GET.get("page"))
    query_params = request.GET.copy()
    query_params.pop("page", None)
    return render(
        request,
        "accounts/officer_dashboard.html",
        {
            "reports": page.object_list,
            "page_obj": page,
            "filter_form": filter_form,
            "filter_query": query_params.urlencode(),
        },
    )


@login_required
def unit_results(request):
    if request.user.role == User.Role.TECHNICIAN_CONTRACTOR:
        units = Unit.objects.filter(pk=request.user.unit_id, is_active=True)
    elif request.user.role == User.Role.CALL_CENTER_STAFF:
        units = Unit.objects.filter(is_active=True)
    else:
        raise Http404

    period = request.GET.get("period", "quarter")
    period_days = {"month": 30, "quarter": 90, "year": 365}
    if period not in {*period_days, "all"}:
        return HttpResponseBadRequest("Choose month, quarter, year, or all for period.")
    start = (
        timezone.now() - timedelta(days=period_days[period])
        if period != "all"
        else None
    )
    unit_rows = []
    for unit in units.order_by("name"):
        assignments = Assignment.objects.filter(
            unit=unit,
            completed_at__isnull=False,
        )
        if start is not None:
            assignments = assignments.filter(completed_at__gte=start)
        durations = [
            assignment.completed_at - assignment.started_at
            for assignment in assignments.filter(started_at__isnull=False).only(
                "started_at", "completed_at"
            )
        ]
        average_seconds = (
            sum(duration.total_seconds() for duration in durations) / len(durations)
            if durations
            else 0
        )
        unit_rows.append(
            {
                "unit": unit,
                "completed_jobs": assignments.count(),
                "average_hours": (
                    round(average_seconds / 3600, 2) if durations else None
                ),
            }
        )

    return render(
        request,
        "accounts/unit_results.html",
        {"unit_rows": unit_rows, "period": period},
    )


def _officer_report_or_404(request, report_id):
    return get_object_or_404(Report.objects.for_user(request.user), pk=report_id)


@role_required(User.Role.CALL_CENTER_STAFF)
def officer_report_detail(request, report_id):
    report = _officer_report_or_404(request, report_id)
    report = (
        Report.objects.filter(pk=report.pk)
        .select_related("resident", "category", "building")
        .prefetch_related(
            "photos",
            "status_history__changed_by",
            Prefetch(
                "assignments",
                queryset=Assignment.objects.select_related(
                    "technician", "assigned_by"
                ),
            ),
        )
        .get()
    )
    context = {"report": report}
    context["comments"] = Comment.objects.for_user(
        request.user, report
    ).select_related("author")
    context["comment_form"] = CommentForm()
    if report.status == Report.Status.SUBMITTED:
        context["review_form"] = ReviewReportForm(report=report)
    elif report.status == Report.Status.UNDER_REVIEW:
        context["priority_form"] = SetPriorityForm(report=report)
        context["reject_form"] = RejectReportForm(report=report)
    elif report.status in (
        Report.Status.ASSIGNED,
        Report.Status.IN_PROGRESS,
        Report.Status.REOPENED,
    ):
        context["assignment_url"] = reverse(
            "assignments:assign_report", args=(report.pk,)
        )
    elif report.status == Report.Status.CLOSED:
        completion = Assignment.objects.filter(
            report=report, completed_at__isnull=False
        ).order_by("-completed_at", "-pk").first()
        if (
            completion
            and timezone.now()
            <= completion.completed_at
            + timedelta(days=settings.REOPEN_WINDOW_DAYS)
        ):
            context["reopen_form"] = ReopenReportForm(report=report)
    return render(request, "reports/officer_report_detail.html", context)


@role_required(User.Role.CALL_CENTER_STAFF)
@require_POST
def begin_report_review(request, report_id):
    report = _officer_report_or_404(request, report_id)
    form = ReviewReportForm(request.POST, report=report)
    if not form.is_valid():
        messages.error(request, "Refresh the request and try again.")
        return redirect("accounts:officer_dashboard")

    try:
        start_review(
            report_id=report.pk,
            actor=request.user,
            expected_version=form.cleaned_data["version"],
            room_verified=form.cleaned_data["room_verified"],
        )
    except ReportConflict as exc:
        messages.error(request, str(exc))
        return redirect("accounts:officer_dashboard")
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
    return redirect("accounts:officer_dashboard")


@role_required(User.Role.CALL_CENTER_STAFF)
@require_POST
def update_report_priority(request, report_id):
    report = _officer_report_or_404(request, report_id)
    form = SetPriorityForm(request.POST, report=report)
    if not form.is_valid():
        messages.error(request, "Correct the priority form and try again.")
        return redirect("accounts:officer_report_detail", report_id=report_id)
    try:
        set_priority(
            report_id=report.pk,
            priority=form.cleaned_data["priority"],
            actor=request.user,
            expected_version=form.cleaned_data["version"],
        )
        messages.success(request, "Priority updated.")
    except (ValidationError, ReportConflict) as exc:
        messages.error(
            request, "; ".join(exc.messages) if isinstance(exc, ValidationError) else str(exc)
        )
    return redirect("accounts:officer_report_detail", report_id=report_id)


@role_required(User.Role.CALL_CENTER_STAFF)
@require_POST
def reject_report_view(request, report_id):
    report = _officer_report_or_404(request, report_id)
    form = RejectReportForm(request.POST, report=report)
    if not form.is_valid():
        messages.error(request, "A rejection reason is required.")
        return redirect("accounts:officer_report_detail", report_id=report_id)
    try:
        reject_report(
            report_id=report.pk,
            reason=form.cleaned_data["reason"],
            actor=request.user,
            expected_version=form.cleaned_data["version"],
        )
        messages.success(request, "Request rejected.")
    except (ValidationError, ReportConflict) as exc:
        messages.error(
            request, "; ".join(exc.messages) if isinstance(exc, ValidationError) else str(exc)
        )
    return redirect("accounts:officer_report_detail", report_id=report_id)


@role_required(User.Role.CALL_CENTER_STAFF)
@require_POST
def officer_reopen_report(request, report_id):
    report = _officer_report_or_404(request, report_id)
    form = ReopenReportForm(request.POST, report=report)
    if not form.is_valid():
        messages.error(request, "Provide a reason and refresh before reopening.")
        return redirect("accounts:officer_report_detail", report_id=report_id)
    try:
        reopen_report(
            report_id=report.pk,
            actor=request.user,
            expected_version=form.cleaned_data["version"],
            reason=form.cleaned_data["reason"],
        )
        messages.success(request, "The ticket was reopened for reassignment.")
    except (ValidationError, ReportConflict) as exc:
        messages.error(
            request,
            "; ".join(exc.messages) if isinstance(exc, ValidationError) else str(exc),
        )
    return redirect("accounts:officer_report_detail", report_id=report_id)


@role_required(User.Role.TECHNICIAN_CONTRACTOR)
def technician_dashboard(request):
    reports = (
        Report.objects.for_user(request.user)
        .filter(assignments__technician=request.user, assignments__is_active=True)
        .select_related("resident", "category", "building")
        .distinct()
    )
    return render(
        request, "accounts/technician_dashboard.html", {"reports": reports}
    )


@role_required(User.Role.CALL_CENTER_STAFF)
def officer_create_report(request):
    """Enter a request received by phone, email or walk-in, optionally assigning it at once."""

    form = CallerReportForm(
        request.POST if request.method == "POST" else None,
        request.FILES if request.method == "POST" else None,
    )
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            with transaction.atomic():
                report = enter_report_for_caller(
                    resident=data["resident"],
                    submitted_by=request.user,
                    channel=data["channel"],
                    category=data["category"],
                    subcategory=data.get("subcategory"),
                    building=data["building"],
                    room_location=data["room_location"],
                    title=data["title"],
                    description=data["description"],
                    requested_urgency=data["requested_urgency"],
                    room_verified=data["room_verified"],
                    photo=data.get("photo"),
                )
                if data.get("unit"):
                    report = assign_technician(
                        report_id=report.pk,
                        technician=data.get("technician"),
                        assigned_by=request.user,
                        priority=data.get("priority") or None,
                        expected_version=report.version,
                        unit=data["unit"],
                    )
        except ValidationError as exc:
            form.add_error(None, exc)
        except (IntegrityError, ReportConflict):
            form.add_error(None, "The request could not be saved. Check the details and try again.")
        else:
            if data.get("unit"):
                messages.success(
                    request,
                    f"Ticket {report.ticket_no} was created and assigned to {data['unit'].name}.",
                )
            else:
                messages.success(request, f"Ticket {report.ticket_no} was created.")
            return redirect("accounts:officer_report_detail", report_id=report.pk)
    return render(request, "accounts/officer_create_report.html", {"form": form})
