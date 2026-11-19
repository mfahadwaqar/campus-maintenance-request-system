from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from accounts.models import User
from reports.forms import CommentForm, CompletionForm, HoldForm
from reports.models import Comment, Report
from reports.services import (
    ReportConflict,
    assign_technician,
    complete_work,
    put_on_hold,
    start_work,
)

from .forms import AssignTechnicianForm


def _officer_report_or_404(user, report_id):
    if user.role != User.Role.CALL_CENTER_STAFF:
        raise Http404
    return get_object_or_404(Report.objects.for_user(user), pk=report_id)


@login_required
@require_http_methods(["GET", "POST"])
def assign_report(request, report_id):
    report = _officer_report_or_404(request.user, report_id)
    assignable_statuses = {
        Report.Status.UNDER_REVIEW,
        Report.Status.ASSIGNED,
        Report.Status.IN_PROGRESS,
        Report.Status.REOPENED,
    }
    if report.status not in assignable_statuses:
        raise Http404

    form = AssignTechnicianForm(
        request.POST if request.method == "POST" else None,
        report=report,
    )
    if request.method == "POST" and form.is_valid():
        try:
            assign_technician(
                report_id=report.pk,
                technician=form.cleaned_data["technician"],
                assigned_by=request.user,
                priority=form.cleaned_data["priority"],
                expected_version=form.cleaned_data["version"],
                unit=form.cleaned_data["unit"],
            )
        except ReportConflict as exc:
            response = render(
                request,
                "assignments/assign_form.html",
                {"form": form, "report": report, "conflict_message": str(exc)},
                status=409,
            )
            return response
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, f"Request #{report.pk} assigned successfully.")
            return redirect("accounts:officer_dashboard")

    return render(
        request, "assignments/assign_form.html", {"form": form, "report": report}
    )


def _assigned_report_or_404(user, report_id):
    if user.role != User.Role.TECHNICIAN_CONTRACTOR:
        raise Http404
    return get_object_or_404(
        Report.objects.for_user(user).filter(
            assignments__technician=user,
            assignments__is_active=True,
        ),
        pk=report_id,
    )


def _technician_detail_context(user, report, completion_form=None, hold_form=None):
    return {
        "report": report,
        "completion_form": completion_form
        or (
            CompletionForm(report=report)
            if report.status == Report.Status.IN_PROGRESS
            else None
        ),
        "version": report.version,
        "comments": Comment.objects.for_user(user, report).select_related("author"),
        "comment_form": CommentForm(),
        "hold_form": hold_form
        or (
            HoldForm(report=report)
            if report.status in {Report.Status.ASSIGNED, Report.Status.IN_PROGRESS}
            else None
        ),
    }


@login_required
def technician_report_detail(request, report_id):
    report = _assigned_report_or_404(request.user, report_id)
    report = get_object_or_404(
        Report.objects.for_user(request.user)
        .filter(assignments__technician=request.user, assignments__is_active=True)
        .select_related("resident", "category", "building")
        .prefetch_related("photos", "status_history__changed_by"),
        pk=report.pk,
    )
    return render(
        request,
        "assignments/technician_report_detail.html",
        _technician_detail_context(request.user, report),
    )


@login_required
@require_POST
def start_work_view(request, report_id):
    report = _assigned_report_or_404(request.user, report_id)
    try:
        version = int(request.POST.get("version", ""))
        start_work(
            report_id=report.pk,
            technician=request.user,
            expected_version=version,
        )
        messages.success(request, "Work started.")
    except (ValueError, ReportConflict) as exc:
        messages.error(request, str(exc) or "Refresh the request and try again.")
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
    return redirect("assignments:technician_report_detail", report_id=report.pk)


@login_required
@require_POST
def complete_work_view(request, report_id):
    report = _assigned_report_or_404(request.user, report_id)
    form = CompletionForm(request.POST, request.FILES, report=report)
    if not form.is_valid():
        return render(
            request,
            "assignments/technician_report_detail.html",
            _technician_detail_context(request.user, report, form),
        )
    try:
        complete_work(
            report_id=report.pk,
            technician=request.user,
            expected_version=form.cleaned_data["version"],
            completion_notes=form.cleaned_data["completion_notes"],
            photo=form.cleaned_data.get("photo"),
            requester_signed_on_site=form.cleaned_data["requester_signed_on_site"],
        )
        messages.success(request, "Work marked as completed.")
    except ReportConflict as exc:
        messages.error(request, str(exc))
        return render(
            request,
            "assignments/technician_report_detail.html",
            _technician_detail_context(request.user, report, form),
            status=409,
        )
    except ValidationError as exc:
        form.add_error(None, exc)
        return render(
            request,
            "assignments/technician_report_detail.html",
            _technician_detail_context(request.user, report, form),
        )
    return redirect("accounts:technician_dashboard")


@login_required
@require_POST
def put_on_hold_view(request, report_id):
    report = _assigned_report_or_404(request.user, report_id)
    form = HoldForm(request.POST, report=report)
    if not form.is_valid():
        return render(
            request,
            "assignments/technician_report_detail.html",
            _technician_detail_context(request.user, report, hold_form=form),
        )
    try:
        put_on_hold(
            report_id=report.pk,
            technician=request.user,
            expected_version=form.cleaned_data["version"],
            reason=form.cleaned_data["reason"],
            expected_date=form.cleaned_data["expected_date"],
        )
        messages.success(request, "Work put on hold; the resident was notified.")
    except ReportConflict as exc:
        messages.error(request, str(exc))
        return render(
            request,
            "assignments/technician_report_detail.html",
            _technician_detail_context(request.user, report, hold_form=form),
            status=409,
        )
    except ValidationError as exc:
        form.add_error(None, exc)
        return render(
            request,
            "assignments/technician_report_detail.html",
            _technician_detail_context(request.user, report, hold_form=form),
        )
    return redirect("accounts:technician_dashboard")
