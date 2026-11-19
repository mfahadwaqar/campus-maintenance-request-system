from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import Assignment, EndReason
from accounts.models import User


def _validate_assignment(unit, technician, officer):
    if unit is None:
        raise ValidationError("A unit is required.")
    if not unit.is_active:
        raise ValidationError("Choose an active unit.")
    if not getattr(officer, "is_authenticated", False) or officer.role != User.Role.CALL_CENTER_STAFF:
        raise ValidationError("Only Call Center Staff may assign or reassign work.")
    if technician is not None:
        if technician.role != User.Role.TECHNICIAN_CONTRACTOR or not technician.is_active:
            raise ValidationError("Choose an active Technician/Contractor.")
        if technician.unit_id != unit.pk:
            raise ValidationError("The Technician/Contractor must belong to the selected unit.")


def create_assignment(report, unit, technician, officer):
    _validate_assignment(unit, technician, officer)
    return Assignment.objects.create(
        report=report,
        unit=unit,
        technician=technician,
        assigned_by=officer,
    )


def reassign_assignment(report, unit, technician, officer):
    _validate_assignment(unit, technician, officer)
    active = Assignment.objects.select_for_update().filter(report=report, is_active=True).first()
    if active is None:
        raise ValidationError("The report has no active assignment to reassign.")

    now = timezone.now()
    active.is_active = False
    active.ended_at = now
    active.end_reason = EndReason.REASSIGNED
    active.save(update_fields=("is_active", "ended_at", "end_reason"))

    return Assignment.objects.create(
        report=report,
        unit=unit,
        technician=technician,
        assigned_by=officer,
    )


@transaction.atomic
def assign_technician(report, unit, technician, officer):
    if Assignment.objects.select_for_update().filter(report=report, is_active=True).exists():
        raise ValidationError("The report already has an active assignment; use reassign().")
    _validate_assignment(unit, technician, officer)
    from reports.services import apply_transition

    return apply_transition(report, "ASSIGNED", officer, technician=technician, unit=unit,
                            assignment_action="assign", note="Technician/Contractor assigned")


@transaction.atomic
def reassign(report, unit, technician, officer):
    if not Assignment.objects.select_for_update().filter(report=report, is_active=True).exists():
        raise ValidationError("The report has no active assignment to reassign.")
    _validate_assignment(unit, technician, officer)
    from reports.services import apply_transition

    return apply_transition(report, "ASSIGNED", officer, technician=technician, unit=unit,
                            assignment_action="reassign", note="Technician/Contractor reassigned")
