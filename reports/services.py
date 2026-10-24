from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from accounts.models import User
from assignments.models import Assignment, TechnicianSpecialization
from notifications.services import queue_report_notifications
from .models import Comment, Photo, Report, StatusHistory, Verification


class ReportConflict(Exception):
    """Raised when a report changed since the officer opened its action form."""


@dataclass(frozen=True)
class TransitionRule:
    actor_role: str
    required_fields: tuple[str, ...] = ()


TRANSITION_TABLE = {
    (None, Report.Status.SUBMITTED): TransitionRule(User.Role.RESIDENT, ("valid_form",)),
    (Report.Status.SUBMITTED, Report.Status.UNDER_REVIEW): TransitionRule(
        User.Role.OFFICER
    ),
    (Report.Status.UNDER_REVIEW, Report.Status.ASSIGNED): TransitionRule(
        User.Role.OFFICER, ("priority", "technician")
    ),
    (Report.Status.UNDER_REVIEW, Report.Status.REJECTED): TransitionRule(
        User.Role.OFFICER, ("reason",)
    ),
    (Report.Status.UNDER_REVIEW, Report.Status.MERGED): TransitionRule(
        User.Role.OFFICER, ("master_report",)
    ),
    (Report.Status.ASSIGNED, Report.Status.ASSIGNED): TransitionRule(
        User.Role.OFFICER, ("technician",)
    ),
    (Report.Status.IN_PROGRESS, Report.Status.ASSIGNED): TransitionRule(
        User.Role.OFFICER, ("technician",)
    ),
    (Report.Status.ASSIGNED, Report.Status.IN_PROGRESS): TransitionRule(
        User.Role.TECHNICIAN
    ),
    (Report.Status.IN_PROGRESS, Report.Status.COMPLETED): TransitionRule(
        User.Role.TECHNICIAN, ("completion_notes",)
    ),
    (Report.Status.COMPLETED, Report.Status.CLOSED): TransitionRule(
        User.Role.RESIDENT, ("rating",)
    ),
    (Report.Status.COMPLETED, Report.Status.REOPENED): TransitionRule(
        User.Role.RESIDENT, ("reason",)
    ),
    (Report.Status.REOPENED, Report.Status.ASSIGNED): TransitionRule(
        User.Role.OFFICER, ("technician",)
    ),
}


def _validate_transition(old_status, new_status, actor, values):
    """Enforce the workflow's allowed actor and required data for a transition."""

    rule = TRANSITION_TABLE.get((old_status, new_status))
    if rule is None:
        raise ValidationError(
            f"The transition from {old_status or 'new'} to {new_status} is not allowed."
        )
    if not actor.is_authenticated or actor.role != rule.actor_role:
        raise ValidationError(f"Only a {rule.actor_role.lower()} may perform this transition.")
    missing = [
        field
        for field in rule.required_fields
        if field not in values or values[field] in (None, "", False)
    ]
    if missing:
        raise ValidationError(
            "Required transition data is missing: " + ", ".join(missing) + "."
        )
    return rule


def transition_report(*, report: Report, new_status: str, actor: User, **values):
    """Lock, validate, and record one report transition in a single transaction."""

    expected_version = values.pop("expected_version", None)
    note = values.pop("note", "")
    technician = values.get("technician")
    priority = values.get("priority")
    master_report = values.get("master_report")
    completion_notes = values.get("completion_notes")
    resident_report_id = values.pop("resident_report_id", None)
    end_reason = values.get("end_reason", "Reassigned by officer")
    update_fields = {"status", "version", "updated_at"}

    with transaction.atomic():
        locked_report = Report.objects.select_for_update().get(pk=report.pk)
        if expected_version is None or locked_report.version != expected_version:
            raise ReportConflict("This request changed. Refresh and try again.")

        _validate_transition(locked_report.status, new_status, actor, values)
        old_status = locked_report.status

        if new_status in (Report.Status.CLOSED, Report.Status.REOPENED):
            if resident_report_id is None:
                resident_report_id = locked_report.pk
            resident_owns_target = (
                resident_report_id == locked_report.pk
                and locked_report.resident_id == actor.pk
            )
            resident_owns_duplicate = Report.objects.filter(
                pk=resident_report_id,
                resident=actor,
                merged_into=locked_report,
            ).exists()
            if not (resident_owns_target or resident_owns_duplicate):
                raise ValidationError(
                    "Only the requesting resident may verify or reopen this report."
                )

        if new_status in (
            Report.Status.IN_PROGRESS,
            Report.Status.COMPLETED,
        ):
            active_assignment = (
                Assignment.objects.select_for_update()
                .filter(
                    report=locked_report,
                    technician=actor,
                    is_active=True,
                )
                .first()
            )
            if active_assignment is None:
                raise ValidationError(
                    "Only the assigned technician may update this report."
                )

        if new_status == Report.Status.ASSIGNED:
            if technician.role != User.Role.TECHNICIAN:
                raise ValidationError("Choose an active technician account.")
            if not technician.is_active:
                raise ValidationError("The selected technician account is inactive.")
            if old_status == Report.Status.UNDER_REVIEW and (
                not priority
                or priority not in dict(Report._meta.get_field("priority").choices)
            ):
                raise ValidationError("Choose a valid priority before assigning.")

            try:
                with transaction.atomic():
                    Assignment.objects.filter(
                        report=locked_report, is_active=True
                    ).update(
                        is_active=False,
                        ended_at=timezone.now(),
                        end_reason=end_reason,
                    )
                    Assignment.objects.create(
                        report=locked_report,
                        technician=technician,
                        assigned_by=actor,
                    )
            except IntegrityError as exc:
                raise ReportConflict(
                    "Another officer updated this assignment. Refresh and try again."
                ) from exc

            if priority:
                locked_report.priority = priority
                update_fields.add("priority")
            matching = TechnicianSpecialization.objects.filter(
                technician=technician, category=locked_report.category
            ).exists()
            if not matching:
                note = f"{note}. Technician specialization does not match the report category."

        if new_status == Report.Status.MERGED:
            if master_report.pk == locked_report.pk:
                raise ValidationError("A report cannot be merged into itself.")
            master = Report.objects.select_for_update().get(pk=master_report.pk)
            if master.status in (Report.Status.MERGED, Report.Status.REJECTED):
                raise ValidationError(
                    "The master report must not be merged or rejected."
                )
            locked_report.merged_into = master
            update_fields.add("merged_into")

        if new_status == Report.Status.REJECTED:
            note = values["reason"]

        if new_status == Report.Status.COMPLETED:
            note = completion_notes.strip()
            Assignment.objects.filter(
                report=locked_report,
                technician=actor,
                is_active=True,
            ).update(
                is_active=False,
                ended_at=timezone.now(),
                end_reason="Work completed",
            )

        locked_report.status = new_status
        locked_report.version += 1
        locked_report.save(update_fields=tuple(update_fields))
        StatusHistory.objects.create(
            report=locked_report,
            old_status=old_status,
            new_status=new_status,
            changed_by=actor,
            note=note,
        )
        if new_status == Report.Status.ASSIGNED:
            queue_report_notifications(
                locked_report,
                event="was assigned to a technician",
                recipients=(locked_report.resident, technician),
            )
        elif new_status == Report.Status.REOPENED:
            officers = User.objects.filter(role=User.Role.OFFICER, is_active=True)
            queue_report_notifications(
                locked_report,
                event="was reopened",
                recipients=officers,
            )
        elif new_status == Report.Status.MERGED:
            queue_report_notifications(
                locked_report,
                event="was marked as a duplicate",
                recipients=(locked_report.resident,),
            )
        else:
            event_text = {
                Report.Status.UNDER_REVIEW: "is under review",
                Report.Status.IN_PROGRESS: "has work in progress",
                Report.Status.COMPLETED: "is complete and ready for verification",
                Report.Status.CLOSED: "was verified and closed",
                Report.Status.REJECTED: "was rejected",
            }.get(new_status)
            if event_text:
                queue_report_notifications(
                    locked_report,
                    event=event_text,
                    recipients=(locked_report.resident,),
                )

    return locked_report


def start_review(*, report_id: int, actor: User, expected_version: int) -> Report:
    """Move a submitted report into officer review."""

    report = Report.objects.get(pk=report_id)
    return transition_report(
        report=report,
        new_status=Report.Status.UNDER_REVIEW,
        actor=actor,
        expected_version=expected_version,
        note="Review started",
    )


def set_priority(
    *, report_id: int, priority: str, actor: User, expected_version: int
) -> Report:
    """Set an officer priority while the report is under review."""

    if not priority or priority not in dict(Report._meta.get_field("priority").choices):
        raise ValidationError("Choose a valid priority.")
    with transaction.atomic():
        report = Report.objects.select_for_update().get(pk=report_id)
        if report.version != expected_version:
            raise ReportConflict("This request changed. Refresh and try again.")
        if not actor.is_authenticated or actor.role != User.Role.OFFICER:
            raise ValidationError("Only an officer may set priority.")
        if report.status != Report.Status.UNDER_REVIEW:
            raise ValidationError("Priority can only be set while under review.")
        old_priority = report.priority
        report.priority = priority
        report.version += 1
        report.save(update_fields=("priority", "version", "updated_at"))
        StatusHistory.objects.create(
            report=report,
            old_status=report.status,
            new_status=report.status,
            changed_by=actor,
            note=f"Priority changed from {old_priority or 'unset'} to {priority}",
        )
    return report


def reject_report(
    *, report_id: int, reason: str, actor: User, expected_version: int
) -> Report:
    """Reject an under-review report with a mandatory reason."""

    reason = reason.strip()
    if not reason:
        raise ValidationError("A rejection reason is required.")
    report = Report.objects.get(pk=report_id)
    return transition_report(
        report=report,
        new_status=Report.Status.REJECTED,
        actor=actor,
        expected_version=expected_version,
        reason=reason,
    )


def mark_duplicate(
    *,
    report_id: int,
    master_report_id: int,
    actor: User,
    expected_version: int,
) -> Report:
    """Mark an under-review report as a duplicate while retaining its history."""

    master_report = Report.objects.get(pk=master_report_id)
    report = Report.objects.get(pk=report_id)
    return transition_report(
        report=report,
        new_status=Report.Status.MERGED,
        actor=actor,
        expected_version=expected_version,
        master_report=master_report,
        note=f"Marked duplicate of report #{master_report_id}",
    )


def assign_technician(
    *,
    report_id: int,
    technician: User,
    assigned_by: User,
    priority: str | None,
    expected_version: int,
) -> Report:
    """Assign or reassign a technician using a locked, version-checked transition."""

    report = Report.objects.get(pk=report_id)
    return transition_report(
        report=report,
        new_status=Report.Status.ASSIGNED,
        actor=assigned_by,
        expected_version=expected_version,
        technician=technician,
        priority=priority,
        end_reason="Reassigned by officer",
        note="Technician assigned",
    )


def start_work(*, report_id: int, technician: User, expected_version: int) -> Report:
    """Start work on an active assignment using the shared transition service."""

    report = Report.objects.get(pk=report_id)
    return transition_report(
        report=report,
        new_status=Report.Status.IN_PROGRESS,
        actor=technician,
        expected_version=expected_version,
        note="Work started",
    )


@transaction.atomic
def complete_work(
    *,
    report_id: int,
    technician: User,
    expected_version: int,
    completion_notes: str,
    photo=None,
) -> Report:
    """Complete assigned work with notes and an optional processed photo."""

    completion_notes = completion_notes.strip()
    if not completion_notes:
        raise ValidationError("Completion notes are required.")
    report = Report.objects.get(pk=report_id)
    completed_report = transition_report(
        report=report,
        new_status=Report.Status.COMPLETED,
        actor=technician,
        expected_version=expected_version,
        completion_notes=completion_notes,
    )
    if photo is not None:
        Photo.objects.create(
            report=completed_report,
            uploaded_by=technician,
            stage=Photo.Stage.COMPLETION,
            file=photo,
        )
    return completed_report


@transaction.atomic
def verify_report(
    *,
    report_id: int,
    resident: User,
    expected_version: int,
    rating: int,
    comment: str = "",
) -> Report:
    """Verify completed work and preserve the resident's rating."""

    if not resident.is_authenticated or resident.role != User.Role.RESIDENT:
        raise ValidationError("Only the requesting resident may verify this report.")
    if not isinstance(rating, int) or not 1 <= rating <= 5:
        raise ValidationError("Rating must be a whole number from 1 to 5.")
    report = Report.objects.select_for_update().get(pk=report_id)
    if report.resident_id != resident.pk:
        raise ValidationError("Only the requesting resident may verify this report.")
    closed_report = transition_report(
        report=report,
        new_status=Report.Status.CLOSED,
        actor=resident,
        expected_version=expected_version,
        rating=rating,
        note="Resident verified completed work",
    )
    Verification.objects.create(
        report=closed_report,
        resident=resident,
        outcome=Verification.Outcome.VERIFIED,
        rating=rating,
        comment=comment.strip(),
    )
    return closed_report


@transaction.atomic
def reopen_report(
    *,
    report_id: int,
    resident: User,
    expected_version: int,
    reason: str,
) -> Report:
    """Record a resident reopen and return merged reports to their master queue."""

    reason = reason.strip()
    if not reason:
        raise ValidationError("A reopen reason is required.")
    if not resident.is_authenticated or resident.role != User.Role.RESIDENT:
        raise ValidationError("Only the requesting resident may reopen this report.")

    source_report = Report.objects.select_for_update().get(pk=report_id)
    if source_report.resident_id != resident.pk:
        raise ValidationError("Only the requesting resident may reopen this report.")
    if source_report.version != expected_version:
        raise ReportConflict("This request changed. Refresh and try again.")

    if source_report.merged_into_id:
        master = Report.objects.select_for_update().get(
            pk=source_report.merged_into_id
        )
        if master.status != Report.Status.COMPLETED:
            raise ValidationError("The master report is not awaiting verification.")
        reopened = transition_report(
            report=master,
            new_status=Report.Status.REOPENED,
            actor=resident,
            expected_version=master.version,
            resident_report_id=source_report.pk,
            reason=reason,
            note=f"Linked request #{source_report.pk} reopened: {reason}",
        )
    else:
        reopened = transition_report(
            report=source_report,
            new_status=Report.Status.REOPENED,
            actor=resident,
            expected_version=expected_version,
            reason=reason,
            note=reason,
        )

    Verification.objects.create(
        report=source_report,
        resident=resident,
        outcome=Verification.Outcome.REOPENED,
        rating=None,
        comment=reason,
    )
    return reopened


@transaction.atomic
def add_comment(
    *, report_id: int, author: User, body: str, is_internal: bool = False
) -> Comment:
    """Create a comment only when the author may participate in the report."""

    body = body.strip()
    if not body:
        raise ValidationError("Comment text is required.")
    report = Report.objects.select_for_update().get(pk=report_id)
    if not Report.objects.for_user(author).filter(pk=report.pk).exists():
        raise ValidationError("You may not comment on this report.")
    if is_internal and author.role not in (User.Role.OFFICER, User.Role.TECHNICIAN):
        raise ValidationError("Only officers and technicians may add internal comments.")
    return Comment.objects.create(
        report=report,
        author=author,
        body=body,
        is_internal=is_internal,
    )


@transaction.atomic
def submit_report(
    *,
    resident: User,
    category,
    building,
    room_location: str,
    title: str,
    description: str,
    requested_urgency: str,
    photo=None,
) -> Report:
    """Create a submitted report and its initial history row atomically."""

    _validate_transition(
        None, Report.Status.SUBMITTED, resident, {"valid_form": True}
    )
    report = Report(
        resident=resident,
        category=category,
        building=building,
        room_location=room_location,
        title=title,
        description=description,
        requested_urgency=requested_urgency,
        status=Report.Status.SUBMITTED,
    )
    report.full_clean()
    report.save()
    if photo is not None:
        Photo.objects.create(
            report=report,
            uploaded_by=resident,
            stage=Photo.Stage.REPORT,
            file=photo,
        )
    StatusHistory.objects.create(
        report=report,
        old_status="",
        new_status=Report.Status.SUBMITTED,
        changed_by=resident,
        note="Report submitted",
    )
    queue_report_notifications(
        report,
        event="was submitted",
        recipients=User.objects.filter(role=User.Role.OFFICER, is_active=True),
    )
    return report
