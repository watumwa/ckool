from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings


class CreateModelIfMissing(migrations.CreateModel):
    """Create a model table only when it does not already exist."""

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        model = to_state.apps.get_model(app_label, self.name)
        table_name = model._meta.db_table

        with schema_editor.connection.cursor() as cursor:
            if table_name in schema_editor.connection.introspection.table_names(cursor):
                return

        return super().database_forwards(app_label, schema_editor, from_state, to_state)


class AddFieldIfMissing(migrations.AddField):
    """Add a field only when the target column is missing."""

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        model = to_state.apps.get_model(app_label, self.model_name)
        table_name = model._meta.db_table
        field = model._meta.get_field(self.name)
        column_name = field.column

        with schema_editor.connection.cursor() as cursor:
            if table_name not in schema_editor.connection.introspection.table_names(cursor):
                return super().database_forwards(app_label, schema_editor, from_state, to_state)
            existing_columns = {
                col.name
                for col in schema_editor.connection.introspection.get_table_description(cursor, table_name)
            }

        if column_name in existing_columns:
            return

        return super().database_forwards(app_label, schema_editor, from_state, to_state)


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0051_alter_academicclassstream_class_teacher_signature'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        CreateModelIfMissing(
            name='ResultVerificationSetting',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('pass_mark_percent', models.DecimalField(decimal_places=2, default=50.0, max_digits=5)),
                ('boundary_window', models.DecimalField(decimal_places=2, default=5.0, max_digits=5)),
                ('sample_percent', models.DecimalField(decimal_places=2, default=10.0, max_digits=5)),
                ('outlier_percent', models.DecimalField(decimal_places=2, default=5.0, max_digits=5)),
                ('enable_sampling', models.BooleanField(default=True)),
                ('enable_boundary', models.BooleanField(default=True)),
                ('enable_outlier', models.BooleanField(default=True)),
            ],
        ),
        AddFieldIfMissing(
            model_name='result',
            name='verification_status',
            field=models.CharField(choices=[('PENDING', 'Pending'), ('FLAGGED', 'Flagged'), ('VERIFIED', 'Verified')], default='PENDING', max_length=10),
        ),
        AddFieldIfMissing(
            model_name='result',
            name='is_sampled',
            field=models.BooleanField(default=False),
        ),
        AddFieldIfMissing(
            model_name='result',
            name='is_boundary',
            field=models.BooleanField(default=False),
        ),
        AddFieldIfMissing(
            model_name='result',
            name='is_outlier',
            field=models.BooleanField(default=False),
        ),
        AddFieldIfMissing(
            model_name='result',
            name='verified_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        AddFieldIfMissing(
            model_name='result',
            name='verified_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='verified_results', to=settings.AUTH_USER_MODEL),
        ),
    ]
