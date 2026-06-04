from django.core.management.base import BaseCommand
from app.models.students import Student


class Command(BaseCommand):
    help = "Backfill missing 6-digit student IDs without altering existing reg_no values."

    def add_arguments(self, parser):
        parser.add_argument(
            "--start",
            type=int,
            default=100001,
            help="First number to use when assigning missing IDs. Default: 100001",
        )

    def handle(self, *args, **options):
        next_number = options["start"]
        used = set(
            str(value).strip()
            for value in Student.objects.exclude(student_number__isnull=True)
            .exclude(student_number="")
            .values_list("student_number", flat=True)
            if str(value or "").strip().isdigit()
        )
        updated = 0

        for student in Student.objects.order_by("id").iterator():
            current = str(student.student_number or "").strip()
            if current.isdigit() and len(current) == 6:
                continue

            while f"{next_number:06d}" in used:
                next_number += 1
            student.student_number = f"{next_number:06d}"
            student.save(update_fields=["student_number"])
            used.add(student.student_number)
            updated += 1
            next_number += 1

        self.stdout.write(self.style.SUCCESS(f"Backfilled {updated} student number(s)."))
