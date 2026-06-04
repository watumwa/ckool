from django.db import migrations


def _column_names(connection, table_name):
    with connection.cursor() as cursor:
        description = connection.introspection.get_table_description(cursor, table_name)
    return {col.name for col in description}


def drop_stale_section_report_template_slug(apps, schema_editor):
    connection = schema_editor.connection
    Section = apps.get_model("app", "Section")
    table_name = Section._meta.db_table

    with connection.cursor() as cursor:
        tables = connection.introspection.table_names(cursor)
    if table_name not in tables:
        return

    if "report_template_slug" not in _column_names(connection, table_name):
        return

    quoted_table = schema_editor.quote_name(table_name)
    quoted_column = schema_editor.quote_name("report_template_slug")
    schema_editor.execute(f"ALTER TABLE {quoted_table} DROP COLUMN {quoted_column}")


def noop_reverse(apps, schema_editor):
    return


class Migration(migrations.Migration):
    dependencies = [
        ("app", "0098_force_add_class_stream_lock_flag"),
    ]

    operations = [
        migrations.RunPython(drop_stale_section_report_template_slug, reverse_code=noop_reverse),
    ]
