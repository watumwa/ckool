from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class CreateModelIfMissing(migrations.CreateModel):
    """Create a model table only when it does not already exist."""

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        model = to_state.apps.get_model(app_label, self.name)
        table_name = model._meta.db_table

        with schema_editor.connection.cursor() as cursor:
            if table_name in schema_editor.connection.introspection.table_names(cursor):
                return

        return super().database_forwards(app_label, schema_editor, from_state, to_state)


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("app", "0059_alter_announcement_audience_alter_event_audience_and_more"),
    ]

    operations = [
        CreateModelIfMissing(
            name="MessageThreadArchive",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("archived_at", models.DateTimeField(auto_now_add=True)),
                ("thread", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="archive_entries", to="app.messagethread")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="archived_message_threads", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "unique_together": {("thread", "user")},
            },
        ),
    ]
