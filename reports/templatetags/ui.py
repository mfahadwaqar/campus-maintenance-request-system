from datetime import timedelta

from django import template
from django.conf import settings
from django.utils import timezone

register = template.Library()

# (status that marks the step, label shown in the journey line)
JOURNEY_STEPS = (
    ("SUBMITTED", "Sent"),
    ("UNDER_REVIEW", "Review"),
    ("ASSIGNED", "Assigned"),
    ("IN_PROGRESS", "In progress"),
    ("CLOSED", "Closed"),
)
STEP_INDEX = {status: index for index, (status, _) in enumerate(JOURNEY_STEPS)}
# Completing a job closes the ticket in the same step, so COMPLETED shares the Closed step.
STEP_INDEX["COMPLETED"] = STEP_INDEX["CLOSED"]

# Statuses that sit off the happy path: (step they appear at, label, css class).
OFF_PATH = {
    "ON_HOLD": (STEP_INDEX["IN_PROGRESS"], "On hold", "alert-step"),
    "REOPENED": (STEP_INDEX["ASSIGNED"], "Reopened", "alert-step reopened"),
}


@register.inclusion_tag("reports/_journey.html")
def journey(status):
    """Render the progress line for a report status. Rejected reports get none."""

    if status == "REJECTED":
        return {"steps": []}

    if status in OFF_PATH:
        current, label, css = OFF_PATH[status]
    else:
        current, label, css = STEP_INDEX.get(status, 0), None, ""

    steps = []
    for index, (_, step_label) in enumerate(JOURNEY_STEPS):
        if index < current:
            state = "done"
        elif index == current:
            state = "current " + css if css else "current"
        else:
            state = ""
        # Closed is the last step: once reached it is done, not pending.
        if status in ("CLOSED", "COMPLETED") and index == current:
            state = "done"
        steps.append(
            {
                "label": label if index == current and label else step_label,
                "state": state.strip(),
            }
        )
    return {"steps": steps}


QUEUE_GROUPS = (
    ("Needs review", ("SUBMITTED", "UNDER_REVIEW"), "var(--blue)"),
    ("With technicians", ("ASSIGNED", "IN_PROGRESS", "ON_HOLD"), "var(--teal)"),
    ("Reopened", ("REOPENED",), "var(--terra)"),
    ("Finished", ("COMPLETED", "CLOSED"), "var(--green)"),
)

OPEN_STATUSES = ("SUBMITTED", "UNDER_REVIEW", "ASSIGNED", "IN_PROGRESS", "ON_HOLD", "REOPENED")


@register.inclusion_tag("reports/_queue_summary.html")
def queue_summary(reports):
    """Count the reports on the current page by stage for the queue header tiles."""

    statuses = [report.status for report in reports]
    tiles = [
        {"label": label, "count": sum(1 for s in statuses if s in group), "color": color}
        for label, group, color in QUEUE_GROUPS
    ]
    return {"tiles": tiles}


@register.filter
def is_open(status):
    """True while a request still needs work, so the age tag is worth showing."""

    return status in OPEN_STATUSES


@register.inclusion_tag("reports/_report_notes.html")
def report_notes(report):
    """Hold details, completion record and reopen window for one report."""

    completed = [row for row in report.assignments.all() if row.completed_at]
    completion = max(completed, key=lambda row: (row.completed_at, row.pk), default=None)

    hold = None
    if report.status == "ON_HOLD":
        latest = (
            report.status_history.filter(new_status="ON_HOLD")
            .order_by("-changed_at", "-pk")
            .first()
        )
        hold = {
            "reason": latest.note if latest else "",
            "expected_date": report.expected_date,
        }

    reopen = None
    if report.status == "CLOSED" and completion is not None:
        days = getattr(settings, "REOPEN_WINDOW_DAYS", 3)
        deadline = completion.completed_at + timedelta(days=days)
        reopen = {
            "days": days,
            "deadline": deadline,
            "is_open": deadline >= timezone.now(),
        }
    return {"hold": hold, "completion": completion, "reopen": reopen}
