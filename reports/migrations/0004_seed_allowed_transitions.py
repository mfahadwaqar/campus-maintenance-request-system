from django.db import migrations

ALLOWED_TRANSITIONS = [
    ("SUBMITTED", "UNDER_REVIEW", "OFFICER"),
    ("SUBMITTED", "ASSIGNED", "OFFICER"),
    ("SUBMITTED", "REJECTED", "OFFICER"),
    ("UNDER_REVIEW", "ASSIGNED", "OFFICER"),
    ("UNDER_REVIEW", "REJECTED", "OFFICER"),
    ("ASSIGNED", "ASSIGNED", "OFFICER"),
    ("ASSIGNED", "IN_PROGRESS", "TECHNICIAN"),
    ("ASSIGNED", "ON_HOLD", "TECHNICIAN"),
    ("IN_PROGRESS", "ON_HOLD", "TECHNICIAN"),
    ("ON_HOLD", "IN_PROGRESS", "TECHNICIAN"),
    ("IN_PROGRESS", "COMPLETED", "TECHNICIAN"),
    ("COMPLETED", "CLOSED", "RESIDENT"),
    ("COMPLETED", "CLOSED", "SYSTEM"),
    ("COMPLETED", "REOPENED", "RESIDENT"),
    ("REOPENED", "ASSIGNED", "OFFICER"),
    ("REOPENED", "IN_PROGRESS", "TECHNICIAN"),
]


def seed(apps, schema_editor):
    AllowedTransition = apps.get_model("reports", "AllowedTransition")
    AllowedTransition.objects.all().delete()
    for from_status, to_status, actor_role in ALLOWED_TRANSITIONS:
        AllowedTransition.objects.get_or_create(
            from_status=from_status, to_status=to_status, actor_role=actor_role
        )


class Migration(migrations.Migration):
    dependencies = [("reports", "0003_align_history_and_photo")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
