from django.db import migrations


FORWARD_SQL = """
CREATE OR REPLACE FUNCTION reports_guard_report_status_transition()
RETURNS trigger AS $$
DECLARE
    required_actor_role text := NULLIF(btrim(COALESCE(current_setting('app.current_user_role', TRUE), '')), '');
BEGIN
    IF NEW.status IS DISTINCT FROM OLD.status
       AND (required_actor_role IS NULL OR NOT EXISTS (
            SELECT 1
            FROM reports_allowedtransition transition
            WHERE transition.from_status = OLD.status
              AND transition.to_status = NEW.status
              AND transition.actor_role = required_actor_role
       )) THEN
        RAISE EXCEPTION 'Status transition % -> % is not allowed for role %',
            OLD.status, NEW.status, COALESCE(required_actor_role, '');
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS reports_guard_report_status_transition ON reports_report;
CREATE TRIGGER reports_guard_report_status_transition
BEFORE UPDATE OF status ON reports_report
FOR EACH ROW
EXECUTE FUNCTION reports_guard_report_status_transition();

CREATE OR REPLACE FUNCTION reports_guard_report_status_insert()
RETURNS trigger AS $$
BEGIN
    IF NEW.status IS DISTINCT FROM 'SUBMITTED' THEN
        RAISE EXCEPTION 'New reports must have SUBMITTED status';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS reports_guard_report_status_insert ON reports_report;
CREATE TRIGGER reports_guard_report_status_insert
BEFORE INSERT ON reports_report
FOR EACH ROW
EXECUTE FUNCTION reports_guard_report_status_insert();

CREATE OR REPLACE FUNCTION reports_guard_status_history_append_only()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'Status history is append-only';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS reports_guard_status_history_append_only ON reports_statushistory;
CREATE TRIGGER reports_guard_status_history_append_only
BEFORE UPDATE OR DELETE ON reports_statushistory
FOR EACH ROW
EXECUTE FUNCTION reports_guard_status_history_append_only();
"""


REVERSE_SQL = """
DROP TRIGGER IF EXISTS reports_guard_status_history_append_only ON reports_statushistory;
DROP FUNCTION IF EXISTS reports_guard_status_history_append_only();

DROP TRIGGER IF EXISTS reports_guard_report_status_insert ON reports_report;
DROP FUNCTION IF EXISTS reports_guard_report_status_insert();

DROP TRIGGER IF EXISTS reports_guard_report_status_transition ON reports_report;
DROP FUNCTION IF EXISTS reports_guard_report_status_transition();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("reports", "0004_seed_allowed_transitions"),
    ]

    operations = [
        migrations.RunSQL(sql=FORWARD_SQL, reverse_sql=REVERSE_SQL),
    ]
