from .models import AllowedTransition


ALLOWED_TRANSITIONS = [
    ("SUBMITTED", "UNDER_REVIEW", "CALL_CENTER_STAFF"),
    ("SUBMITTED", "ASSIGNED", "CALL_CENTER_STAFF"),
    ("SUBMITTED", "REJECTED", "CALL_CENTER_STAFF"),
    ("UNDER_REVIEW", "ASSIGNED", "CALL_CENTER_STAFF"),
    ("UNDER_REVIEW", "REJECTED", "CALL_CENTER_STAFF"),
    ("ASSIGNED", "ASSIGNED", "CALL_CENTER_STAFF"),
    ("ASSIGNED", "IN_PROGRESS", "TECHNICIAN_CONTRACTOR"),
    ("ASSIGNED", "ON_HOLD", "TECHNICIAN_CONTRACTOR"),
    ("IN_PROGRESS", "ON_HOLD", "TECHNICIAN_CONTRACTOR"),
    ("ON_HOLD", "IN_PROGRESS", "TECHNICIAN_CONTRACTOR"),
    ("IN_PROGRESS", "COMPLETED", "TECHNICIAN_CONTRACTOR"),
    ("COMPLETED", "CLOSED", "RESIDENT"),
    ("COMPLETED", "CLOSED", "SYSTEM"),
    ("COMPLETED", "REOPENED", "RESIDENT"),
    ("REOPENED", "ASSIGNED", "CALL_CENTER_STAFF"),
    ("REOPENED", "IN_PROGRESS", "TECHNICIAN_CONTRACTOR"),
]


def seed_allowed_transitions():
    AllowedTransition.objects.all().delete()
    for from_status, to_status, actor_role in ALLOWED_TRANSITIONS:
        AllowedTransition.objects.get_or_create(
            from_status=from_status,
            to_status=to_status,
            actor_role=actor_role,
        )
