from django.db import migrations


INSTALL_SQL = r"""
DROP POLICY IF EXISTS d10_conference_broadcast_select ON realtime.messages;
CREATE POLICY d10_conference_broadcast_select
ON realtime.messages
FOR SELECT
TO authenticated
USING (
    extension = 'broadcast'
    AND split_part((SELECT realtime.topic()), ':', 1) = 'conference'
    AND split_part((SELECT realtime.topic()), ':', 2) = 'tenant'
    AND split_part((SELECT realtime.topic()), ':', 3) = (SELECT auth.jwt() ->> 'tenant_id')
    AND split_part((SELECT realtime.topic()), ':', 4) = 'unit'
    AND COALESCE((SELECT auth.jwt() -> 'unit_ids'), '[]'::jsonb)
        @> pg_catalog.jsonb_build_array(split_part((SELECT realtime.topic()), ':', 5)::bigint)
    AND split_part((SELECT realtime.topic()), ':', 6) = 'competency'
    AND split_part((SELECT realtime.topic()), ':', 7) = (SELECT auth.jwt() ->> 'competency_id')
);

CREATE OR REPLACE FUNCTION public.d10_broadcast_conference_event_change()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    row_tenant_id bigint;
    row_unit_id bigint;
    row_competency_id bigint;
    old_topic text;
    new_topic text;
BEGIN
    IF TG_OP = 'DELETE' THEN
        row_tenant_id := OLD.tenant_id;
        row_unit_id := OLD.unit_id;
        row_competency_id := OLD.competency_id;
    ELSE
        row_tenant_id := NEW.tenant_id;
        row_unit_id := NEW.unit_id;
        row_competency_id := NEW.competency_id;
    END IF;

    new_topic := 'conference:tenant:' || row_tenant_id::text
        || ':unit:' || row_unit_id::text
        || ':competency:' || row_competency_id::text;

    IF TG_OP = 'UPDATE' THEN
        old_topic := 'conference:tenant:' || OLD.tenant_id::text
            || ':unit:' || OLD.unit_id::text
            || ':competency:' || OLD.competency_id::text;
        IF old_topic IS DISTINCT FROM new_topic THEN
            BEGIN
                PERFORM realtime.send(
                    pg_catalog.jsonb_build_object('type', 'conference_refresh'),
                    'conference.changed',
                    old_topic,
                    true
                );
            EXCEPTION WHEN OTHERS THEN
                RAISE WARNING 'D10 conference broadcast failed (SQLSTATE %).', SQLSTATE;
            END;
        END IF;
    END IF;

    BEGIN
        PERFORM realtime.send(
            pg_catalog.jsonb_build_object('type', 'conference_refresh'),
            'conference.changed',
            new_topic,
            true
        );
    EXCEPTION WHEN OTHERS THEN
        -- A signal failure must never roll back a valid payroll event.
        RAISE WARNING 'D10 conference broadcast failed (SQLSTATE %).', SQLSTATE;
    END;

    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS d10_conference_event_broadcast ON public.core_fieldevent;
CREATE TRIGGER d10_conference_event_broadcast
AFTER INSERT OR UPDATE OR DELETE ON public.core_fieldevent
FOR EACH ROW
EXECUTE FUNCTION public.d10_broadcast_conference_event_change();
"""

UNINSTALL_SQL = r"""
DROP TRIGGER IF EXISTS d10_conference_event_broadcast ON public.core_fieldevent;
DROP FUNCTION IF EXISTS public.d10_broadcast_conference_event_change();
DROP POLICY IF EXISTS d10_conference_broadcast_select ON realtime.messages;
"""


def install_realtime_broadcast(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(INSTALL_SQL, params=None)


def uninstall_realtime_broadcast(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(UNINSTALL_SQL, params=None)


class Migration(migrations.Migration):
    dependencies = [("core", "0017_admission_conversion")]

    operations = [migrations.RunPython(install_realtime_broadcast, uninstall_realtime_broadcast)]
