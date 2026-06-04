from django.db import migrations


def normalize_school_setting_default_level(apps, schema_editor):
    SchoolSetting = apps.get_model("app", "SchoolSetting")
    db_alias = schema_editor.connection.alias

    for setting in SchoolSetting.objects.using(db_alias).all():
        enabled_levels = []
        if setting.offers_primary:
            enabled_levels.append("PRIMARY")
        if setting.offers_secondary_lower:
            enabled_levels.append("SECONDARY_LOWER")
        if setting.offers_secondary_upper:
            enabled_levels.append("SECONDARY_UPPER")

        if not enabled_levels:
            enabled_levels = ["PRIMARY"]

        if setting.education_level not in enabled_levels:
            setting.education_level = enabled_levels[0]
            setting.save(using=db_alias, update_fields=["education_level"])


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0072_schoolsetting_offers_primary_and_more"),
    ]

    operations = [
        migrations.RunPython(
            normalize_school_setting_default_level,
            migrations.RunPython.noop,
        ),
    ]
