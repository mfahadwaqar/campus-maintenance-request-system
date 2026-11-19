"""Unit tests for the business rules in reports/services.py.

Design (lecture 6.1): each rule is tested on both sides of its decision (branch coverage),
at the edges of its valid range (boundary values), and negative tests also check that a
refused action left the database unchanged.
"""

from datetime import date, timedelta

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from assignments.models import Assignment
from reports.models import Comment, StatusHistory, Verification
from reports.services import (
    ReportConflict,
    add_comment,
    apply_transition,
    assign_technician,
    complete_work,
    put_on_hold,
    reject_report,
    reopen_report,
    start_review,
    verify_report,
)

pytestmark = [pytest.mark.unit, pytest.mark.whitebox, pytest.mark.django_db]


def history_count(report):
    return StatusHistory.objects.filter(report=report).count()


# ------------------------------------------------------------------ ticket numbers
def test_ticket_number_has_the_resident_id_and_a_six_digit_sequence(new_report):
    first = new_report()
    second = new_report(title="Second fault")

    assert first.ticket_no == "CMR-2026-900001-000001"
    assert second.ticket_no == "CMR-2026-900001-000002"


def test_sequences_are_counted_per_resident(new_report, other_resident):
    new_report()

    other = new_report(owner=other_resident)

    assert other.ticket_no == "CMR-2026-900002-000001"


def test_a_new_report_starts_submitted_with_one_history_row(new_report):
    report = new_report()

    assert report.status == "SUBMITTED"
    assert history_count(report) == 1


def test_every_accepted_change_raises_the_version_by_exactly_one(new_report, flow):
    report = new_report()
    start = report.version

    flow.review(report)
    after_review = report.version
    flow.assign(report)

    assert after_review == start + 1
    assert report.version == start + 2


# ------------------------------------------------------------------ review (branch: room verified)
@pytest.mark.parametrize("room_verified,allowed", [(True, True), (False, False)])
def test_review_needs_the_room_to_be_verified(new_report, staff, room_verified, allowed):
    report = new_report()

    if allowed:
        start_review(report_id=report.pk, actor=staff, expected_version=report.version, room_verified=True)
        report.refresh_from_db()
        assert report.status == "UNDER_REVIEW"
        assert report.location_verified_by == staff
        assert report.location_verified_at is not None
    else:
        with pytest.raises(ValidationError, match="room"):
            start_review(report_id=report.pk, actor=staff, expected_version=report.version, room_verified=False)
        report.refresh_from_db()
        assert report.status == "SUBMITTED"
        assert history_count(report) == 1


def test_only_call_center_staff_may_review(new_report, resident, technician):
    report = new_report()

    for actor in (resident, technician):
        with pytest.raises(ValidationError):
            start_review(report_id=report.pk, actor=actor, expected_version=report.version, room_verified=True)


# ------------------------------------------------------------------ assignment (branch: priority)
def test_first_assignment_needs_a_priority(new_report, flow, technician, unit):
    report = flow.review(new_report())

    with pytest.raises(ValidationError, match="priority"):
        assign_technician(
            report_id=report.pk,
            technician=technician,
            assigned_by=flow.staff,
            unit=unit,
            priority=None,
            expected_version=report.version,
        )
    report.refresh_from_db()
    assert report.status == "UNDER_REVIEW"
    assert not Assignment.objects.filter(report=report).exists()


def test_assignment_with_a_priority_makes_exactly_one_active_row(new_report, flow):
    report = flow.assign(new_report())

    assert report.status == "ASSIGNED"
    assert report.priority == "HIGH"
    assert Assignment.objects.filter(report=report, is_active=True).count() == 1


def test_reassignment_ends_the_old_row_and_keeps_one_active(new_report, flow, other_unit):
    report = flow.assign(new_report())

    assign_technician(
        report_id=report.pk,
        technician=None,
        assigned_by=flow.staff,
        unit=other_unit,
        priority=None,
        expected_version=report.version,
    )

    rows = Assignment.objects.filter(report=report)
    assert rows.count() == 2
    assert rows.filter(is_active=True).count() == 1
    assert rows.filter(is_active=False).get().end_reason == "REASSIGNED"


def test_a_technician_must_belong_to_the_chosen_unit(new_report, flow, technician, other_unit):
    report = flow.review(new_report())

    with pytest.raises(ValidationError):
        assign_technician(
            report_id=report.pk,
            technician=technician,
            assigned_by=flow.staff,
            unit=other_unit,
            priority="HIGH",
            expected_version=report.version,
        )
    assert not Assignment.objects.filter(report=report).exists()


# ------------------------------------------------------------------ rejection
@pytest.mark.parametrize("reason", ["", "   "])
def test_rejection_needs_a_real_reason(new_report, staff, reason):
    report = new_report()

    with pytest.raises(ValidationError, match="reason"):
        reject_report(report_id=report.pk, reason=reason, actor=staff, expected_version=report.version)
    report.refresh_from_db()
    assert report.status == "SUBMITTED"


def test_a_rejected_ticket_keeps_the_reason_as_a_comment(new_report, staff):
    report = new_report()

    reject_report(report_id=report.pk, reason="Duplicate request", actor=staff, expected_version=report.version)

    report.refresh_from_db()
    assert report.status == "REJECTED"
    assert Comment.objects.filter(report=report, body="Duplicate request").exists()


# ------------------------------------------------------------------ hold (boundaries: reason length)
@pytest.mark.parametrize(
    "length,accepted",
    [(1, True), (399, True), (400, True), (401, False)],  # 400 is the documented maximum
)
def test_hold_reason_length_boundary(in_progress_report, flow, technician, length, accepted):
    report = in_progress_report
    kwargs = dict(
        report_id=report.pk,
        technician=technician,
        expected_version=report.version,
        reason="x" * length,
        expected_date=date.today() + timedelta(days=1),
    )

    if accepted:
        put_on_hold(**kwargs)
        report.refresh_from_db()
        assert report.status == "ON_HOLD"
    else:
        with pytest.raises(ValidationError, match="400"):
            put_on_hold(**kwargs)
        report.refresh_from_db()
        assert report.status == "IN_PROGRESS"


def test_hold_needs_a_reason_and_a_date(in_progress_report, technician):
    report = in_progress_report
    base = dict(report_id=report.pk, technician=technician, expected_version=report.version)

    with pytest.raises(ValidationError, match="reason"):
        put_on_hold(reason="  ", expected_date=date.today(), **base)
    with pytest.raises(ValidationError, match="date"):
        put_on_hold(reason="Waiting for parts", expected_date=None, **base)
    report.refresh_from_db()
    assert report.status == "IN_PROGRESS"


def test_a_held_job_can_be_resumed(in_progress_report, flow):
    report = in_progress_report

    flow.hold(report)
    status_while_held = report.status
    flow.start(report)

    assert (status_while_held, report.status) == ("ON_HOLD", "IN_PROGRESS")


def test_only_the_assigned_technician_may_hold(in_progress_report, other_technician):
    report = in_progress_report

    with pytest.raises(ValidationError):
        put_on_hold(
            report_id=report.pk,
            technician=other_technician,
            expected_version=report.version,
            reason="Not mine",
            expected_date=date.today(),
        )


# ------------------------------------------------------------------ completion
@pytest.mark.parametrize("notes", ["", "   \n"])
def test_completion_needs_notes(in_progress_report, technician, notes):
    report = in_progress_report

    with pytest.raises(ValidationError, match="notes"):
        complete_work(
            report_id=report.pk,
            technician=technician,
            expected_version=report.version,
            completion_notes=notes,
        )
    report.refresh_from_db()
    assert report.status == "IN_PROGRESS"


def test_completion_closes_the_ticket_in_the_same_step_with_two_history_rows(in_progress_report, flow):
    before = history_count(in_progress_report)

    report = flow.complete(in_progress_report)

    assert report.status == "CLOSED"
    new_rows = StatusHistory.objects.filter(report=report).order_by("-pk")[:2]
    assert [row.new_status for row in new_rows] == ["CLOSED", "COMPLETED"]
    assert history_count(report) == before + 2


def test_a_completion_photo_needs_the_signature_flag(in_progress_report, technician, photo):
    report = in_progress_report

    with pytest.raises(ValidationError, match="signature"):
        complete_work(
            report_id=report.pk,
            technician=technician,
            expected_version=report.version,
            completion_notes="Done",
            photo=photo,
            requester_signed_on_site=False,
        )


def test_completion_without_the_resident_is_recorded_as_unsigned(in_progress_report, flow):
    report = flow.complete(in_progress_report, signed=False)

    assignment = Assignment.objects.filter(report=report, completed_at__isnull=False).get()
    assert assignment.requester_signed_on_site is False
    assert assignment.completion_notes == "Fixed the leak."


# ------------------------------------------------------------------ verification (boundaries: rating)
@pytest.mark.parametrize(
    "rating,accepted",
    [(None, True), (1, True), (5, True), (0, False), (6, False), (-1, False), ("3", False)],
)
def test_rating_boundaries(closed_report, resident, rating, accepted):
    report = closed_report
    kwargs = dict(
        report_id=report.pk,
        resident=resident,
        expected_version=report.version,
        rating=rating,
        comment="ok",
    )

    if accepted:
        verify_report(**kwargs)
        assert Verification.objects.filter(report=report).count() == 1
    else:
        with pytest.raises(ValidationError, match="Rating"):
            verify_report(**kwargs)
        assert not Verification.objects.filter(report=report).exists()


def test_verification_is_refused_before_the_ticket_is_closed(assigned_report, resident):
    with pytest.raises(ValidationError) as caught:
        verify_report(
            report_id=assigned_report.pk,
            resident=resident,
            expected_version=assigned_report.version,
        )

    assert caught.value.code == "ticket_not_closed"


def test_the_same_work_cannot_be_verified_twice(closed_report, resident):
    verify_report(report_id=closed_report.pk, resident=resident, expected_version=closed_report.version)

    with pytest.raises(ValidationError, match="already been verified"):
        verify_report(report_id=closed_report.pk, resident=resident, expected_version=closed_report.version)


def test_only_the_owner_may_verify(closed_report, other_resident):
    with pytest.raises(ValidationError, match="requesting resident"):
        verify_report(
            report_id=closed_report.pk,
            resident=other_resident,
            expected_version=closed_report.version,
        )


# ------------------------------------------------------------------ reopening (boundary: 3 days)
def age_completion(report, **delta):
    Assignment.objects.filter(report=report, completed_at__isnull=False).update(
        completed_at=timezone.now() - timedelta(**delta)
    )


def test_reopen_just_inside_the_three_day_window_is_allowed(closed_report, flow, resident):
    age_completion(closed_report, days=2, hours=23, minutes=59)

    report = flow.reopen(closed_report, resident)

    assert report.status == "ASSIGNED"


def test_reopen_just_outside_the_window_is_refused_with_its_own_code(closed_report, resident):
    age_completion(closed_report, days=3, minutes=1)

    with pytest.raises(ValidationError) as caught:
        reopen_report(
            report_id=closed_report.pk,
            actor=resident,
            expected_version=closed_report.version,
            reason="Too late?",
        )

    assert caught.value.code == "reopen_window_closed"
    closed_report.refresh_from_db()
    assert closed_report.status == "CLOSED"


def test_the_window_length_comes_from_the_setting(closed_report, resident, settings):
    settings.REOPEN_WINDOW_DAYS = 1
    age_completion(closed_report, days=1, minutes=1)

    with pytest.raises(ValidationError, match="reopen"):
        reopen_report(
            report_id=closed_report.pk,
            actor=resident,
            expected_version=closed_report.version,
            reason="Late",
        )


@pytest.mark.parametrize("reason", ["", "   "])
def test_reopen_needs_a_reason(closed_report, resident, reason):
    with pytest.raises(ValidationError):
        reopen_report(
            report_id=closed_report.pk,
            actor=resident,
            expected_version=closed_report.version,
            reason=reason,
        )


def test_staff_may_reopen_but_another_resident_may_not(closed_report, staff, other_resident):
    with pytest.raises(ValidationError):
        reopen_report(
            report_id=closed_report.pk,
            actor=other_resident,
            expected_version=closed_report.version,
            reason="Not my ticket",
        )

    reopen_report(
        report_id=closed_report.pk,
        actor=staff,
        expected_version=closed_report.version,
        reason="Resident phoned back",
    )
    closed_report.refresh_from_db()
    assert closed_report.status == "ASSIGNED"


# ------------------------------------------------------------------ comments (branch: closed / role)
def test_comment_on_an_open_ticket_is_saved(in_progress_report, resident):
    comment = add_comment(report_id=in_progress_report.pk, author=resident, body="  Any news?  ")

    assert comment.body == "Any news?"
    assert Comment.objects.filter(report=in_progress_report).count() == 1


def test_comment_on_a_closed_ticket_is_refused_and_nothing_is_saved(closed_report, resident):
    before = Comment.objects.count()

    with pytest.raises(ValidationError) as caught:
        add_comment(report_id=closed_report.pk, author=resident, body="Still leaking")

    assert caught.value.code == "ticket_closed"
    assert Comment.objects.count() == before


def test_comments_are_allowed_again_after_a_reopen(closed_report, flow, resident):
    flow.reopen(closed_report, resident)

    assert add_comment(report_id=closed_report.pk, author=resident, body="Thanks")


@pytest.mark.parametrize("body", ["", "  \n "])
def test_blank_comments_are_refused(in_progress_report, resident, body):
    with pytest.raises(ValidationError, match="required"):
        add_comment(report_id=in_progress_report.pk, author=resident, body=body)


def test_another_resident_cannot_comment(in_progress_report, other_resident):
    with pytest.raises(ValidationError):
        add_comment(report_id=in_progress_report.pk, author=other_resident, body="Hi")


def test_an_unassigned_technician_cannot_comment(in_progress_report, other_technician, flow):
    with pytest.raises(ValidationError):
        add_comment(report_id=in_progress_report.pk, author=other_technician, body="Hi")


def test_the_follow_up_flag_follows_who_wrote_last(in_progress_report, resident, staff):
    report = in_progress_report

    add_comment(report_id=report.pk, author=resident, body="Any news?")
    report.refresh_from_db()
    assert report.awaiting_call_center_response is True

    add_comment(report_id=report.pk, author=staff, body="On its way")
    report.refresh_from_db()
    assert report.awaiting_call_center_response is False


# ------------------------------------------------------------------ optimistic locking
def test_a_stale_version_is_refused_and_changes_nothing(new_report, staff):
    report = new_report()
    stale = report.version
    start_review(report_id=report.pk, actor=staff, expected_version=stale, room_verified=True)

    with pytest.raises(ReportConflict):
        reject_report(report_id=report.pk, reason="Late click", actor=staff, expected_version=stale)

    report.refresh_from_db()
    assert report.status == "UNDER_REVIEW"


# ------------------------------------------------------------------ transition table
ILLEGAL = [
    ("technician", "SUBMITTED", "IN_PROGRESS"),
    ("technician", "SUBMITTED", "COMPLETED"),
    ("technician", "UNDER_REVIEW", "COMPLETED"),
    ("technician", "CLOSED", "IN_PROGRESS"),
    ("staff", "CLOSED", "UNDER_REVIEW"),
    ("staff", "REJECTED", "ASSIGNED"),
    ("staff", "IN_PROGRESS", "SUBMITTED"),
]


@pytest.mark.parametrize("actor_name,from_status,to_status", ILLEGAL)
def test_illegal_status_jumps_are_refused_and_leave_no_trace(
    request, new_report, flow, staff, technician, actor_name, from_status, to_status
):
    report = new_report()
    if from_status == "UNDER_REVIEW":
        flow.review(report)
    elif from_status == "IN_PROGRESS":
        flow.start(flow.assign(report))
    elif from_status == "CLOSED":
        flow.complete(flow.start(flow.assign(report)))
    elif from_status == "REJECTED":
        reject_report(report_id=report.pk, reason="No", actor=staff, expected_version=report.version)
    report.refresh_from_db()
    actor = staff if actor_name == "staff" else technician
    rows = history_count(report)

    with pytest.raises(ValidationError):
        apply_transition(report, to_status, actor, expected_version=report.version)

    report.refresh_from_db()
    assert report.status == from_status
    assert history_count(report) == rows


# ------------------------------------------------------------------ the status rules as a model
def test_the_rule_table_in_the_database_matches_the_documented_rules():
    from reports.models import AllowedTransition
    from reports.transitions import ALLOWED_TRANSITIONS

    stored = set(AllowedTransition.objects.values_list("from_status", "to_status", "actor_role"))

    assert stored == set(ALLOWED_TRANSITIONS)
    assert len(stored) == 14


def test_status_rules_hold_four_invariants():
    from reports.transitions import ALLOWED_TRANSITIONS

    # 1. REJECTED is final: nothing leaves it.
    assert not [t for t in ALLOWED_TRANSITIONS if t[0] == "REJECTED"]
    # 2. Nothing returns a ticket to SUBMITTED.
    assert not [t for t in ALLOWED_TRANSITIONS if t[1] == "SUBMITTED"]
    # 3. Only the system closes a ticket, and only from COMPLETED.
    assert [t for t in ALLOWED_TRANSITIONS if t[1] == "CLOSED"] == [("COMPLETED", "CLOSED", "SYSTEM")]
    # 4. Work statuses belong to the technician; reopening belongs to the resident and staff.
    for from_status, to_status, role in ALLOWED_TRANSITIONS:
        if to_status in {"IN_PROGRESS", "ON_HOLD", "COMPLETED"}:
            assert role == "TECHNICIAN_CONTRACTOR"
        if from_status == "CLOSED":
            assert role in {"RESIDENT", "CALL_CENTER_STAFF"}
