"""
Management command: seed_ledger_data

Creates sample StudentBillItem (charges) and Payment records for testing
the financial ledger. Safe to run multiple times — skips if data exists.

Usage:
    python manage.py seed_ledger_data
    python manage.py seed_ledger_data --students 10 --force
"""
import random
from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone

from app.models.classes import AcademicClass, Term
from app.models.fees_payment import BillItem, Payment, StudentBill, StudentBillItem
from app.models.students import Student


CATEGORIES = ["Tuition", "Transport", "Uniform", "Other"]
METHODS = ["Cash", "SchoolPay", "Bank", "Other"]
TUITION_AMOUNTS = [350_000, 400_000, 450_000, 500_000, 600_000]
TRANSPORT_AMOUNTS = [80_000, 100_000, 120_000]
UNIFORM_AMOUNTS = [50_000, 75_000, 100_000]


class Command(BaseCommand):
    help = "Seed sample ledger data (charges + payments) for testing."

    def add_arguments(self, parser):
        parser.add_argument("--students", type=int, default=5, help="Number of students to seed (default 5)")
        parser.add_argument("--force", action="store_true", help="Re-seed even if data already exists")

    def handle(self, *args, **options):
        n = options["students"]
        force = options["force"]

        if StudentBillItem.objects.exists() and not force:
            self.stdout.write(self.style.WARNING(
                "Ledger data already exists. Use --force to re-seed."
            ))
            return

        students = list(Student.objects.all()[:n])
        if not students:
            self.stdout.write(self.style.ERROR("No students found. Add students first."))
            return

        academic_class = AcademicClass.objects.select_related("term", "academic_year").first()
        if not academic_class:
            self.stdout.write(self.style.ERROR("No AcademicClass found. Set up classes first."))
            return

        bill_item, _ = BillItem.objects.get_or_create(
            item_name="School Fees",
            defaults={"category": "Tuition", "bill_duration": "Termly", "description": "Termly school fees"},
        )

        created_bills = 0
        created_charges = 0
        created_payments = 0
        today = timezone.now().date()

        for student in students:
            # Create bill
            bill, bill_created = StudentBill.objects.get_or_create(
                student=student,
                academic_class=academic_class,
                defaults={"due_date": today + timedelta(days=30), "status": "Unpaid"},
            )
            if bill_created:
                created_bills += 1

            # Tuition charge
            charge_date = today - timedelta(days=random.randint(30, 90))
            tuition_amount = Decimal(random.choice(TUITION_AMOUNTS))
            item, _ = StudentBillItem.objects.get_or_create(
                bill=bill,
                bill_item=bill_item,
                defaults={
                    "description": "Tuition fees",
                    "amount": tuition_amount,
                    "charge_date": charge_date,
                    "fee_category": "Tuition",
                    "notes": "Termly tuition",
                },
            )
            if _:
                created_charges += 1

            # Optional transport charge
            if random.random() > 0.4:
                transport_item, _ = BillItem.objects.get_or_create(
                    item_name="Transport",
                    defaults={"category": "Transport", "bill_duration": "Termly", "description": "Transport fees"},
                )
                t_amount = Decimal(random.choice(TRANSPORT_AMOUNTS))
                _, new = StudentBillItem.objects.get_or_create(
                    bill=bill,
                    bill_item=transport_item,
                    defaults={
                        "description": "Transport fees",
                        "amount": t_amount,
                        "charge_date": charge_date,
                        "fee_category": "Transport",
                        "notes": "Termly transport",
                    },
                )
                if new:
                    created_charges += 1

            # Payment (partial or full)
            total_charged = bill.total_amount
            pay_fraction = random.choice([0, 0.3, 0.5, 0.75, 1.0])
            if pay_fraction > 0 and total_charged > 0:
                pay_amount = (total_charged * Decimal(str(pay_fraction))).quantize(Decimal("1"))
                pay_date = charge_date + timedelta(days=random.randint(1, 20))
                ref = f"PMT-SEED-{student.pk}-{bill.pk}-{int(pay_amount)}"
                if not Payment.objects.filter(reference_no=ref).exists():
                    Payment.objects.create(
                        bill=bill,
                        payment_date=pay_date,
                        amount=pay_amount,
                        payment_method=random.choice(METHODS),
                        fee_category="Tuition",
                        reference_no=ref,
                        recorded_by="seed_command",
                        notes="Sample payment",
                    )
                    created_payments += 1

        self.stdout.write(self.style.SUCCESS(
            f"Done. Bills: {created_bills}, Charges: {created_charges}, Payments: {created_payments}"
        ))
