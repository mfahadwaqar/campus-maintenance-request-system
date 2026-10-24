from functools import wraps

from django.contrib import messages
from django.contrib.auth.views import LoginView, redirect_to_login
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Prefetch
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from assignments.forms import (
    DuplicateReportForm,
    OfficerQueueFilterForm,
    RejectReportForm,
    ReviewReportForm,
    SetPriorityForm,
)
from assignments.models import Assignment
from reports.forms import CommentForm
from reports.models import Comment, Report
from reports.services import (
    ReportConflict,
    mark_duplicate,
    reject_report,
    set_priority,
    start_review,
)
from .models import User


class RoleLoginView(LoginView):
    template_name = "accounts/login.html"

    def get_success_url(self):
        return dashboard_url_for_role(self.request.user.role)


def dashboard_url_for_role(role):
    dashboards = {
        User.Role.RESIDENT: "accounts:resident_dashboard",
        User.Role.OFFICER: "accounts:officer_dashboard",
        User.Role.TECHNICIAN: "accounts:technician_dashboard",
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


@role_required(User.Role.OFFICER)
def officer_dashboard(request):
    filter_form = OfficerQueueFilterForm(request.GET or None)
    reports = Report.objects.for_user(request.user).select_related(
        "resident", "category", "building"
    ).prefetch_related(
        Prefetch(
            "assignments",
            queryset=Assignment.objects.filter(is_active=True).select_related(
                "technician"
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


def _officer_report_or_404(request, report_id):
    return get_object_or_404(Report.objects.for_user(request.user), pk=report_id)


@role_required(User.Role.OFFICER)
def officer_report_detail(request, report_id):
    report = _officer_report_or_404(request, report_id)
    report = (
        Report.objects.filter(pk=report.pk)
        .select_related("resident", "category", "building", "merged_into")
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
    context["comment_form"] = CommentForm(allow_internal=True)
    if report.status == Report.Status.SUBMITTED:
        context["review_form"] = ReviewReportForm(report=report)
    elif report.status == Report.Status.UNDER_REVIEW:
        context["priority_form"] = SetPriorityForm(report=report)
        context["reject_form"] = RejectReportForm(report=report)
        context["duplicate_form"] = DuplicateReportForm(report=report)
    elif report.status in (
        Report.Status.ASSIGNED,
        Report.Status.IN_PROGRESS,
        Report.Status.REOPENED,
    ):
        context["assignment_url"] = reverse(
            "assignments:assign_report", args=(report.pk,)
        )
    return render(request, "reports/officer_report_detail.html", context)


@role_required(User.Role.OFFICER)
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
        )
    except ReportConflict as exc:
        messages.error(request, str(exc))
        return redirect("accounts:officer_dashboard")
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
    return redirect("accounts:officer_dashboard")


@role_required(User.Role.OFFICER)
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


@role_required(User.Role.OFFICER)
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


@role_required(User.Role.OFFICER)
@require_POST
def mark_duplicate_view(request, report_id):
    report = _officer_report_or_404(request, report_id)
    form = DuplicateReportForm(request.POST, report=report)
    if not form.is_valid():
        messages.error(request, "Choose a valid master report.")
        return redirect("accounts:officer_report_detail", report_id=report_id)
    try:
        mark_duplicate(
            report_id=report.pk,
            master_report_id=form.cleaned_data["master_report"].pk,
            actor=request.user,
            expected_version=form.cleaned_data["version"],
        )
        messages.success(request, "Request marked as a duplicate.")
    except (ValidationError, ReportConflict) as exc:
        messages.error(
            request, "; ".join(exc.messages) if isinstance(exc, ValidationError) else str(exc)
        )
    return redirect("accounts:officer_report_detail", report_id=report_id)


@role_required(User.Role.TECHNICIAN)
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
