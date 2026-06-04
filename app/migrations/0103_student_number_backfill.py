# Safe client requirement migration for Bayan Learning Center.
# Adds a visible 6-digit student ID without changing existing primary keys or reg_no values.

from django.db import migrations, models


def backfill_student_numbers(apps, schema_editor):
    Student = apps.get_model('app', 'Student')
    used = set()
    next_number = 100001

    for student in Student.objects.order_by('id').only('id', 'student_number').iterator():
        existing = str(getattr(student, 'student_number', '') or '').strip()
        if existing.isdigit() and len(existing) == 6 and existing not in used:
            used.add(existing)
            continue

        while f'{next_number:06d}' in used:
            next_number += 1
        assigned = f'{next_number:06d}'
        used.add(assigned)
        Student.objects.filter(pk=student.pk).update(student_number=assigned)
        next_number += 1


def reverse_student_numbers(apps, schema_editor):
    # Keep generated numbers on rollback unless the field itself is removed by Django.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0102_fix_django_admin_log_charset'),
    ]

    operations = [
        migrations.AddField(
            model_name='student',
            name='student_number',
            field=models.CharField(blank=True, db_index=True, max_length=6, null=True, unique=True),
        ),
        migrations.RunPython(backfill_student_numbers, reverse_student_numbers),
    ]
