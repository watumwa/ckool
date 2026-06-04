from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("app", "0093_remove_tenancy_models"),
    ]

    operations = [
        migrations.DeleteModel(
            name="PayrollAdjustment",
        ),
        migrations.DeleteModel(
            name="PayrollLine",
        ),
        migrations.DeleteModel(
            name="PayrollRun",
        ),
        migrations.DeleteModel(
            name="EmploymentRecord",
        ),
        migrations.DeleteModel(
            name="StaffCertification",
        ),
        migrations.DeleteModel(
            name="StaffHRDocument",
        ),
        migrations.DeleteModel(
            name="StaffLicense",
        ),
        migrations.DeleteModel(
            name="StaffProfileExtra",
        ),
        migrations.DeleteModel(
            name="StaffQualification",
        ),
    ]
