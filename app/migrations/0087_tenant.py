from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("app", "0086_alter_assessmenttype_weight"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Tenant",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=160, unique=True)),
                ("slug", models.SlugField(max_length=80, unique=True)),
                (
                    "school_type",
                    models.CharField(
                        choices=[
                            ("PRIMARY", "Primary"),
                            ("SECONDARY", "Secondary"),
                            ("BOTH", "Primary + Secondary"),
                        ],
                        default="PRIMARY",
                        max_length=20,
                    ),
                ),
                ("country", models.CharField(blank=True, default="", max_length=80)),
                ("district", models.CharField(blank=True, default="", max_length=80)),
                ("contact_email", models.EmailField(blank=True, default="", max_length=254)),
                ("contact_phone", models.CharField(blank=True, default="", max_length=40)),
                ("subdomain", models.SlugField(max_length=80, unique=True)),
                (
                    "host",
                    models.CharField(
                        help_text="Fully-qualified host for this tenant.",
                        max_length=255,
                        unique=True,
                    ),
                ),
                (
                    "database_mode",
                    models.CharField(
                        choices=[("SHARED", "Shared Database"), ("DEDICATED", "Dedicated Database")],
                        default="DEDICATED",
                        max_length=20,
                    ),
                ),
                ("db_alias", models.CharField(max_length=120, unique=True)),
                ("db_config", models.JSONField(blank=True, default=dict)),
                ("hosting_region", models.CharField(blank=True, default="auto", max_length=40)),
                (
                    "subscription_plan",
                    models.CharField(
                        choices=[
                            ("STARTER", "Starter"),
                            ("PROFESSIONAL", "Professional"),
                            ("ENTERPRISE", "Enterprise"),
                        ],
                        default="STARTER",
                        max_length=20,
                    ),
                ),
                ("trial_ends_at", models.DateTimeField(blank=True, null=True)),
                ("academic_config", models.JSONField(blank=True, default=dict)),
                ("feature_flags", models.JSONField(blank=True, default=dict)),
                ("branding", models.JSONField(blank=True, default=dict)),
                ("admin_full_name", models.CharField(blank=True, default="", max_length=120)),
                ("admin_email", models.EmailField(blank=True, default="", max_length=254)),
                (
                    "provisioning_status",
                    models.CharField(
                        choices=[
                            ("PENDING", "Pending"),
                            ("PROVISIONING", "Provisioning"),
                            ("ACTIVE", "Active"),
                            ("FAILED", "Failed"),
                        ],
                        default="PENDING",
                        max_length=20,
                    ),
                ),
                ("provisioning_log", models.JSONField(blank=True, default=list)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="tenants_created",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "app_tenant",
                "ordering": ("-created_at", "-id"),
            },
        ),
        migrations.AddIndex(
            model_name="tenant",
            index=models.Index(fields=["host"], name="tenant_host_idx"),
        ),
        migrations.AddIndex(
            model_name="tenant",
            index=models.Index(fields=["subdomain"], name="tenant_subdomain_idx"),
        ),
        migrations.AddIndex(
            model_name="tenant",
            index=models.Index(fields=["db_alias"], name="tenant_db_alias_idx"),
        ),
        migrations.AddIndex(
            model_name="tenant",
            index=models.Index(fields=["provisioning_status"], name="tenant_prov_status_idx"),
        ),
    ]

