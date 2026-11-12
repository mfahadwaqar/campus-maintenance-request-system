from django.db import migrations, models


def rename_roles_forward(apps, schema_editor):
    AllowedTransition = apps.get_model("reports", "AllowedTransition")
    AllowedTransition.objects.filter(actor_role="TECHNICIAN").update(actor_role="TECHNICIAN_CONTRACTOR")
    AllowedTransition.objects.filter(actor_role="OFFICER").update(actor_role="CALL_CENTER_STAFF")


def rename_roles_reverse(apps, schema_editor):
    AllowedTransition = apps.get_model("reports", "AllowedTransition")
    AllowedTransition.objects.filter(actor_role="TECHNICIAN_CONTRACTOR").update(actor_role="TECHNICIAN")
    AllowedTransition.objects.filter(actor_role="CALL_CENTER_STAFF").update(actor_role="OFFICER")


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0004_rename_roles"),
        ("reports", "0005_database_transition_guards"),
    ]

    operations = [
        migrations.AlterField(
            model_name="allowedtransition",
            name="actor_role",
            field=models.CharField(
                choices=[
                    ("RESIDENT", "Resident"),
                    ("CALL_CENTER_STAFF", "Call Center Staff"),
                    ("TECHNICIAN_CONTRACTOR", "Technician/Contractor"),
                    ("SYSTEM", "System"),
                ],
                max_length=32,
            ),
        ),
        migrations.RunPython(rename_roles_forward, rename_roles_reverse),
        migrations.AddField(
            model_name="report",
            name="awaiting_call_center_response",
            field=models.BooleanField(default=False),
        ),
    ]
