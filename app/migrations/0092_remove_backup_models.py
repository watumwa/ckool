from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0091_tenantinvoice_tenantinvoice_tenant_invoice_due_uniq"),
    ]

    operations = [
        migrations.DeleteModel(
            name="BackupLog",
        ),
        migrations.DeleteModel(
            name="BackupConfiguration",
        ),
    ]
