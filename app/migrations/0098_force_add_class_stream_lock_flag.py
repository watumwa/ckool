from django.db import migrations


def _column_names(connection, table_name):
    with connection.cursor() as cursor:
        description = connection.introspection.get_table_description(cursor, table_name)
    return {col.name for col in description}


def force_add_lock_flag_if_missing(apps, schema_editor):
    connection = schema_editor.connection
    AcademicClassStream = apps.get_model("app", "AcademicClassStream")
    table_name = AcademicClassStream._meta.db_table

    with connection.cursor() as cursor:
        tables = connection.introspection.table_names(cursor)
    if table_name not in tables:
        return

    if "is_timetable_locked" in _column_names(connection, table_name):
        return

    quoted_table = schema_editor.quote_name(table_name)
    quoted_col = schema_editor.quote_name("is_timetable_locked")

    if connection.vendor == "sqlite":
        schema_editor.execute(
            f"ALTER TABLE {quoted_table} ADD COLUMN {quoted_col} INTEGER NOT NULL DEFAULT 0"
        )
    else:
        schema_editor.execute(
            f"ALTER TABLE {quoted_table} ADD COLUMN {quoted_col} BOOLEAN NOT NULL DEFAULT FALSE"
        )


def noop_reverse(apps, schema_editor):
    return


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0097_reconcile_class_stream_lock_flag"),
    ]

    operations = [
        migrations.RunPython(force_add_lock_flag_if_missing, reverse_code=noop_reverse),
    ]
