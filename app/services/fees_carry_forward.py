from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from app.models.classes import AcademicClass, Class, Term
from app.models.fees_payment import BillItem, StudentBill, StudentBillItem


CARRY_FORWARD_ITEM_NAME = "Balance Brought Forward"
CARRY_FORWARD_SOURCE_MARKER = "CARRY_FORWARD_SOURCE_BILL"
CARRY_FORWARD_TARGET_MARKER = "CARRY_FORWARD_TARGET_BILL"


def money(value):
    try:
        return Decimal(str(value or 0))
    except Exception:
        return Decimal("0")


@dataclass
class CarryForwardRow:
    source_bill: StudentBill
    target_academic_class: AcademicClass | None
    outstanding: Decimal
    source_adjustment: StudentBillItem | None = None
    target_item: StudentBillItem | None = None

    @property
    def student(self):
        return self.source_bill.student

    @property
    def can_post(self):
        return self.outstanding > 0 and self.target_academic_class is not None


def get_or_create_carry_forward_bill_item():
    bill_item, _ = BillItem.objects.get_or_create(
        item_name=CARRY_FORWARD_ITEM_NAME,
        defaults={
            "category": "Other",
            "bill_duration": "None",
            "description": "Outstanding learner balance moved from a previous term.",
        },
    )
    return bill_item


def _source_marker(source_bill_id):
    return f"{CARRY_FORWARD_SOURCE_MARKER}:{source_bill_id}"


def _target_marker(target_bill_id):
    return f"{CARRY_FORWARD_TARGET_MARKER}:{target_bill_id}"


def _source_carry_adjustment_total(source_bill):
    total = (
        StudentBillItem.objects.filter(
            bill=source_bill,
            notes__contains=_source_marker(source_bill.id),
        ).aggregate(total=Sum("amount"))["total"]
        or 0
    )
    return money(total)


def outstanding_before_carry_forward(source_bill):
    # Existing source-side carry rows are negative adjustments. Add them back
    # before calculating what still needs to move.
    return money(source_bill.balance) - _source_carry_adjustment_total(source_bill)


def find_target_academic_class(source_bill, target_term, target_class_id=None):
    target_class = None
    if target_class_id:
        target_class = Class.objects.filter(pk=target_class_id).first()
    if not target_class:
        target_class = source_bill.academic_class.Class

    return (
        AcademicClass.objects.filter(
            academic_year=target_term.academic_year,
            term=target_term,
            Class=target_class,
        )
        .select_related("Class", "term", "academic_year", "section")
        .first()
    )


def build_carry_forward_preview(*, source_term, target_term, class_id="", active_students_only=True):
    source_bills = StudentBill.objects.filter(
        academic_class__term=source_term,
        academic_class__academic_year=source_term.academic_year,
    ).select_related(
        "student",
        "student__current_class",
        "academic_class",
        "academic_class__Class",
        "academic_class__term",
        "academic_class__academic_year",
    )
    if class_id:
        source_bills = source_bills.filter(academic_class__Class_id=class_id)
    if active_students_only:
        source_bills = source_bills.filter(student__is_active=True)

    rows = []
    for source_bill in source_bills.order_by("student__student_name", "id"):
        outstanding = outstanding_before_carry_forward(source_bill)
        if outstanding <= 0:
            continue
        rows.append(
            CarryForwardRow(
                source_bill=source_bill,
                target_academic_class=find_target_academic_class(source_bill, target_term),
                outstanding=outstanding,
            )
        )
    return rows


@transaction.atomic
def post_carry_forward(*, source_term, target_term, class_id="", active_students_only=True):
    bill_item = get_or_create_carry_forward_bill_item()
    rows = build_carry_forward_preview(
        source_term=source_term,
        target_term=target_term,
        class_id=class_id,
        active_students_only=active_students_only,
    )

    posted = []
    skipped = []
    today = timezone.localdate()

    for row in rows:
        if not row.can_post:
            skipped.append(row)
            continue

        target_bill, _ = StudentBill.objects.get_or_create(
            student=row.student,
            academic_class=row.target_academic_class,
            defaults={
                "due_date": getattr(target_term, "end_date", None),
                "status": "Unpaid",
            },
        )

        source_note = (
            f"{_source_marker(row.source_bill.id)}; {_target_marker(target_bill.id)}; "
            f"Moved to {row.target_academic_class}"
        )
        target_note = (
            f"{_source_marker(row.source_bill.id)}; {_target_marker(target_bill.id)}; "
            f"From {row.source_bill.academic_class}"
        )

        source_adjustment = (
            StudentBillItem.objects.filter(
                bill=row.source_bill,
                bill_item=bill_item,
                notes__contains=_source_marker(row.source_bill.id),
            )
            .order_by("id")
            .first()
        )
        if not source_adjustment:
            source_adjustment = StudentBillItem.objects.create(
                bill=row.source_bill,
                bill_item=bill_item,
                description=f"Balance carried forward to {row.target_academic_class}",
                amount=-row.outstanding,
                charge_date=getattr(source_term, "end_date", None) or today,
                fee_category="Other",
                notes=source_note,
            )
        elif source_adjustment.amount != -row.outstanding:
            source_adjustment.amount = -row.outstanding
            source_adjustment.description = f"Balance carried forward to {row.target_academic_class}"
            source_adjustment.charge_date = getattr(source_term, "end_date", None) or today
            source_adjustment.fee_category = "Other"
            source_adjustment.notes = source_note
            source_adjustment.save(update_fields=["amount", "description", "charge_date", "fee_category", "notes"])

        target_item = (
            StudentBillItem.objects.filter(
                bill=target_bill,
                bill_item=bill_item,
                notes__contains=_source_marker(row.source_bill.id),
            )
            .order_by("id")
            .first()
        )
        if not target_item:
            target_item = StudentBillItem.objects.create(
                bill=target_bill,
                bill_item=bill_item,
                description=f"Balance brought forward from {row.source_bill.academic_class}",
                amount=row.outstanding,
                charge_date=getattr(target_term, "start_date", None) or today,
                fee_category="Other",
                notes=target_note,
            )
        elif target_item.amount != row.outstanding:
            target_item.amount = row.outstanding
            target_item.description = f"Balance brought forward from {row.source_bill.academic_class}"
            target_item.charge_date = getattr(target_term, "start_date", None) or today
            target_item.fee_category = "Other"
            target_item.notes = target_note
            target_item.save(update_fields=["amount", "description", "charge_date", "fee_category", "notes"])

        row.source_bill.refresh_from_db()
        target_bill.refresh_from_db()
        row.source_bill.status = "Paid" if money(row.source_bill.balance) <= 0 else "Unpaid"
        target_bill.status = "Paid" if money(target_bill.balance) <= 0 else "Unpaid"
        row.source_bill.save(update_fields=["status"])
        target_bill.save(update_fields=["status"])

        row.source_adjustment = source_adjustment
        row.target_item = target_item
        posted.append(row)

    return {
        "posted": posted,
        "skipped": skipped,
        "posted_count": len(posted),
        "skipped_count": len(skipped),
        "posted_total": sum((row.outstanding for row in posted), Decimal("0")),
    }
