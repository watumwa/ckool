"""Reports center service for the admin control-tower dashboard."""

from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.models import User
from django.db.models import (
    Avg,
    Count,
    DecimalField,
    ExpressionWrapper,
    F,
    Max,
    Min,
    Q,
    Sum,
)
from django.db.models.functions import TruncDate, TruncMonth
from django.urls import reverse
from django.utils import timezone

from app.models.accounts import StaffAccount
from app.models.attendance import AttendanceRecord, AttendanceStatus
from app.models.audit import AuditLog
from app.models.fees_payment import Payment, StudentBillItem
from app.models.finance import Expenditure, ExpenditureItem, Transaction
from app.models.results import GradingSystem, Result, ResultBatch
from app.models.staffs import Role, Staff
from app.services.level_scope import (
    get_level_academic_classes_queryset,
    get_level_students_queryset,
    get_level_subjects_queryset,
)
from app.services.school_level import get_active_school_level


PRESENT_LIKE_STATUSES = [AttendanceStatus.PRESENT, AttendanceStatus.LATE]
ABSENT_LIKE_STATUSES = [AttendanceStatus.ABSENT, AttendanceStatus.EXCUSED]


def _to_decimal(value) -> Decimal:
    return Decimal(value or 0)


def _to_float(value) -> float:
    return float(value or 0)


def _to_int_param(raw_value: str | None):
    raw_value = (raw_value or "").strip()
    return int(raw_value) if raw_value.isdigit() else None


def _parse_date(raw_value: str | None):
    raw_value = (raw_value or "").strip()
    if not raw_value:
        return None
    try:
        return datetime.strptime(raw_value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _percent(part, whole) -> float:
    whole = _to_float(whole)
    if whole <= 0:
        return 0.0
    return round((_to_float(part) / whole) * 100, 1)


def _month_start(day: date) -> date:
    return date(day.year, day.month, 1)


def _shift_month(base_month: date, month_delta: int) -> date:
    month_index = (base_month.year * 12 + (base_month.month - 1)) + month_delta
    year = month_index // 12
    month = (month_index % 12) + 1
    return date(year, month, 1)


def _month_axis(end_date: date, *, months: int = 6):
    anchor = _month_start(end_date)
    return [_shift_month(anchor, -(months - 1 - idx)) for idx in range(months)]


def _normalize_month_key(value):
    if value is None:
        return None
    if hasattr(value, "date"):
        value = value.date()
    return _month_start(value)


def _audit_target_label(log: AuditLog) -> str:
    object_repr = (log.object_repr or "").strip()
    if object_repr:
        return object_repr
    if log.content_type_id:
        model_label = f"{log.content_type.app_label}.{log.content_type.model}"
        if log.object_id:
            return f"{model_label} ({log.object_id})"
        return model_label
    path = (log.path or "").strip()
    if path:
        return path
    return "System record"


def _audit_change_summary(log: AuditLog) -> str:
    changes = log.changes if isinstance(log.changes, dict) else {}
    action = (log.action or "").lower()

    if action == AuditLog.ACTION_UPDATE:
        changed_fields = [str(field) for field in changes.keys() if field not in {"old", "new"}]
        if not changed_fields:
            return "Updated record"
        preview = ", ".join(changed_fields[:3])
        if len(changed_fields) > 3:
            preview = f"{preview} (+{len(changed_fields) - 3} more)"
        return f"Fields changed: {preview}"

    if action == AuditLog.ACTION_CREATE:
        created_values = changes.get("new")
        if isinstance(created_values, dict):
            set_fields = [str(key) for key, value in created_values.items() if value not in (None, "", [], {})]
            if set_fields:
                preview = ", ".join(set_fields[:3])
                if len(set_fields) > 3:
                    preview = f"{preview} (+{len(set_fields) - 3} more)"
                return f"Created with: {preview}"
        return "Created record"

    if action == AuditLog.ACTION_DELETE:
        deleted_values = changes.get("old")
        if isinstance(deleted_values, dict):
            previous_fields = [str(key) for key, value in deleted_values.items() if value not in (None, "", [], {})]
            if previous_fields:
                preview = ", ".join(previous_fields[:3])
                if len(previous_fields) > 3:
                    preview = f"{preview} (+{len(previous_fields) - 3} more)"
                return f"Deleted record data: {preview}"
        return "Deleted record"

    return "-"


def _dir_size_mb(path: str) -> float:
    if not path or not os.path.exists(path):
        return 0.0
    total_size = 0
    for root, _, files in os.walk(path):
        for file_name in files:
            file_path = os.path.join(root, file_name)
            try:
                total_size += os.path.getsize(file_path)
            except OSError:
                continue
    return round(total_size / (1024 * 1024), 2)


def _expenditure_total(expenditure_queryset):
    item_total = (
        ExpenditureItem.objects.filter(expenditure__in=expenditure_queryset).aggregate(
            total=Sum(
                ExpressionWrapper(
                    F("quantity") * F("unit_cost"),
                    output_field=DecimalField(max_digits=14, decimal_places=2),
                )
            )
        )["total"]
        or Decimal("0")
    )
    vat_total = expenditure_queryset.aggregate(total=Sum("vat"))["total"] or Decimal("0")
    return _to_decimal(item_total) + _to_decimal(vat_total)


def _grade_for_score(score, grading_scale):
    score = _to_float(score)
    for band in grading_scale:
        if float(band.min_score) <= score <= float(band.max_score):
            return band.grade
    return "N/A"


def get_reports_context(request, scope):
    current_year = scope.get("current_year")
    current_term = scope.get("current_term")
    active_level = get_active_school_level(request)
    today = timezone.localdate()
    scoped_academic_classes = get_level_academic_classes_queryset(active_level=active_level)
    scoped_students_all = get_level_students_queryset(active_level=active_level)

    if current_year and current_term:
        term_scoped_academic_classes = scoped_academic_classes.filter(
            academic_year=current_year,
            term=current_term,
        )
        term_scoped_students = scoped_students_all.filter(
            academic_year=current_year,
            term=current_term,
        )
    else:
        term_scoped_academic_classes = scoped_academic_classes.none()
        term_scoped_students = scoped_students_all.none()

    class_options_source = term_scoped_academic_classes if term_scoped_academic_classes.exists() else scoped_academic_classes
    section_options_source = class_options_source
    student_options_source = term_scoped_students if term_scoped_students.exists() else scoped_students_all

    report_class_options = [
        {
            "id": row["Class_id"],
            "label": f"{row['Class__code'] or row['Class__name']} - {row['Class__name']}",
        }
        for row in class_options_source.values("Class_id", "Class__code", "Class__name")
        .distinct()
        .order_by("Class__name", "Class__code")
    ]
    report_section_options = [
        {"id": row["section_id"], "label": row["section__section_name"]}
        for row in section_options_source.values("section_id", "section__section_name")
        .distinct()
        .order_by("section__section_name")
    ]
    report_student_options = [
        {"id": row["id"], "name": row["student_name"], "reg_no": row.get("student_number") or row["reg_no"]}
        for row in student_options_source.values("id", "student_name", "student_number", "reg_no")
        .order_by("student_name")[:200]
    ]
    report_subject_options = [
        {"id": row["id"], "name": row["name"]}
        for row in get_level_subjects_queryset(active_level=active_level)
        .values("id", "name")
        .order_by("name")
    ]
    report_role_options = [
        {"name": role.name}
        for role in Role.objects.order_by("name")
    ]
    report_department_options = [
        item
        for item in Staff.objects.values_list("department", flat=True).distinct().order_by("department")
        if item
    ]

    report_links = [
        {
            "key": "fees",
            "label": "Fees Report",
            "description": "Transaction ledger with charge and payment level detail.",
            "url": reverse("payment_ledger"),
            "group": "Finance",
        },
        {
            "key": "financial_summary",
            "label": "Financial Summary",
            "description": "Summary financial position for the selected scope.",
            "url": reverse("financial_summary_report"),
            "group": "Finance",
        },
        {
            "key": "income_statement",
            "label": "Income Statement",
            "description": "Income and expense statement output.",
            "url": reverse("income_statement"),
            "group": "Finance",
        },
        {
            "key": "cash_flow",
            "label": "Cash Flow",
            "description": "Cash flow report and movement trends.",
            "url": reverse("cash_flow"),
            "group": "Finance",
        },
        {
            "key": "attendance",
            "label": "Attendance Report",
            "description": "Student/class attendance reports and tracking.",
            "url": reverse("class_attendance_report"),
            "group": "Attendance",
        },
        {
            "key": "academic",
            "label": "Academic Report",
            "description": "Performance analytics and report outputs.",
            "url": reverse("class_stream_filter"),
            "group": "Academics",
        },
        {
            "key": "bulk_cards",
            "label": "Bulk Result Cards",
            "description": "Generate report cards for whole classes.",
            "url": reverse("class_bulk_reports"),
            "group": "Academics",
        },
        {
            "key": "verification",
            "label": "Verification Monitor",
            "description": "Track pending and flagged verification tasks.",
            "url": reverse("verification_overview"),
            "group": "Quality Control",
        },
        {
            "key": "users",
            "label": "User & Access Report",
            "description": "Review users, permissions, and role assignments.",
            "url": reverse("user_list"),
            "group": "System",
        },
    ]
    report_links_map = {row["key"]: row for row in report_links}

    # ------------------------------------------------------------------
    # 1) Fees report
    # ------------------------------------------------------------------
    fees_class_id = _to_int_param(request.GET.get("fees_class"))
    fees_section_id = _to_int_param(request.GET.get("fees_section"))
    fees_student_id = _to_int_param(request.GET.get("fees_student"))

    fees_class_scope = term_scoped_academic_classes
    if fees_class_id:
        fees_class_scope = fees_class_scope.filter(Class_id=fees_class_id)
    if fees_section_id:
        fees_class_scope = fees_class_scope.filter(section_id=fees_section_id)

    fees_billed_qs = StudentBillItem.objects.filter(bill__academic_class__in=fees_class_scope)
    fees_paid_qs = Payment.objects.filter(bill__academic_class__in=fees_class_scope)
    if fees_student_id:
        fees_billed_qs = fees_billed_qs.filter(bill__student_id=fees_student_id)
        fees_paid_qs = fees_paid_qs.filter(bill__student_id=fees_student_id)

    fees_total_billed = _to_decimal(fees_billed_qs.aggregate(total=Sum("amount"))["total"])
    fees_total_paid = _to_decimal(fees_paid_qs.aggregate(total=Sum("amount"))["total"])
    fees_total_outstanding = max(fees_total_billed - fees_total_paid, Decimal("0"))
    fees_collection_percent = _percent(fees_total_paid, fees_total_billed)

    paid_by_student_map = {
        row["bill__student_id"]: _to_decimal(row["total_paid"])
        for row in fees_paid_qs.values("bill__student_id").annotate(total_paid=Sum("amount"))
    }

    fees_student_table_rows = []
    billed_by_student_rows = (
        fees_billed_qs.values(
            "bill__student_id",
            "bill__student__student_name",
            "bill__student__student_number",
                "bill__student__reg_no",
            "bill__student__current_class__code",
            "bill__student__current_class__name",
            "bill__student__stream__stream",
        )
        .annotate(total_billed=Sum("amount"))
        .order_by("bill__student__student_name")
    )
    for row in billed_by_student_rows:
        billed = _to_decimal(row["total_billed"])
        paid = paid_by_student_map.get(row["bill__student_id"], Decimal("0"))
        outstanding = max(billed - paid, Decimal("0"))
        if billed <= 0:
            status = "No Bills"
        elif paid <= 0:
            status = "Unpaid"
        elif outstanding <= 0:
            status = "Paid"
        else:
            status = "Partial"

        class_code = row["bill__student__current_class__code"] or row["bill__student__current_class__name"] or "-"
        stream_code = row["bill__student__stream__stream"] or ""
        fees_student_table_rows.append(
            {
                "student_id": row["bill__student_id"],
                "student_name": row["bill__student__student_name"] or "Unknown",
                "reg_no": row.get("bill__student__student_number") or row.get("bill__student__reg_no") or "-",
                "class_label": f"{class_code}{stream_code}".strip(),
                "fees_billed": billed,
                "fees_paid": paid,
                "outstanding": outstanding,
                "status": status,
            }
        )
    fees_student_table_rows = sorted(
        fees_student_table_rows,
        key=lambda item: (-_to_float(item["outstanding"]), item["student_name"]),
    )[:150]

    paid_by_class_map = {
        row["bill__academic_class_id"]: _to_decimal(row["total_paid"])
        for row in fees_paid_qs.values("bill__academic_class_id").annotate(total_paid=Sum("amount"))
    }
    fees_class_outstanding_rows = []
    for row in fees_billed_qs.values(
        "bill__academic_class_id",
        "bill__academic_class__Class__code",
        "bill__academic_class__Class__name",
    ).annotate(total_billed=Sum("amount")):
        total_billed = _to_decimal(row["total_billed"])
        total_paid = paid_by_class_map.get(row["bill__academic_class_id"], Decimal("0"))
        outstanding = max(total_billed - total_paid, Decimal("0"))
        class_label = row["bill__academic_class__Class__code"] or row["bill__academic_class__Class__name"] or "-"
        fees_class_outstanding_rows.append(
            {
                "class_id": row["bill__academic_class_id"],
                "class_label": class_label,
                "total_billed": total_billed,
                "total_paid": total_paid,
                "outstanding": outstanding,
            }
        )
    fees_class_outstanding_rows = sorted(
        fees_class_outstanding_rows,
        key=lambda item: -_to_float(item["outstanding"]),
    )

    fees_month_axis = _month_axis(today, months=6)
    fees_month_map = {}
    for row in fees_paid_qs.annotate(month=TruncMonth("payment_date")).values("month").annotate(total=Sum("amount")):
        month_key = _normalize_month_key(row["month"])
        if month_key:
            fees_month_map[month_key] = _to_decimal(row["total"])
    fees_month_labels = [month.strftime("%b %Y") for month in fees_month_axis]
    fees_month_values = [_to_float(fees_month_map.get(month, 0)) for month in fees_month_axis]

    # ------------------------------------------------------------------
    # Shared financial scope
    # ------------------------------------------------------------------
    payment_scope_classes = term_scoped_academic_classes if term_scoped_academic_classes.exists() else scoped_academic_classes
    term_payment_scope = Payment.objects.filter(bill__academic_class__in=payment_scope_classes)
    term_billed_total = _to_decimal(
        StudentBillItem.objects.filter(bill__academic_class__in=payment_scope_classes).aggregate(total=Sum("amount"))["total"]
    )
    term_paid_total = _to_decimal(term_payment_scope.aggregate(total=Sum("amount"))["total"])
    term_outstanding_receivables = max(term_billed_total - term_paid_total, Decimal("0"))

    if current_term and current_term.start_date and current_term.end_date:
        transaction_scope = Transaction.objects.filter(
            date__range=(current_term.start_date, current_term.end_date)
        )
        expenditure_scope = Expenditure.objects.filter(
            date_incurred__range=(current_term.start_date, current_term.end_date)
        )
    else:
        transaction_scope = Transaction.objects.all()
        expenditure_scope = Expenditure.objects.all()

    transaction_income_total = _to_decimal(
        transaction_scope.filter(transaction_type="Income").aggregate(total=Sum("amount"))["total"]
    )
    transaction_expense_total = _to_decimal(
        transaction_scope.filter(transaction_type="Expense").aggregate(total=Sum("amount"))["total"]
    )
    expenditure_total = _expenditure_total(expenditure_scope)

    # ------------------------------------------------------------------
    # 2) Financial summary
    # ------------------------------------------------------------------
    financial_total_income = term_paid_total + transaction_income_total
    financial_total_expenses = expenditure_total + transaction_expense_total
    financial_net_balance = financial_total_income - financial_total_expenses

    financial_summary_rows = [
        {
            "category": "Tuition & Fees Billed",
            "amount": term_billed_total,
            "notes": f"{current_year.academic_year if current_year else 'Current'} scope",
        },
        {
            "category": "Fees Paid",
            "amount": term_paid_total,
            "notes": "Student payment receipts",
        },
        {
            "category": "Other Income",
            "amount": transaction_income_total,
            "notes": "Income transactions ledger",
        },
        {
            "category": "Expenses",
            "amount": financial_total_expenses,
            "notes": "Expenditures + expense transactions",
        },
        {
            "category": "Net Balance",
            "amount": financial_net_balance,
            "notes": "Income minus expenses",
        },
    ]

    financial_month_axis = _month_axis(today, months=6)
    payment_month_map = {}
    for row in term_payment_scope.annotate(month=TruncMonth("payment_date")).values("month").annotate(total=Sum("amount")):
        month_key = _normalize_month_key(row["month"])
        if month_key:
            payment_month_map[month_key] = _to_decimal(row["total"])

    trans_income_month_map = {}
    for row in transaction_scope.filter(transaction_type="Income").annotate(month=TruncMonth("date")).values("month").annotate(total=Sum("amount")):
        month_key = _normalize_month_key(row["month"])
        if month_key:
            trans_income_month_map[month_key] = _to_decimal(row["total"])

    trans_expense_month_map = {}
    for row in transaction_scope.filter(transaction_type="Expense").annotate(month=TruncMonth("date")).values("month").annotate(total=Sum("amount")):
        month_key = _normalize_month_key(row["month"])
        if month_key:
            trans_expense_month_map[month_key] = _to_decimal(row["total"])

    exp_items_month_map = {}
    for row in ExpenditureItem.objects.filter(expenditure__in=expenditure_scope).annotate(
        month=TruncMonth("expenditure__date_incurred")
    ).values("month").annotate(
        total=Sum(
            ExpressionWrapper(
                F("quantity") * F("unit_cost"),
                output_field=DecimalField(max_digits=14, decimal_places=2),
            )
        )
    ):
        month_key = _normalize_month_key(row["month"])
        if month_key:
            exp_items_month_map[month_key] = _to_decimal(row["total"])

    exp_vat_month_map = {}
    for row in expenditure_scope.annotate(month=TruncMonth("date_incurred")).values("month").annotate(total=Sum("vat")):
        month_key = _normalize_month_key(row["month"])
        if month_key:
            exp_vat_month_map[month_key] = _to_decimal(row["total"])

    financial_balance_labels = [item.strftime("%b %Y") for item in financial_month_axis]
    financial_monthly_income_values = []
    financial_monthly_expense_values = []
    financial_monthly_balance_values = []
    running_balance = Decimal("0")
    for month_key in financial_month_axis:
        income_value = payment_month_map.get(month_key, Decimal("0")) + trans_income_month_map.get(month_key, Decimal("0"))
        expense_value = (
            trans_expense_month_map.get(month_key, Decimal("0"))
            + exp_items_month_map.get(month_key, Decimal("0"))
            + exp_vat_month_map.get(month_key, Decimal("0"))
        )
        running_balance += income_value - expense_value
        financial_monthly_income_values.append(_to_float(income_value))
        financial_monthly_expense_values.append(_to_float(expense_value))
        financial_monthly_balance_values.append(_to_float(running_balance))

    # ------------------------------------------------------------------
    # 3) Income statement
    # ------------------------------------------------------------------
    statement_class_id = _to_int_param(request.GET.get("statement_class"))
    statement_class_scope = term_scoped_academic_classes
    if statement_class_id:
        statement_class_scope = statement_class_scope.filter(Class_id=statement_class_id)

    statement_fee_income_total = _to_decimal(
        Payment.objects.filter(bill__academic_class__in=statement_class_scope).aggregate(total=Sum("amount"))["total"]
    )

    statement_income_rows = [
        {
            "item": "Tuition / Fees",
            "type": "Income",
            "amount": statement_fee_income_total,
            "notes": "Collected school fees",
        }
    ]
    statement_expense_rows = []
    statement_chart_map = defaultdict(lambda: {"income": Decimal("0"), "expense": Decimal("0")})

    if statement_fee_income_total:
        statement_chart_map["Tuition / Fees"]["income"] += statement_fee_income_total

    for row in transaction_scope.filter(transaction_type="Income").values("related_income_source__name").annotate(total=Sum("amount")).order_by("-total"):
        item_name = row["related_income_source__name"] or "Other Income"
        total_value = _to_decimal(row["total"])
        statement_income_rows.append(
            {
                "item": item_name,
                "type": "Income",
                "amount": total_value,
                "notes": "Ledger income source",
            }
        )
        statement_chart_map[item_name]["income"] += total_value

    expense_item_rows = (
        ExpenditureItem.objects.filter(expenditure__in=expenditure_scope)
        .values("expenditure__budget_item__expense__name")
        .annotate(
            total=Sum(
                ExpressionWrapper(
                    F("quantity") * F("unit_cost"),
                    output_field=DecimalField(max_digits=14, decimal_places=2),
                )
            )
        )
        .order_by("-total")
    )
    for row in expense_item_rows:
        item_name = row["expenditure__budget_item__expense__name"] or "General Expense"
        total_value = _to_decimal(row["total"])
        statement_expense_rows.append(
            {
                "item": item_name,
                "type": "Expense",
                "amount": total_value,
                "notes": "Budget expenditure items",
            }
        )
        statement_chart_map[item_name]["expense"] += total_value

    statement_vat_total = _to_decimal(expenditure_scope.aggregate(total=Sum("vat"))["total"])
    if statement_vat_total:
        statement_expense_rows.append(
            {
                "item": "VAT",
                "type": "Expense",
                "amount": statement_vat_total,
                "notes": "Value added tax on expenditures",
            }
        )
        statement_chart_map["VAT"]["expense"] += statement_vat_total

    statement_direct_expense_total = _to_decimal(
        transaction_scope.filter(transaction_type="Expense").aggregate(total=Sum("amount"))["total"]
    )
    if statement_direct_expense_total:
        statement_expense_rows.append(
            {
                "item": "Direct Expense Transactions",
                "type": "Expense",
                "amount": statement_direct_expense_total,
                "notes": "Cash expense transactions",
            }
        )
        statement_chart_map["Direct Expense Transactions"]["expense"] += statement_direct_expense_total

    income_statement_table_rows = statement_income_rows + statement_expense_rows
    income_statement_table_rows = sorted(
        income_statement_table_rows,
        key=lambda item: (item["type"], -_to_float(item["amount"]), item["item"]),
    )

    statement_chart_labels = []
    statement_chart_income = []
    statement_chart_expense = []
    for item_name, item_value in sorted(
        statement_chart_map.items(),
        key=lambda pair: -_to_float(pair[1]["income"] + pair[1]["expense"]),
    )[:10]:
        statement_chart_labels.append(item_name)
        statement_chart_income.append(_to_float(item_value["income"]))
        statement_chart_expense.append(_to_float(item_value["expense"]))

    # ------------------------------------------------------------------
    # 4) Cash flow
    # ------------------------------------------------------------------
    default_cash_from = current_term.start_date if current_term else (today - timedelta(days=29))
    default_cash_to = current_term.end_date if current_term else today
    cash_from = _parse_date(request.GET.get("cash_from")) or default_cash_from
    cash_to = _parse_date(request.GET.get("cash_to")) or default_cash_to
    if cash_from > cash_to:
        cash_from, cash_to = cash_to, cash_from

    cash_payment_scope = Payment.objects.filter(
        bill__academic_class__in=payment_scope_classes,
        payment_date__range=(cash_from, cash_to),
    ).select_related("bill__student")
    cash_transaction_scope = Transaction.objects.filter(date__range=(cash_from, cash_to))
    cash_expenditure_scope = Expenditure.objects.filter(date_incurred__range=(cash_from, cash_to))

    cash_entries = []
    for payment in cash_payment_scope:
        cash_entries.append(
            {
                "date": payment.payment_date,
                "description": f"Tuition Fees - {payment.bill.student.student_name}",
                "inflow": _to_decimal(payment.amount),
                "outflow": Decimal("0"),
            }
        )

    for txn in cash_transaction_scope:
        if txn.transaction_type == "Income":
            inflow = _to_decimal(txn.amount)
            outflow = Decimal("0")
        else:
            inflow = Decimal("0")
            outflow = _to_decimal(txn.amount)
        cash_entries.append(
            {
                "date": txn.date,
                "description": txn.description,
                "inflow": inflow,
                "outflow": outflow,
            }
        )

    for row in cash_expenditure_scope.annotate(
        items_total=Sum(
            ExpressionWrapper(
                F("items__quantity") * F("items__unit_cost"),
                output_field=DecimalField(max_digits=14, decimal_places=2),
            )
        )
    ).values("date_incurred", "description", "vat", "items_total"):
        total_outflow = _to_decimal(row["items_total"]) + _to_decimal(row["vat"])
        cash_entries.append(
            {
                "date": row["date_incurred"],
                "description": row["description"] or "Expenditure",
                "inflow": Decimal("0"),
                "outflow": total_outflow,
            }
        )

    cash_entries = sorted(cash_entries, key=lambda item: (item["date"], item["description"]))
    cash_total_inflow = sum((item["inflow"] for item in cash_entries), Decimal("0"))
    cash_total_outflow = sum((item["outflow"] for item in cash_entries), Decimal("0"))
    cash_net = cash_total_inflow - cash_total_outflow

    running_balance = Decimal("0")
    cash_flow_table_rows = []
    for item in cash_entries:
        running_balance += item["inflow"] - item["outflow"]
        cash_flow_table_rows.append(
            {
                "date": item["date"],
                "description": item["description"],
                "inflow": item["inflow"],
                "outflow": item["outflow"],
                "balance": running_balance,
            }
        )
    cash_flow_table_rows = cash_flow_table_rows[-120:]

    cash_line_start = cash_from
    if (cash_to - cash_from).days > 45:
        cash_line_start = cash_to - timedelta(days=45)

    line_base_balance = Decimal("0")
    for item in cash_entries:
        if item["date"] < cash_line_start:
            line_base_balance += item["inflow"] - item["outflow"]

    daily_delta_map = defaultdict(lambda: Decimal("0"))
    for item in cash_entries:
        if item["date"] >= cash_line_start:
            daily_delta_map[item["date"]] += item["inflow"] - item["outflow"]

    cash_line_labels = []
    cash_line_values = []
    cursor = cash_line_start
    rolling_balance = line_base_balance
    while cursor <= cash_to:
        rolling_balance += daily_delta_map.get(cursor, Decimal("0"))
        cash_line_labels.append(cursor.strftime("%d %b"))
        cash_line_values.append(_to_float(rolling_balance))
        cursor += timedelta(days=1)

    weekly_bucket = defaultdict(lambda: {"inflow": Decimal("0"), "outflow": Decimal("0")})
    for item in cash_entries:
        week_start = item["date"] - timedelta(days=item["date"].weekday())
        weekly_bucket[week_start]["inflow"] += item["inflow"]
        weekly_bucket[week_start]["outflow"] += item["outflow"]

    cash_weekly_labels = []
    cash_weekly_inflow = []
    cash_weekly_outflow = []
    for week_start in sorted(weekly_bucket.keys()):
        cash_weekly_labels.append(week_start.strftime("Wk %d %b"))
        cash_weekly_inflow.append(_to_float(weekly_bucket[week_start]["inflow"]))
        cash_weekly_outflow.append(_to_float(weekly_bucket[week_start]["outflow"]))

    # ------------------------------------------------------------------
    # 5) Attendance report
    # ------------------------------------------------------------------
    attendance_class_id = _to_int_param(request.GET.get("attendance_class"))
    attendance_section_id = _to_int_param(request.GET.get("attendance_section"))
    attendance_from = _parse_date(request.GET.get("attendance_from")) or (
        current_term.start_date if current_term else (today - timedelta(days=29))
    )
    attendance_to = _parse_date(request.GET.get("attendance_to")) or (
        current_term.end_date if current_term else today
    )
    if attendance_from > attendance_to:
        attendance_from, attendance_to = attendance_to, attendance_from

    attendance_scope = AttendanceRecord.objects.filter(
        session__class_stream__academic_class__in=term_scoped_academic_classes,
        session__date__range=(attendance_from, attendance_to),
    )
    if attendance_class_id:
        attendance_scope = attendance_scope.filter(
            session__class_stream__academic_class__Class_id=attendance_class_id
        )
    if attendance_section_id:
        attendance_scope = attendance_scope.filter(
            session__class_stream__academic_class__section_id=attendance_section_id
        )

    attendance_total_present = attendance_scope.filter(status__in=PRESENT_LIKE_STATUSES).count()
    attendance_total_absent = attendance_scope.filter(status__in=ABSENT_LIKE_STATUSES).count()
    attendance_total_records = attendance_total_present + attendance_total_absent
    attendance_percent = _percent(attendance_total_present, attendance_total_records)

    attendance_student_rows = []
    for row in attendance_scope.values(
        "student_id",
        "student__student_name",
        "student__student_number",
                "student__reg_no",
        "session__class_stream__academic_class__Class__code",
        "session__class_stream__stream__stream",
    ).annotate(
        days_present=Count("id", filter=Q(status__in=PRESENT_LIKE_STATUSES)),
        days_absent=Count("id", filter=Q(status__in=ABSENT_LIKE_STATUSES)),
        total_days=Count("id"),
    ).order_by("student__student_name"):
        total_days = row["total_days"] or 0
        percent_value = _percent(row["days_present"], total_days)
        attendance_student_rows.append(
            {
                "student_id": row["student_id"],
                "student_name": row["student__student_name"] or "Unknown",
                "reg_no": row.get("student__student_number") or row.get("student__reg_no") or "-",
                "class_label": f"{row['session__class_stream__academic_class__Class__code'] or '-'}{row['session__class_stream__stream__stream'] or ''}".strip(),
                "days_present": row["days_present"] or 0,
                "days_absent": row["days_absent"] or 0,
                "attendance_percent": percent_value,
            }
        )
    attendance_student_rows = sorted(
        attendance_student_rows,
        key=lambda item: (item["attendance_percent"], item["student_name"]),
    )[:200]

    attendance_class_comparison_rows = []
    for row in attendance_scope.values(
        "session__class_stream__academic_class__Class__code",
    ).annotate(
        present=Count("id", filter=Q(status__in=PRESENT_LIKE_STATUSES)),
        total=Count("id"),
    ).order_by("session__class_stream__academic_class__Class__code"):
        class_rate = _percent(row["present"], row["total"])
        attendance_class_comparison_rows.append(
            {
                "class_label": row["session__class_stream__academic_class__Class__code"] or "-",
                "rate": class_rate,
            }
        )

    heatmap_total_days = (attendance_to - attendance_from).days + 1
    heatmap_start = attendance_from
    if heatmap_total_days > 42:
        heatmap_start = attendance_to - timedelta(days=41)

    daily_attendance_map = {}
    for row in attendance_scope.filter(session__date__gte=heatmap_start).annotate(
        day=TruncDate("session__date")
    ).values("day").annotate(
        present=Count("id", filter=Q(status__in=PRESENT_LIKE_STATUSES)),
        total=Count("id"),
    ):
        if row["day"]:
            daily_attendance_map[row["day"]] = {"present": row["present"] or 0, "total": row["total"] or 0}

    attendance_heatmap_points = []
    cursor = heatmap_start
    while cursor <= attendance_to:
        daily = daily_attendance_map.get(cursor, {"present": 0, "total": 0})
        rate = _percent(daily["present"], daily["total"]) if daily["total"] else 0
        if not daily["total"]:
            intensity = 0
        elif rate < 60:
            intensity = 1
        elif rate < 75:
            intensity = 2
        elif rate < 90:
            intensity = 3
        else:
            intensity = 4
        attendance_heatmap_points.append(
            {
                "date": cursor,
                "day_label": cursor.strftime("%d"),
                "weekday": cursor.strftime("%a"),
                "rate": rate,
                "intensity": intensity,
                "total": daily["total"],
            }
        )
        cursor += timedelta(days=1)

    # ------------------------------------------------------------------
    # 6) Academic report
    # ------------------------------------------------------------------
    academic_class_id = _to_int_param(request.GET.get("academic_class"))
    academic_subject_id = _to_int_param(request.GET.get("academic_subject"))

    academic_scope = Result.objects.filter(
        assessment__academic_class__in=term_scoped_academic_classes
    )
    if academic_class_id:
        academic_scope = academic_scope.filter(
            assessment__academic_class__Class_id=academic_class_id
        )
    if academic_subject_id:
        academic_scope = academic_scope.filter(assessment__subject_id=academic_subject_id)

    academic_average_score = _to_float(academic_scope.aggregate(avg=Avg("score"))["avg"])
    academic_highest_score = _to_float(academic_scope.aggregate(max=Max("score"))["max"])
    academic_lowest_score = _to_float(academic_scope.aggregate(min=Min("score"))["min"])

    grading_scale = list(GradingSystem.objects.order_by("min_score"))
    academic_student_rows = []
    for row in academic_scope.values(
        "student_id",
        "student__student_name",
        "student__student_number",
                "student__reg_no",
        "assessment__subject__name",
    ).annotate(
        term_score=Avg("score"),
        cumulative_score=Sum("score"),
    ).order_by("student__student_name", "assessment__subject__name"):
        term_score = _to_float(row["term_score"])
        academic_student_rows.append(
            {
                "student_id": row["student_id"],
                "student_name": row["student__student_name"] or "Unknown",
                "reg_no": row.get("student__student_number") or row.get("student__reg_no") or "-",
                "subject_name": row["assessment__subject__name"] or "-",
                "term_score": term_score,
                "cumulative_score": _to_float(row["cumulative_score"]),
                "grade": _grade_for_score(term_score, grading_scale),
            }
        )
    academic_student_rows = academic_student_rows[:250]

    academic_subject_chart_rows = list(
        academic_scope.values("assessment__subject__name")
        .annotate(avg_score=Avg("score"))
        .order_by("-avg_score")[:10]
    )
    academic_progress_rows = list(
        academic_scope.values("assessment__date")
        .annotate(avg_score=Avg("score"))
        .order_by("assessment__date")
    )
    if len(academic_progress_rows) > 12:
        academic_progress_rows = academic_progress_rows[-12:]

    # ------------------------------------------------------------------
    # 7) Bulk result cards
    # ------------------------------------------------------------------
    bulk_class_id = _to_int_param(request.GET.get("bulk_class"))
    bulk_section_id = _to_int_param(request.GET.get("bulk_section"))

    bulk_class_scope = term_scoped_academic_classes
    if bulk_class_id:
        bulk_class_scope = bulk_class_scope.filter(Class_id=bulk_class_id)
    if bulk_section_id:
        bulk_class_scope = bulk_class_scope.filter(section_id=bulk_section_id)

    bulk_students_scope = term_scoped_students
    if bulk_class_id:
        bulk_students_scope = bulk_students_scope.filter(current_class_id=bulk_class_id)
    if bulk_section_id:
        bulk_students_scope = bulk_students_scope.filter(current_class__section_id=bulk_section_id)

    bulk_result_student_ids = set(
        Result.objects.filter(assessment__academic_class__in=bulk_class_scope)
        .values_list("student_id", flat=True)
        .distinct()
    )

    bulk_result_rows = []
    generated_count = 0
    for student in bulk_students_scope.order_by("student_name")[:300]:
        is_generated = student.id in bulk_result_student_ids
        if is_generated:
            generated_count += 1
        generate_url = reverse("student_term_report", args=[student.id])
        if current_term:
            generate_url = f"{generate_url}?term={current_term.id}"
        bulk_result_rows.append(
            {
                "student_id": student.id,
                "student_name": student.student_name,
                "reg_no": student.student_number or student.reg_no,
                "class_label": f"{student.current_class.code}{student.stream.stream}".strip(),
                "is_generated": is_generated,
                "generate_url": generate_url,
            }
        )
    total_bulk_students = len(bulk_result_rows)
    pending_count = max(total_bulk_students - generated_count, 0)

    bulk_generate_url = reverse("class_bulk_reports")
    bulk_query_parts = []
    if current_term:
        bulk_query_parts.append(f"term={current_term.id}")
    if bulk_class_id:
        bulk_query_parts.append(f"class={bulk_class_id}")
    if bulk_query_parts:
        bulk_generate_url = f"{bulk_generate_url}?{'&'.join(bulk_query_parts)}"

    # ------------------------------------------------------------------
    # 8) Verification monitor
    # ------------------------------------------------------------------
    monitor_status = (request.GET.get("monitor_status") or "all").strip().lower()
    monitor_user_id = _to_int_param(request.GET.get("monitor_user"))

    verification_task_rows = []

    result_batch_base_scope = ResultBatch.objects.filter(
        assessment__academic_class__in=term_scoped_academic_classes
    )
    result_batch_scope = (
        result_batch_base_scope.select_related(
            "assessment__academic_class__Class",
            "submitted_by",
            "verified_by",
        )
        .order_by("-assessment__date")[:200]
    )
    for batch in result_batch_scope:
        assigned_user = batch.verified_by or batch.submitted_by
        status_key = (batch.status or "").strip().lower()
        verification_task_rows.append(
            {
                "task": f"Result Check - {batch.assessment}",
                "type": "Result Verification",
                "status": batch.get_status_display(),
                "status_key": status_key,
                "assigned_to": assigned_user.username if assigned_user else "Unassigned",
                "assigned_user_id": assigned_user.id if assigned_user else None,
                "created_on": batch.submitted_at.date() if batch.submitted_at else batch.assessment.date,
                "notes": batch.rejection_reason or "Awaiting result verification",
            }
        )

    filtered_verification_tasks = []
    for task in verification_task_rows:
        if monitor_status != "all" and task["status_key"] != monitor_status:
            continue
        if monitor_user_id and task["assigned_user_id"] != monitor_user_id:
            continue
        filtered_verification_tasks.append(task)
    filtered_verification_tasks = sorted(
        filtered_verification_tasks,
        key=lambda item: item["created_on"],
        reverse=True,
    )[:250]

    pending_statuses = {"pending", "flagged", "draft"}
    completed_statuses = {"verified"}
    verification_pending_count = 0
    verification_completed_count = 0
    for task in filtered_verification_tasks:
        if task["status_key"] in completed_statuses:
            verification_completed_count += 1
        elif task["status_key"] in pending_statuses:
            verification_pending_count += 1
        else:
            verification_pending_count += 1

    monitor_user_options = []
    monitor_user_ids = {task["assigned_user_id"] for task in filtered_verification_tasks if task["assigned_user_id"]}
    if monitor_user_ids:
        monitor_user_options = list(
            User.objects.filter(id__in=monitor_user_ids).values("id", "username").order_by("username")
        )
    if not monitor_user_options:
        monitor_user_options = list(
            User.objects.filter(is_active=True).values("id", "username").order_by("username")[:50]
        )

    # ------------------------------------------------------------------
    # 9) User & access report
    # ------------------------------------------------------------------
    user_role_filter = (request.GET.get("user_role") or "").strip()
    user_department_filter = (request.GET.get("user_department") or "").strip()
    user_status_filter = (request.GET.get("user_status") or "all").strip().lower()

    user_scope = User.objects.select_related("staff_account__role", "staff_account__staff").order_by("username")
    if user_status_filter == "active":
        user_scope = user_scope.filter(is_active=True)
    elif user_status_filter == "inactive":
        user_scope = user_scope.filter(is_active=False)

    if user_role_filter:
        user_scope = user_scope.filter(staff_account__role__name=user_role_filter)
    if user_department_filter:
        user_scope = user_scope.filter(staff_account__staff__department=user_department_filter)

    user_access_rows = []
    for user_obj in user_scope[:250]:
        staff_account = getattr(user_obj, "staff_account", None)
        role_name = getattr(getattr(staff_account, "role", None), "name", "Unassigned")
        staff_member = getattr(staff_account, "staff", None)
        department = getattr(staff_member, "department", "-")
        manage_url = f"{reverse('user_list')}?search={user_obj.username}"
        user_access_rows.append(
            {
                "id": user_obj.id,
                "username": user_obj.username,
                "role_name": role_name or "Unassigned",
                "department": department or "-",
                "status": "Active" if user_obj.is_active else "Inactive",
                "last_login": user_obj.last_login,
                "view_url": reverse("user_detail", args=[user_obj.id]),
                "edit_url": manage_url,
                "deactivate_url": manage_url,
                "can_deactivate": user_obj.is_active and not user_obj.is_superuser and user_obj.id != request.user.id,
            }
        )

    user_role_distribution_rows = list(
        user_scope.values("staff_account__role__name")
        .annotate(total=Count("id"))
        .order_by("-total")
    )
    user_role_distribution_labels = [
        row["staff_account__role__name"] or "Unassigned"
        for row in user_role_distribution_rows
    ]
    user_role_distribution_values = [_to_float(row["total"]) for row in user_role_distribution_rows]

    # ------------------------------------------------------------------
    # Top cards and operational side data
    # ------------------------------------------------------------------
    active_users_count = User.objects.filter(is_active=True).count()
    inactive_users_count = User.objects.filter(is_active=False).count()

    verification_status_counts = {status: 0 for status, _ in ResultBatch.STATUS_CHOICES}
    for row in result_batch_base_scope.values("status").annotate(total=Count("id")):
        verification_status_counts[row["status"]] = row["total"]

    recent_login_activity = list(
        AuditLog.objects.filter(action__in=[AuditLog.ACTION_LOGIN, AuditLog.ACTION_LOGOUT])
        .select_related("user")
        .order_by("-timestamp")[:8]
    )
    recent_system_activity_logs = list(
        AuditLog.objects.select_related("user", "content_type")
        .filter(action__in=[AuditLog.ACTION_CREATE, AuditLog.ACTION_UPDATE, AuditLog.ACTION_DELETE])
        .filter(content_type__app_label="app")
        .filter(Q(user__isnull=False) | ~Q(username="") | ~Q(path="") | ~Q(object_repr=""))
        .order_by("-timestamp")[:8]
    )
    recent_system_activity = []
    for log in recent_system_activity_logs:
        username = (log.username or (log.user.username if log.user_id else "")).strip() or "System"
        recent_system_activity.append(
            {
                "timestamp": log.timestamp,
                "username": username,
                "action": log.get_action_display(),
                "target": _audit_target_label(log),
                "details": _audit_change_summary(log),
            }
        )

    db_name = settings.DATABASES.get("default", {}).get("NAME")
    db_size_mb = 0.0
    if db_name and os.path.exists(db_name):
        try:
            db_size_mb = round(os.path.getsize(db_name) / (1024 * 1024), 2)
        except OSError:
            db_size_mb = 0.0
    media_size_mb = _dir_size_mb(getattr(settings, "MEDIA_ROOT", ""))
    storage_total_mb = round(db_size_mb + media_size_mb, 2)

    software_name = getattr(settings, "SOFTWARE_NAME", "School MIS")
    software_version = getattr(settings, "SOFTWARE_VERSION", "1.0.0")
    software_channel = getattr(settings, "SOFTWARE_RELEASE_CHANNEL", "stable")
    software_build = getattr(settings, "SOFTWARE_BUILD", "")
    version_label = f"{software_name} v{software_version}"
    if software_channel:
        version_label = f"{version_label} ({software_channel})"
    if software_build:
        version_label = f"{version_label} [{software_build}]"

    # ------------------------------------------------------------------
    # Charts payload
    # ------------------------------------------------------------------
    charts_payload = {
        "fees_paid_vs_outstanding": {
            "labels": ["Paid", "Outstanding"],
            "values": [_to_float(fees_total_paid), _to_float(fees_total_outstanding)],
        },
        "fees_class_outstanding": {
            "labels": [row["class_label"] for row in fees_class_outstanding_rows[:10]],
            "values": [_to_float(row["outstanding"]) for row in fees_class_outstanding_rows[:10]],
        },
        "fees_monthly_collection": {
            "labels": fees_month_labels,
            "values": fees_month_values,
        },
        "financial_income_vs_expense": {
            "labels": ["Income", "Expenses"],
            "values": [_to_float(financial_total_income), _to_float(financial_total_expenses)],
        },
        "financial_balance_trend": {
            "labels": financial_balance_labels,
            "income_values": financial_monthly_income_values,
            "expense_values": financial_monthly_expense_values,
            "balance_values": financial_monthly_balance_values,
        },
        "income_statement_stack": {
            "labels": statement_chart_labels,
            "income_values": statement_chart_income,
            "expense_values": statement_chart_expense,
        },
        "cash_flow_line": {
            "labels": cash_line_labels,
            "values": cash_line_values,
        },
        "cash_flow_weekly": {
            "labels": cash_weekly_labels,
            "inflow_values": cash_weekly_inflow,
            "outflow_values": cash_weekly_outflow,
        },
        "attendance_class_comparison": {
            "labels": [row["class_label"] for row in attendance_class_comparison_rows],
            "values": [row["rate"] for row in attendance_class_comparison_rows],
        },
        "academic_subject_performance": {
            "labels": [row["assessment__subject__name"] or "-" for row in academic_subject_chart_rows],
            "values": [_to_float(row["avg_score"]) for row in academic_subject_chart_rows],
        },
        "academic_progress": {
            "labels": [
                row["assessment__date"].strftime("%d %b")
                for row in academic_progress_rows
                if row["assessment__date"]
            ],
            "values": [_to_float(row["avg_score"]) for row in academic_progress_rows],
        },
        "verification_status": {
            "labels": ["Pending", "Completed"],
            "values": [verification_pending_count, verification_completed_count],
        },
        "user_role_distribution": {
            "labels": user_role_distribution_labels,
            "values": user_role_distribution_values,
        },
    }

    return {
        "reports_links": report_links,
        "reports_links_map": report_links_map,
        "reports_system_version": version_label,
        "reports_filter_options": {
            "year": current_year,
            "term": current_term,
            "formats": ["PDF", "Excel"],
            "classes": report_class_options,
            "sections": report_section_options,
            "students": report_student_options,
            "subjects": report_subject_options,
            "roles": report_role_options,
            "departments": report_department_options,
            "monitor_users": monitor_user_options,
        },
        "reports_recent_login_activity": recent_login_activity,
        "reports_recent_system_activity": recent_system_activity,
        "reports_db_size_mb": db_size_mb,
        "reports_media_size_mb": media_size_mb,
        "reports_storage_total_mb": storage_total_mb,
        "reports_active_users_count": active_users_count,
        "reports_inactive_users_count": inactive_users_count,
        "reports_verification_total": sum(verification_status_counts.values()),
        "reports_pending_verification": verification_status_counts.get("PENDING", 0),
        "reports_flagged_verification": verification_status_counts.get("FLAGGED", 0),
        "reports_top_cards": {
            "fees_billed": term_billed_total,
            "fees_paid": term_paid_total,
            "fees_outstanding": term_outstanding_receivables,
            "collection_percent": _percent(term_paid_total, term_billed_total),
            "net_balance": financial_net_balance,
            "attendance_percent": attendance_percent,
            "academic_average": academic_average_score,
            "pending_tasks": verification_pending_count,
            "active_users": active_users_count,
        },
        # 1) Fees
        "fees_selected_class": fees_class_id,
        "fees_selected_section": fees_section_id,
        "fees_selected_student": fees_student_id,
        "fees_total_billed": fees_total_billed,
        "fees_total_paid": fees_total_paid,
        "fees_total_outstanding": fees_total_outstanding,
        "fees_collection_percent": fees_collection_percent,
        "fees_student_rows": fees_student_table_rows,
        "fees_class_outstanding_rows": fees_class_outstanding_rows[:20],
        # 2) Financial summary
        "financial_total_income": financial_total_income,
        "financial_total_expenses": financial_total_expenses,
        "financial_net_balance": financial_net_balance,
        "financial_outstanding_receivables": term_outstanding_receivables,
        "financial_summary_rows": financial_summary_rows,
        # 3) Income statement
        "statement_selected_class": statement_class_id,
        "income_statement_rows": income_statement_table_rows,
        # 4) Cash flow
        "cash_from": cash_from,
        "cash_to": cash_to,
        "cash_total_inflow": cash_total_inflow,
        "cash_total_outflow": cash_total_outflow,
        "cash_net": cash_net,
        "cash_flow_rows": cash_flow_table_rows,
        # 5) Attendance
        "attendance_selected_class": attendance_class_id,
        "attendance_selected_section": attendance_section_id,
        "attendance_from": attendance_from,
        "attendance_to": attendance_to,
        "attendance_total_present": attendance_total_present,
        "attendance_total_absent": attendance_total_absent,
        "attendance_percent": attendance_percent,
        "attendance_student_rows": attendance_student_rows,
        "attendance_heatmap_points": attendance_heatmap_points,
        "attendance_heatmap_truncated": heatmap_total_days > 42,
        "attendance_class_comparison_rows": attendance_class_comparison_rows,
        # 6) Academics
        "academic_selected_class": academic_class_id,
        "academic_selected_subject": academic_subject_id,
        "academic_average_score": academic_average_score,
        "academic_highest_score": academic_highest_score,
        "academic_lowest_score": academic_lowest_score,
        "academic_student_rows": academic_student_rows,
        # 7) Bulk cards
        "bulk_selected_class": bulk_class_id,
        "bulk_selected_section": bulk_section_id,
        "bulk_generated_count": generated_count,
        "bulk_pending_count": pending_count,
        "bulk_total_students": total_bulk_students,
        "bulk_result_rows": bulk_result_rows,
        "bulk_generate_url": bulk_generate_url,
        # 8) Verification
        "monitor_selected_status": monitor_status,
        "monitor_selected_user": monitor_user_id,
        "verification_tasks": filtered_verification_tasks,
        "verification_pending_count": verification_pending_count,
        "verification_completed_count": verification_completed_count,
        # 9) Users
        "user_selected_role": user_role_filter,
        "user_selected_department": user_department_filter,
        "user_selected_status": user_status_filter,
        "user_access_rows": user_access_rows,
        "reports_charts_json": json.dumps(charts_payload),
    }
