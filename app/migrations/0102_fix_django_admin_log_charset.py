from django.db import migrations


def _table_exists(connection, table_name):
    with connection.cursor() as cursor:
        return table_name in connection.introspection.table_names(cursor)


def fix_django_admin_log_charset(apps, schema_editor):
    connection = schema_editor.connection
    if connection.vendor != "mysql":
        return

    table_name = "django_admin_log"
    if not _table_exists(connection, table_name):
        return

    # Some imported databases still carry the contrib admin log table as latin1,
    # which breaks saves whenever object_repr contains Arabic or other utf8mb4 text.
    schema_editor.execute(
        f"ALTER TABLE `{table_name}` CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
    )


def noop_reverse(apps, schema_editor):
    return


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("app", "0101_payment_fee_category_payment_notes_and_more"),
    ]

    operations = [
        migrations.RunPython(fix_django_admin_log_charset, reverse_code=noop_reverse),
    ]
