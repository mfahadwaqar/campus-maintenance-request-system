from django.db import migrations, models


def rename_roles_forward(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    User.objects.filter(role="TECHNICIAN").update(role="TECHNICIAN_CONTRACTOR")
    User.objects.filter(role="OFFICER").update(role="CALL_CENTER_STAFF")


def rename_roles_reverse(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    User.objects.filter(role="TECHNICIAN_CONTRACTOR").update(role="TECHNICIAN")
    User.objects.filter(role="CALL_CENTER_STAFF").update(role="OFFICER")


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0003_seed_room_locations"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="user",
            name="user_role_valid",
        ),
        migrations.RemoveConstraint(
            model_name="user",
            name="user_technician_has_unit",
        ),
        migrations.AlterField(
            model_name="user",
            name="role",
            field=models.CharField(
                blank=True,
                choices=[
                    ("RESIDENT", "Resident"),
                    ("CALL_CENTER_STAFF", "Call Center Staff"),
                    ("TECHNICIAN_CONTRACTOR", "Technician/Contractor"),
                ],
                max_length=32,
                null=True,
            ),
        ),
        migrations.RunPython(rename_roles_forward, rename_roles_reverse),
        migrations.AddConstraint(
            model_name="user",
            constraint=models.CheckConstraint(
                condition=models.Q(role__isnull=True)
                | models.Q(
                    role__in=[
                        "RESIDENT",
                        "CALL_CENTER_STAFF",
                        "TECHNICIAN_CONTRACTOR",
                    ]
                ),
                name="user_role_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="user",
            constraint=models.CheckConstraint(
                condition=~models.Q(role="TECHNICIAN_CONTRACTOR") | models.Q(unit__isnull=False),
                name="user_technician_has_unit",
            ),
        ),
    ]
