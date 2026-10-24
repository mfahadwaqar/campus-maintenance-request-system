from pathlib import Path

from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.models import User
from .forms import (
    CommentForm,
    ReopenReportForm,
    ReportSubmissionForm,
    VerificationForm,
)
from .models import Comment, Photo, Report
from .services import (
    ReportConflict,
    add_comment,
    reopen_report,
    submit_report,
    verify_report,
)


@login_required
def report_list(request):
    reports = Report.objects.for_user(request.user).select_related(
        "resident", "category", "building"
    )
    return render(request, "reports/report_list.html", {"reports": reports})


@login_required
def report_detail(request, report_id):
    report = get_object_or_404(
        Report.objects.for_user(request.user)
        .select_related("resident", "category", "building")
        .prefetch_related("photos", "status_history"),
        pk=report_id,
    )
    comments = Comment.objects.for_user(request.user, report).select_related("author")
    context = {"report": report, "comments": comments}
    if request.user.role == User.Role.RESIDENT and report.resident_id == request.user.pk:
        if report.status == Report.Status.COMPLETED:
            context["verification_form"] = VerificationForm(report=report)
            context["reopen_form"] = ReopenReportForm(report=report)
        elif report.merged_into_id and report.merged_into.status == Report.Status.COMPLETED:
            context["reopen_form"] = ReopenReportForm(report=report)
    if (
        request.user.role == User.Role.RESIDENT
        and report.merged_into_id
    ):
        master = report.merged_into
        context["master_summary"] = {
            "id": master.pk,
            "status": master.get_status_display(),
        }
    context["comment_form"] = CommentForm(
        allow_internal=request.user.role in (User.Role.OFFICER, User.Role.TECHNICIAN)
    )
    return render(request, "reports/report_detail.html", context)


@login_required
def report_history(request, report_id):
    report = get_object_or_404(
        Report.objects.for_user(request.user)
        .select_related("resident")
        .prefetch_related("status_history__changed_by"),
        pk=report_id,
    )
    return render(request, "reports/report_history.html", {"report": report})


@login_required
@require_POST
def verify_report_view(request, report_id):
    report = get_object_or_404(
        Report.objects.filter(resident=request.user), pk=report_id
    )
    form = VerificationForm(request.POST, report=report)
    if form.is_valid():
        try:
            verify_report(
                report_id=report.pk,
                resident=request.user,
                expected_version=form.cleaned_data["version"],
                rating=form.cleaned_data["rating"],
                comment=form.cleaned_data["comment"],
            )
            messages.success(request, "You verified this completed request.")
        except (ValidationError, ReportConflict) as exc:
            messages.error(
                request,
                "; ".join(exc.messages)
                if isinstance(exc, ValidationError)
                else str(exc),
            )
    else:
        messages.error(request, "Correct the verification form and try again.")
    return redirect("reports:detail", report_id=report.pk)


@login_required
@require_POST
def reopen_report_view(request, report_id):
    report = get_object_or_404(
        Report.objects.filter(resident=request.user), pk=report_id
    )
    form = ReopenReportForm(request.POST, report=report)
    if form.is_valid():
        try:
            reopened = reopen_report(
                report_id=report.pk,
                resident=request.user,
                expected_version=form.cleaned_data["version"],
                reason=form.cleaned_data["reason"],
            )
            messages.success(
                request, f"Request #{reopened.pk} was sent back for officer review."
            )
        except (ValidationError, ReportConflict) as exc:
            messages.error(
                request,
                "; ".join(exc.messages)
                if isinstance(exc, ValidationError)
                else str(exc),
            )
    else:
        messages.error(request, "A reason is required to reopen a request.")
    return redirect("reports:detail", report_id=report.pk)


@login_required
def report_comments(request, report_id):
    report = get_object_or_404(Report.objects.for_user(request.user), pk=report_id)
    if request.method == "POST":
        form = CommentForm(
            request.POST,
            allow_internal=request.user.role
            in (User.Role.OFFICER, User.Role.TECHNICIAN),
        )
        if form.is_valid():
            try:
                add_comment(
                    report_id=report.pk,
                    author=request.user,
                    body=form.cleaned_data["body"],
                    is_internal=form.cleaned_data.get("is_internal", False),
                )
                messages.success(request, "Comment added.")
            except ValidationError as exc:
                messages.error(request, "; ".join(exc.messages))
        else:
            messages.error(request, "Comment text is required.")
        return redirect("reports:detail", report_id=report.pk)
    comments = Comment.objects.for_user(request.user, report).select_related("author")
    return render(
        request,
        "reports/comments.html",
        {
            "report": report,
            "comments": comments,
            "comment_form": CommentForm(
                allow_internal=request.user.role
                in (User.Role.OFFICER, User.Role.TECHNICIAN)
            ),
        },
    )


@login_required
def report_create(request):
    if request.user.role != User.Role.RESIDENT:
        raise Http404

    form = ReportSubmissionForm(
        request.POST if request.method == "POST" else None,
        request.FILES if request.method == "POST" else None,
    )
    if request.method == "POST" and form.is_valid():
        report = submit_report(
            resident=request.user,
            category=form.cleaned_data["category"],
            building=form.cleaned_data["building"],
            room_location=form.cleaned_data["room_location"],
            title=form.cleaned_data["title"],
            description=form.cleaned_data["description"],
            requested_urgency=form.cleaned_data["requested_urgency"],
            photo=form.cleaned_data.get("photo"),
        )
        return redirect("reports:detail", report_id=report.pk)

    return render(request, "reports/report_form.html", {"form": form})


@login_required
def photo_download(request, report_id, photo_id):
    report = get_object_or_404(Report.objects.for_user(request.user), pk=report_id)
    photo = get_object_or_404(Photo, pk=photo_id, report=report)
    filename = Path(photo.file.name).name
    content_type = "image/jpeg" if filename.lower().endswith((".jpg", ".jpeg")) else "image/png"
    return FileResponse(
        photo.file.open("rb"),
        as_attachment=True,
        filename=filename,
        content_type=content_type,
    )
