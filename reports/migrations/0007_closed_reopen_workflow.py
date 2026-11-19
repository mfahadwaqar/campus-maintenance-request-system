from django.db import migrations


def update_transitions(apps, schema_editor):
    AllowedTransition = apps.get_model("reports", "AllowedTransition")
    AllowedTransition.objects.filter(
        from_status="COMPLETED",
        to_status="CLOSED",
        actor_role="RESIDENT",
    ).delete()
    AllowedTransition.objects.filter(
        from_status="COMPLETED",
        to_status="REOPENED",
        actor_role="RESIDENT",
    ).delete()
    AllowedTransition.objects.filter(
        from_status="REOPENED",
        to_status="IN_PROGRESS",
        actor_role="TECHNICIAN_CONTRACTOR",
    ).delete()
    AllowedTransition.objects.get_or_create(
        from_status="CLOSED",
        to_status="REOPENED",
        actor_role="RESIDENT",
    )
    AllowedTransition.objects.get_or_create(
        from_status="CLOSED",
        to_status="REOPENED",
        actor_role="CALL_CENTER_STAFF",
    )


def restore_transitions(apps, schema_editor):
    AllowedTransition = apps.get_model("reports", "AllowedTransition")
    AllowedTransition.objects.filter(
        from_status="CLOSED",
        to_status="REOPENED",
        actor_role__in=("RESIDENT", "CALL_CENTER_STAFF"),
    ).delete()
    AllowedTransition.objects.get_or_create(
        from_status="COMPLETED",
        to_status="CLOSED",
        actor_role="RESIDENT",
    )
    AllowedTransition.objects.get_or_create(
        from_status="COMPLETED",
        to_status="REOPENED",
        actor_role="RESIDENT",
    )
    AllowedTransition.objects.get_or_create(
        from_status="REOPENED",
        to_status="IN_PROGRESS",
        actor_role="TECHNICIAN_CONTRACTOR",
    )


class Migration(migrations.Migration):
    dependencies = [("reports", "0006_role_rename_and_comment_flag")]

    # Keep the database transition guard aligned with system-close and 3-day reopen rules.
    operations = [migrations.RunPython(update_transitions, restore_transitions)]
