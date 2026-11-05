from importlib import import_module

from django.db import migrations


def reinstall_private_broadcast(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        migration = import_module("core.migrations.0018_conference_broadcast")
        schema_editor.execute(migration.INSTALL_SQL, params=None)


class Migration(migrations.Migration):
    dependencies = [("core", "0018_conference_broadcast")]

    operations = [migrations.RunPython(reinstall_private_broadcast, migrations.RunPython.noop)]
