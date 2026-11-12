from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("reports", "0001_initial")]

    operations = [
        migrations.RunSQL(
            sql="""
            ALTER TABLE reports_report
            ADD CONSTRAINT report_subcategory_category_fk
            FOREIGN KEY (subcategory_id, category_id)
            REFERENCES reports_subcategory (id, category_id)
            """,
            reverse_sql="ALTER TABLE reports_report DROP CONSTRAINT report_subcategory_category_fk",
        ),
    ]
