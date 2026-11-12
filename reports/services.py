from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.conf import settings
from django.core.files.storage import default_storage
from django.db import IntegrityError, transaction
from django.utils import timezone

from accounts.models import User
from assignments.models import Assignment
from notifications.services import queue_report_notifications
from .models import AllowedTransition, Channel, Comment, Photo, Report, StatusHistory, Verification
from .photo_pipeline import validate_and_reencode_photo
from .storage import private_photo_storage
from .transitions import seed_allowed_transitions


class ReportConflict(Exception):
    """Raised when a report changed since the officer opened its action form."""


@dataclass(frozen=True)
class TransitionRule:
    actor_role: str
    required_fields: tuple[str, ...] = ()


TRANSITION_TABLE = {
    (None, Report.Status.SUBMITTED): TransitionRule(User.Role.RESIDENT, ("valid_form",)),
    (Report.Status.SUBMITTED, Report.Status.UNDER_REVIEW): TransitionRule(
        User.Role.CALL_CENTER_STAFF
    ),
    (Report.Status.UNDER_REVIEW, Report.Status.ASSIGNED): TransitionRule(
        User.Role.CALL_CENTER_STAFF, ("priority", "technician")
    ),
    (Report.Status.UNDER_REVIEW, Report.Status.REJECTED): TransitionRule(
        User.Role.CALL_CENTER_STAFF, ("reason",)
    ),
    (Report.Status.SUBMITTED, Report.Status.REJECTED): TransitionRule(
        User.Role.CALL_CENTER_STAFF, ("reason",)
    ),
    (Report.Status.ASSIGNED, Report.Status.ASSIGNED): TransitionRule(
        User.Role.CALL_CENTER_STAFF, ("technician",)
    ),
    (Report.Status.IN_PROGRESS, Report.Status.ASSIGNED): TransitionRule(
        User.Role.CALL_CENTER_STAFF, ("technician",)
    ),
    (Report.Status.ASSIGNED, Report.Status.IN_PROGRESS): TransitionRule(
        User.Role.TECHNICIAN_CONTRACTOR
    ),
    (Report.Status.IN_PROGRESS, Report.Status.COMPLETED): TransitionRule(
        User.Role.TECHNICIAN_CONTRACTOR, ("completion_notes",)
    ),
    (Report.Status.COMPLETED, Report.Status.CLOSED): TransitionRule(
        User.Role.RESIDENT, ("rating",)
    ),
    (Report.Status.COMPLETED, Report.Status.REOPENED): TransitionRule(
        User.Role.RESIDENT, ("reason",)
    ),
    (Report.Status.REOPENED, Report.Status.ASSIGNED): TransitionRule(
        User.Role.CALL_CENTER_STAFF, ("technician",)
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


@transaction.atomic
@transaction.atomic
def apply_transition(report, new_status, actor, **kwargs):
    locked = Report.objects.select_for_update().get(pk=report.pk)
    actor_role = kwargs.pop("actor_role", actor if isinstance(actor, str) else getattr(actor, "role", None))
    if actor_role == "SYSTEM":
        actor_role = "SYSTEM"
    elif actor_role not in {"RESIDENT", "CALL_CENTER_STAFF", "TECHNICIAN_CONTRACTOR"}:
        raise ValidationError("A valid acting role is required.")

    from django.db import connection
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config('app.current_user_role', %s, true)", [actor_role])

    allowed = AllowedTransition.objects.filter(
        from_status=locked.status, to_status=new_status, actor_role=actor_role
    ).exists()
    if not allowed:
        raise ValidationError("This status transition is not allowed for this role.")

    old_status = locked.status
    history_actor = actor
    if isinstance(actor, str):
        history_actor = User.objects.filter(is_staff=True).first()
        if history_actor is None:
            history_actor = User.objects.create_superuser(username="system", email="system@example.test", password=None)
    now = timezone.now()
    note = kwargs.get("note", "")

    active_assignment = Assignment.objects.select_for_update().filter(report=locked, is_active=True).first()
    close_days = getattr(settings, "REPAIR_CLOSE_DAYS", 15)
    completion_assignment = Assignment.objects.filter(report=locked, completed_at__isnull=False).order_by("-completed_at", "-pk").first()

    if actor_role == "TECHNICIAN_CONTRACTOR" and new_status in {
        Report.Status.IN_PROGRESS, Report.Status.ON_HOLD, Report.Status.COMPLETED
    }:
        if active_assignment is None or active_assignment.technician_id != getattr(actor, "pk", None):
            raise ValidationError("Only the assigned technician may perform this transition.")

    if new_status == Report.Status.UNDER_REVIEW:
        if actor_role != User.Role.CALL_CENTER_STAFF:
            raise ValidationError("Only an officer may begin location review.")
        locked.location_verified_by = actor
        locked.location_verified_at = now

    if new_status == Report.Status.REJECTED:
        reason = str(kwargs.get("reason", "")).strip()
        if not reason:
            raise ValidationError("A rejection reason is required.")
        Comment.objects.create(report=locked, author=actor, kind=Comment.Kind.COMMENT, body=reason)
        note = reason

    if new_status == Report.Status.ON_HOLD:
        reason = str(kwargs.get("reason", "")).strip()
        expected_date = kwargs.get("expected_date")
        if not reason:
            raise ValidationError("A reason is required when putting a report on hold.")
        if expected_date is None:
            raise ValidationError("An expected date is required when putting a report on hold.")
        locked.expected_date = expected_date
        note = reason
        Comment.objects.create(
            report=locked,
            author=actor,
            kind=Comment.Kind.FOLLOW_UP,
            body=reason,
        )

    if new_status == Report.Status.IN_PROGRESS and old_status in {
        Report.Status.ASSIGNED,
        Report.Status.ON_HOLD,
        Report.Status.IN_PROGRESS,
    }:
        if active_assignment is not None and active_assignment.started_at is None:
            active_assignment.started_at = now
            active_assignment.save(update_fields=("started_at",))

    if new_status == Report.Status.COMPLETED:
        completion_notes = str(kwargs.get("completion_notes", "")).strip()
        if not completion_notes:
            raise ValidationError("Completion notes are required.")
        if active_assignment is None or active_assignment.technician_id != actor.pk:
            raise ValidationError("Only the assigned technician may complete this report.")
        active_assignment.completed_at = now
        active_assignment.completion_notes = completion_notes
        active_assignment.requester_signed_on_site = bool(kwargs.get("requester_signed_on_site", False))
        active_assignment.is_active = False
        active_assignment.ended_at = now
        active_assignment.end_reason = "COMPLETED"
        active_assignment.save(update_fields=("completed_at", "completion_notes", "requester_signed_on_site", "is_active", "ended_at", "end_reason"))
        note = completion_notes

    if new_status == Report.Status.CLOSED:
        if locked.status != Report.Status.COMPLETED:
            raise ValidationError("Only completed reports may be closed.")
        if completion_assignment is None:
            raise ValidationError("The completion date is required before closing.")
        elapsed = now - completion_assignment.completed_at
        if actor_role == "RESIDENT":
            if locked.resident_id != actor.pk:
                raise ValidationError("Only the requesting resident may close this report.")
            if elapsed > timezone.timedelta(days=close_days):
                raise ValidationError("The resident closing window has expired.")
            rating = kwargs.get("rating")
            if rating is not None and (not isinstance(rating, int) or not 1 <= rating <= 5):
                raise ValidationError("Rating must be a whole number from 1 to 5.")
        elif actor_role == "SYSTEM" and elapsed <= timezone.timedelta(days=close_days):
            raise ValidationError("The system closing window has not elapsed.")
        else:
            raise ValidationError("This role may not close a report.")

    if new_status == Report.Status.REOPENED:
        reason = str(kwargs.get("reason", "")).strip()
        if not reason:
            raise ValidationError("A reopen reason is required.")
        if locked.resident_id != actor.pk:
            raise ValidationError("Only the requesting resident may reopen this report.")
        if completion_assignment is None:
            raise ValidationError("The completion date is required before reopening.")
        if now - completion_assignment.completed_at > timezone.timedelta(days=close_days):
            raise ValidationError("The resident reopening window has expired.")
        note = reason

    changed_assignment = active_assignment
    if old_status == Report.Status.ASSIGNED and new_status == Report.Status.ASSIGNED:
        from assignments.services import reassign_assignment
        requested_technician = kwargs.get("technician")
        requested_unit = kwargs.get("unit") or getattr(active_assignment, "unit", None) or getattr(requested_technician, "unit", None)
        if requested_unit is None:
            raise ValidationError("A unit is required for reassignment.")
        kwargs["unit"] = requested_unit
        if (active_assignment and active_assignment.unit_id == requested_unit.pk
                and active_assignment.technician_id == getattr(requested_technician, "pk", None)):
            raise ValidationError("The requested assignment is already active.")
        changed_assignment = reassign_assignment(locked, requested_unit, requested_technician, actor)
    elif new_status == Report.Status.ASSIGNED:
        if not Assignment.objects.select_for_update().filter(report=locked, is_active=True).exists():
            requested_technician = kwargs.get("technician")
            requested_unit = kwargs.get("unit") or getattr(requested_technician, "unit", None)
            if requested_unit is None:
                raise ValidationError("A unit is required for assignment.")
            changed_assignment = Assignment.objects.create(
                report=locked,
                unit=requested_unit,
                technician=requested_technician,
                assigned_by=actor,
            )

    locked.status = new_status
    locked.version += 1
    update_fields = ["status", "expected_date", "version", "updated_at"]
    if new_status == Report.Status.UNDER_REVIEW:
        update_fields.extend(["location_verified_by", "location_verified_at"])
    locked.save(update_fields=update_fields)
    StatusHistory.objects.create(
        report=locked,
        old_status=old_status,
        new_status=new_status,
        changed_by=history_actor,
        assignment=changed_assignment,
        note=note,
    )
    if new_status == Report.Status.COMPLETED:
        queue_report_notifications(locked, event="is complete and ready for verification", recipients=(locked.resident,))
    elif new_status == Report.Status.ASSIGNED:
        unit = requested_unit if "requested_unit" in locals() else changed_assignment.unit
        queue_report_notifications(locked, event="was assigned", recipients=User.objects.filter(unit=unit, is_active=True))
    elif new_status == Report.Status.REJECTED:
        reason = kwargs.get("reason", "Rejected")
        queue_report_notifications(locked, event=f"was rejected: {reason}", recipients=(locked.resident,))
    elif new_status == Report.Status.ON_HOLD:
        queue_report_notifications(locked, event="was put on hold", recipients=(locked.resident,))
    elif new_status == Report.Status.REOPENED:
        officers = User.objects.filter(role=User.Role.CALL_CENTER_STAFF, is_active=True)
        queue_report_notifications(locked, event="was reopened", recipients=officers)
    elif new_status == Report.Status.CLOSED:
        queue_report_notifications(locked, event="was verified and closed", recipients=(locked.resident,))
    return locked


def transition_report(*, report, new_status, actor, **values):
    return apply_transition(report, new_status, actor, **values)

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
        if not actor.is_authenticated or actor.role != User.Role.CALL_CENTER_STAFF:
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
    if priority:
        report.priority = priority
        report.save(update_fields=("priority", "updated_at"))
    from assignments.models import Assignment
    from assignments.services import assign_technician as assign_service, reassign

    if Assignment.objects.filter(report=report, is_active=True).exists():
        return reassign(report, technician.unit, technician, assigned_by)
    return assign_service(report, technician.unit, technician, assigned_by)


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
def put_on_hold(
    *,
    report_id: int,
    technician: User,
    expected_version: int,
    reason: str,
    expected_date,
) -> Report:
    """Put assigned or in-progress work on hold."""

    reason = reason.strip()
    if not reason:
        raise ValidationError("A reason is required when putting a report on hold.")
    if expected_date is None:
        raise ValidationError("An expected date is required when putting a report on hold.")
    return transition_report(
        report=Report.objects.get(pk=report_id),
        new_status=Report.Status.ON_HOLD,
        actor=technician,
        expected_version=expected_version,
        reason=reason,
        expected_date=expected_date,
        note=reason,
    )


@transaction.atomic
def complete_work(
    *,
    report_id: int,
    technician: User,
    expected_version: int,
    completion_notes: str,
    photo=None,
    requester_signed_on_site: bool = False,
) -> Report:
    """Complete assigned work with notes and an optional processed photo."""

    completion_notes = completion_notes.strip()
    if not completion_notes:
        raise ValidationError("Completion notes are required.")
    if requester_signed_on_site and photo is None:
        raise ValidationError("Upload a completion photo when the paper signature was taken on site.")
    report = Report.objects.get(pk=report_id)
    processed_photo = validate_and_reencode_photo(photo) if photo is not None else None
    completed_report = transition_report(
        report=report,
        new_status=Report.Status.COMPLETED,
        actor=technician,
        expected_version=expected_version,
        completion_notes=completion_notes,
        requester_signed_on_site=requester_signed_on_site,
    )
    if processed_photo is not None:
        stored_path = default_storage.save(
            f"reports/completions/{processed_photo.name}",
            processed_photo,
        )
        Photo.objects.create(
            report=completed_report,
            uploaded_by=technician,
            assignment=Assignment.objects.filter(report=completed_report).order_by("-pk").first(),
            stage=Photo.Stage.COMPLETION,
            file_path=stored_path,
            content_type="image/png" if processed_photo.name.lower().endswith(".png") else "image/jpeg",
            size_bytes=processed_photo.size,
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
    completion_assignment = Assignment.objects.filter(report=closed_report).order_by("-completed_at", "-pk").first()
    if completion_assignment is None:
        raise ValidationError("No completed assignment exists for verification.")
    Verification.objects.create(
        report=closed_report,
        resident=resident,
        assignment=completion_assignment,
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

    completion_assignment = Assignment.objects.filter(report=source_report).order_by("-completed_at", "-pk").first()
    if completion_assignment is None:
        raise ValidationError("No completed assignment exists for reopening verification.")
    Verification.objects.create(
        report=source_report,
        resident=resident,
        assignment=completion_assignment,
        outcome=Verification.Outcome.REOPENED,
        rating=None,
        comment=reason,
    )
    return reopened


@transaction.atomic
def add_comment(
    *, report_id: int, author: User, body: str, kind: str = "COMMENT"
) -> Comment:
    """Create a comment only when the author may participate in the report."""

    body = body.strip()
    if not body:
        raise ValidationError("Comment text is required.")
    report = Report.objects.select_for_update().get(pk=report_id)
    if report.status == Report.Status.CLOSED:
        raise ValidationError("This ticket is closed and cannot accept comments.")
    if not Report.objects.for_user(author).filter(pk=report.pk).exists():
        raise ValidationError("You may not comment on this report.")
    kind = Comment.Kind.COMMENT
    if author.role == User.Role.TECHNICIAN_CONTRACTOR:
        assigned = Assignment.objects.filter(
            report=report,
            is_active=True,
            unit_id=author.unit_id,
        ).exists()
        if not assigned and not Assignment.objects.filter(report=report, technician=author, is_active=True).exists():
            raise ValidationError("Only technicians assigned to this ticket or its unit may comment.")
    comment = Comment.objects.create(
        report=report,
        author=author,
        body=body,
        kind=kind,
    )
    if (
        author.role == User.Role.RESIDENT
        and report.status in {Report.Status.COMPLETED, Report.Status.REOPENED}
    ):
        if not report.awaiting_call_center_response:
            report.awaiting_call_center_response = True
            report.save(update_fields=("awaiting_call_center_response",))
    elif author.role in {User.Role.CALL_CENTER_STAFF, User.Role.TECHNICIAN_CONTRACTOR}:
        if report.awaiting_call_center_response:
            report.awaiting_call_center_response = False
            report.save(update_fields=("awaiting_call_center_response",))
    return comment


@transaction.atomic
def _next_ticket_no(resident: User) -> str:
    student_id = "".join(character for character in resident.username if character.isdigit()) or str(resident.pk)
    prefix = f"CMR-2026-{student_id}-"
    sequences = []
    for existing in Report.objects.filter(ticket_no__startswith=prefix).values_list("ticket_no", flat=True):
        suffix = existing.rsplit("-", 1)[-1]
        if suffix.isdigit():
            sequences.append(int(suffix))
    return f"{prefix}{max(sequences, default=0) + 1:06d}"


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
    """Create a submitted resident report and its initial history row atomically."""

    if not resident.is_authenticated or resident.role != User.Role.RESIDENT:
        raise ValidationError("Resident reports must be submitted by a resident account.")
    ticket_no = _next_ticket_no(resident)
    report = Report(
        ticket_no=ticket_no,
        resident=resident,
        submitted_by=None,
        category=category,
        building=building,
        room_location=room_location,
        title=title,
        description=description,
        channel=Channel.WEB,
        requested_urgency=requested_urgency,
        status=Report.Status.SUBMITTED,
        version=1,
    )
    report.full_clean()
    report.save()
    if photo is not None:
        stored_path = private_photo_storage.save(f"reports/{photo.name}", photo)
        Photo.objects.create(
            report=report,
            uploaded_by=resident,
            stage=Photo.Stage.REPORT,
            file_path=stored_path,
            content_type=getattr(photo, "content_type", "image/jpeg"),
            size_bytes=getattr(photo, "size", 0),
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
        recipients=User.objects.filter(role=User.Role.CALL_CENTER_STAFF, is_active=True),
    )
    return report


@transaction.atomic
def enter_report_for_caller(
    *,
    resident: User,
    submitted_by: User,
    channel: str,
    category,
    building,
    room_location: str,
    title: str,
    description: str,
    requested_urgency: str,
    photo=None,
) -> Report:
    """Create a report entered by an officer on behalf of a resident account."""

    if not submitted_by.is_authenticated or submitted_by.role != User.Role.CALL_CENTER_STAFF:
        raise ValidationError("Staff entry must be performed by an officer.")
    if not resident.is_authenticated or resident.role != User.Role.RESIDENT:
        raise ValidationError("The caller must have a resident account.")
    if channel not in {Channel.PHONE, Channel.EMAIL, Channel.WALK_IN}:
        raise ValidationError("Staff-entered reports require PHONE, EMAIL, or WALK_IN channel.")

    report = Report(
        ticket_no=_next_ticket_no(resident),
        resident=resident,
        submitted_by=submitted_by,
        category=category,
        building=building,
        room_location=room_location,
        title=title,
        description=description,
        channel=channel,
        requested_urgency=requested_urgency,
        status=Report.Status.SUBMITTED,
        version=1,
    )
    report.full_clean()
    report.save()
    StatusHistory.objects.create(
        report=report,
        old_status=None,
        new_status=Report.Status.SUBMITTED,
        changed_by=submitted_by,
        note=f"Report entered by staff via {channel}",
    )
    if photo is not None:
        stored_path = private_photo_storage.save(f"reports/{photo.name}", photo)
        Photo.objects.create(
            report=report,
            uploaded_by=submitted_by,
            stage=Photo.Stage.REPORT,
            file_path=stored_path,
            content_type=getattr(photo, "content_type", "image/jpeg"),
            size_bytes=getattr(photo, "size", 0),
        )
    queue_report_notifications(report, event="was submitted", recipients=(resident,))
    return report
