from django.db import migrations


def update_transitions(apps, schema_editor):
    AllowedTransition = apps.get_model("reports", "AllowedTransition")
    AllowedTransition.objects.filter(
        from_status="CLOSED",
        to_status="REOPENED",
        actor_role__in=("RESIDENT", "CALL_CENTER_STAFF"),
    ).delete()
    AllowedTransition.objects.filter(
        from_status="REOPENED",
        to_status="ASSIGNED",
        actor_role="CALL_CENTER_STAFF",
    ).delete()
    AllowedTransition.objects.get_or_create(
        from_status="CLOSED",
        to_status="ASSIGNED",
        actor_role="RESIDENT",
    )
    AllowedTransition.objects.get_or_create(
        from_status="CLOSED",
        to_status="ASSIGNED",
        actor_role="CALL_CENTER_STAFF",
    )


def restore_transitions(apps, schema_editor):
    AllowedTransition = apps.get_model("reports", "AllowedTransition")
    AllowedTransition.objects.filter(
        from_status="CLOSED",
        to_status="ASSIGNED",
        actor_role__in=("RESIDENT", "CALL_CENTER_STAFF"),
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
    AllowedTransition.objects.get_or_create(
        from_status="REOPENED",
        to_status="ASSIGNED",
        actor_role="CALL_CENTER_STAFF",
    )


class Migration(migrations.Migration):
    dependencies = [("reports", "0007_closed_reopen_workflow")]

    operations = [migrations.RunPython(update_transitions, restore_transitions)]
