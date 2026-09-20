from django.core.management import call_command
from django.db import migrations


def create_cache_table(apps, schema_editor):
    # Rate limiting and OTP attempt counts live in a database cache table.
    # Creating it here means an ordinary `manage.py migrate` (which every
    # deploy already runs) sets it up; createcachetable skips existing tables.
    call_command('createcachetable', database=schema_editor.connection.alias)


class Migration(migrations.Migration):
    # createcachetable manages its own schema changes, so run outside the
    # migration's transaction.
    atomic = False

    dependencies = [
        ('accounts', '0014_servicedocument_reupload_flag'),
    ]

    operations = [
        migrations.RunPython(create_cache_table, migrations.RunPython.noop),
    ]
