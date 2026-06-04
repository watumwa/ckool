from django.db import migrations


def _table_exists(connection, table_name):
    with connection.cursor() as cursor:
        return table_name in connection.introspection.table_names(cursor)


def create_student_promotion_history_table_if_missing(apps, schema_editor):
    connection = schema_editor.connection
    StudentPromotionHistory = apps.get_model("app", "StudentPromotionHistory")
    table_name = StudentPromotionHistory._meta.db_table

    if _table_exists(connection, table_name):
        return

    schema_editor.create_model(StudentPromotionHistory)


def noop_reverse(apps, schema_editor):
    return


class Migration(migrations.Migration):
    dependencies = [
        ("app", "0099_drop_stale_section_report_template_slug"),
    ]

    operations = [
        migrations.RunPython(
            create_student_promotion_history_table_if_missing,
            reverse_code=noop_reverse,
        ),
    ]
