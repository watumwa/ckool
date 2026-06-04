from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0052_result_verification_settings_and_flags'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='ResultBatch',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(choices=[('DRAFT', 'Draft'), ('PENDING', 'Pending Verification'), ('VERIFIED', 'Verified'), ('FLAGGED', 'Flagged')], default='DRAFT', max_length=10)),
                ('submitted_at', models.DateTimeField(blank=True, null=True)),
                ('verified_at', models.DateTimeField(blank=True, null=True)),
                ('assessment', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='result_batch', to='app.assessment')),
                ('submitted_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='submitted_batches', to=settings.AUTH_USER_MODEL)),
                ('verified_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='verified_batches', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='VerificationSample',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('dos_mark', models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True)),
                ('matched', models.BooleanField(null=True)),
                ('checked_at', models.DateTimeField(blank=True, null=True)),
                ('checked_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='checked_samples', to=settings.AUTH_USER_MODEL)),
                ('result', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='verification_sample', to='app.result')),
            ],
        ),
        migrations.AddField(
            model_name='result',
            name='batch',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='results', to='app.resultbatch'),
        ),
        migrations.AddField(
            model_name='result',
            name='status',
            field=models.CharField(choices=[('DRAFT', 'Draft'), ('PENDING', 'Pending Verification'), ('VERIFIED', 'Verified'), ('FLAGGED', 'Flagged')], default='DRAFT', max_length=10),
        ),
        migrations.RemoveField(
            model_name='result',
            name='is_boundary',
        ),
        migrations.RemoveField(
            model_name='result',
            name='is_outlier',
        ),
        migrations.RemoveField(
            model_name='result',
            name='is_sampled',
        ),
        migrations.RemoveField(
            model_name='result',
            name='verification_status',
        ),
        migrations.RemoveField(
            model_name='result',
            name='verified_at',
        ),
        migrations.RemoveField(
            model_name='result',
            name='verified_by',
        ),
        migrations.RemoveField(
            model_name='resultverificationsetting',
            name='boundary_window',
        ),
        migrations.RemoveField(
            model_name='resultverificationsetting',
            name='enable_boundary',
        ),
        migrations.RemoveField(
            model_name='resultverificationsetting',
            name='enable_outlier',
        ),
        migrations.RemoveField(
            model_name='resultverificationsetting',
            name='enable_sampling',
        ),
        migrations.RemoveField(
            model_name='resultverificationsetting',
            name='outlier_percent',
        ),
        migrations.RemoveField(
            model_name='resultverificationsetting',
            name='pass_mark_percent',
        ),
        migrations.AddField(
            model_name='resultverificationsetting',
            name='tolerance_marks',
            field=models.DecimalField(decimal_places=2, default=1.0, max_digits=5),
        ),
        migrations.AlterField(
            model_name='resultverificationsetting',
            name='sample_percent',
            field=models.DecimalField(decimal_places=2, default=5.0, max_digits=5),
        ),
    ]
