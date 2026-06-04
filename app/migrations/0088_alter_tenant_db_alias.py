from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("app", "0087_tenant"),
    ]

    operations = [
        migrations.AlterField(
            model_name="tenant",
            name="db_alias",
            field=models.CharField(max_length=120),
        ),
    ]
