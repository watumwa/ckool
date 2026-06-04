"""Finance service for the admin control-tower dashboard."""

from __future__ import annotations

from datetime import timedelta

from django.db.models import DecimalField, ExpressionWrapper, F, Sum
from django.utils import timezone

from app.models.fees_payment import Payment, StudentBillItem
from app.models.finance import Expenditure, ExpenditureItem
from app.services.level_scope import get_level_academic_classes_queryset
from app.services.school_level import get_active_school_level


def _percent(part: float, whole: float) -> float:
    if not whole:
        return 0
    return round((part / whole) * 100, 1)


def get_finance_context(request, scope):
    """Financial KPIs, debt risk, and recent transaction visibility."""
    current_year = scope.get("current_year")
    current_term = scope.get("current_term")
    active_level = get_active_school_level(request)
    today = timezone.localdate()

    total_expected = 0
    total_collected = 0
    outstanding_total = 0
    fees_collected_today = 0
    fees_collected_week = 0
    class_outstanding_rows = []
    top_debtors = []
    recent_payments = []
    recent_expenditures = []
    payment_method_breakdown = []
    daily_collection_rows = []
    expenses_total = 0

    if current_year and current_term:
        term_scoped_academic_classes = get_level_academic_classes_queryset(
            active_level=active_level
        ).filter(
            academic_year=current_year,
            term=current_term,
        )
        total_expected = (
            StudentBillItem.objects.filter(
                bill__academic_class__in=term_scoped_academic_classes,
                bill__academic_class__academic_year=current_year,
                bill__academic_class__term=current_term,
                bill__student__is_active=True,
            ).aggregate(total=Sum("amount"))["total"]
            or 0
        )
        payment_scope = Payment.objects.filter(
            bill__academic_class__in=term_scoped_academic_classes,
            bill__academic_class__academic_year=current_year,
            bill__academic_class__term=current_term,
            bill__student__is_active=True,
        )
        total_collected = payment_scope.aggregate(total=Sum("amount"))["total"] or 0
        outstanding_total = max(total_expected - total_collected, 0)
        fees_collected_today = (
            payment_scope.filter(payment_date=today).aggregate(total=Sum("amount"))["total"] or 0
        )
        fees_collected_week = (
            payment_scope.filter(payment_date__gte=today - timedelta(days=6)).aggregate(
                total=Sum("amount")
            )["total"]
            or 0
        )

        billed_by_class = list(
            StudentBillItem.objects.filter(
                bill__academic_class__in=term_scoped_academic_classes,
                bill__academic_class__academic_year=current_year,
                bill__academic_class__term=current_term,
                bill__student__is_active=True,
            )
            .values("bill__academic_class_id", "bill__academic_class__Class__name")
            .annotate(total_billed=Sum("amount"))
            .order_by("bill__academic_class__Class__name")
        )
        paid_by_class = list(
            payment_scope.values("bill__academic_class_id").annotate(total_paid=Sum("amount"))
        )
        paid_class_map = {
            row["bill__academic_class_id"]: row["total_paid"] or 0 for row in paid_by_class
        }
        for row in billed_by_class:
            class_id = row["bill__academic_class_id"]
            total_billed = row["total_billed"] or 0
            total_paid = paid_class_map.get(class_id, 0)
            balance = max(total_billed - total_paid, 0)
            class_outstanding_rows.append(
                {
                    "class_name": row["bill__academic_class__Class__name"] or "Unknown",
                    "total_billed": total_billed,
                    "total_paid": total_paid,
                    "balance": balance,
                }
            )
        class_outstanding_rows = sorted(
            class_outstanding_rows, key=lambda row: row["balance"], reverse=True
        )

        billed_by_student = list(
            StudentBillItem.objects.filter(
                bill__academic_class__in=term_scoped_academic_classes,
                bill__academic_class__academic_year=current_year,
                bill__academic_class__term=current_term,
                bill__student__is_active=True,
            )
            .values(
                "bill__student_id",
                "bill__student__student_name",
                "bill__student__student_number",
                "bill__student__reg_no",
                "bill__student__current_class__name",
            )
            .annotate(total_billed=Sum("amount"))
        )
        paid_by_student = list(
            payment_scope.values("bill__student_id").annotate(total_paid=Sum("amount"))
        )
        paid_student_map = {
            row["bill__student_id"]: row["total_paid"] or 0 for row in paid_by_student
        }
        for row in billed_by_student:
            student_id = row["bill__student_id"]
            total_billed = row["total_billed"] or 0
            total_paid = paid_student_map.get(student_id, 0)
            balance = max(total_billed - total_paid, 0)
            if balance:
                top_debtors.append(
                    {
                        "student_id": student_id,
                        "student_name": row["bill__student__student_name"] or "Unknown",
                        "reg_no": row.get("bill__student__student_number") or row.get("bill__student__reg_no") or "-",
                        "class_name": row["bill__student__current_class__name"] or "-",
                        "balance": balance,
                    }
                )
        top_debtors = sorted(top_debtors, key=lambda row: row["balance"], reverse=True)[:10]

        recent_payments = list(
            payment_scope.select_related("bill__student")
            .order_by("-payment_date", "-id")[:10]
        )
        payment_method_breakdown = list(
            payment_scope.values("payment_method")
            .annotate(total=Sum("amount"))
            .order_by("-total")
        )

        week_start = today - timedelta(days=6)
        raw_daily = list(
            payment_scope.filter(payment_date__range=(week_start, today))
            .values("payment_date")
            .annotate(total=Sum("amount"))
            .order_by("payment_date")
        )
        daily_map = {row["payment_date"]: row["total"] or 0 for row in raw_daily}
        cursor = week_start
        while cursor <= today:
            daily_collection_rows.append(
                {"label": cursor.strftime("%a"), "date": cursor, "amount": daily_map.get(cursor, 0)}
            )
            cursor = cursor + timedelta(days=1)

        if current_term.start_date and current_term.end_date:
            expenditure_scope = Expenditure.objects.filter(
                date_incurred__range=(current_term.start_date, current_term.end_date)
            )
        else:
            expenditure_scope = Expenditure.objects.all()

        recent_expenditures = list(
            expenditure_scope.select_related("vendor", "budget_item")
            .order_by("-date_incurred", "-id")[:10]
        )

        items_total = (
            ExpenditureItem.objects.filter(expenditure__in=expenditure_scope)
            .aggregate(
                total=Sum(
                    ExpressionWrapper(
                        F("quantity") * F("unit_cost"),
                        output_field=DecimalField(max_digits=14, decimal_places=2),
                    )
                )
            )["total"]
            or 0
        )
        vat_total = expenditure_scope.aggregate(total=Sum("vat"))["total"] or 0
        expenses_total = items_total + vat_total

    return {
        "finance_total_expected": total_expected,
        "finance_total_collected": total_collected,
        "finance_outstanding_total": outstanding_total,
        "finance_collection_rate": _percent(total_collected, total_expected),
        "finance_fees_collected_today": fees_collected_today,
        "finance_fees_collected_week": fees_collected_week,
        "finance_class_outstanding_rows": class_outstanding_rows,
        "finance_top_debtors": top_debtors,
        "finance_recent_payments": recent_payments,
        "finance_recent_expenditures": recent_expenditures,
        "finance_payment_method_breakdown": payment_method_breakdown,
        "finance_daily_collection_rows": daily_collection_rows,
        "finance_expenses_total": expenses_total,
    }
