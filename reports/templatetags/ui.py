from django import template

register = template.Library()

# (status that marks the step, label shown in the journey line)
JOURNEY_STEPS = (
    ("SUBMITTED", "Sent"),
    ("UNDER_REVIEW", "Review"),
    ("ASSIGNED", "Assigned"),
    ("IN_PROGRESS", "In progress"),
    ("COMPLETED", "Done"),
    ("CLOSED", "Closed"),
)
STEP_INDEX = {status: index for index, (status, _) in enumerate(JOURNEY_STEPS)}

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
        if status == "CLOSED" and index == current:
            state = "done"
        steps.append(
            {
                "label": label if index == current and label else step_label,
                "state": state.strip(),
            }
        )
    return {"steps": steps}
