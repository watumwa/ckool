from django.db import migrations


def _column_names(connection, table_name):
    with connection.cursor() as cursor:
        description = connection.introspection.get_table_description(cursor, table_name)
    return {col.name for col in description}


def add_lock_flag_if_missing(apps, schema_editor):
    connection = schema_editor.connection
    AcademicClassStream = apps.get_model("app", "AcademicClassStream")
    table_name = AcademicClassStream._meta.db_table

    with connection.cursor() as cursor:
        tables = connection.introspection.table_names(cursor)
    if table_name not in tables:
        return

    if "is_timetable_locked" in _column_names(connection, table_name):
        return

    field = AcademicClassStream._meta.get_field("is_timetable_locked")
    schema_editor.add_field(AcademicClassStream, field)


def noop_reverse(apps, schema_editor):
    return


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0096_reconcile_schema_drift"),
    ]

    operations = [
        migrations.RunPython(add_lock_flag_if_missing, reverse_code=noop_reverse),
    ]
