"""UX-focused workflow views for daily school operations.

These views are intentionally small and conservative: they do not introduce new
business tables, so they can be deployed to an already-used school system without
migrating live data.
"""
from __future__ import annotations

from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from app.forms.fees_payment import PaymentForm
from app.models.accounts import StaffAccount
from app.models.classes import AcademicClass, AcademicClassStream, Class, Stream, Term
from app.models.fees_payment import BillItem, Payment, StudentBill
from app.models.results import Assessment, AssessmentType, GradingSystem, ResultBatch
from app.models.school_settings import AcademicYear, SchoolSetting, Signature
from app.models.staffs import Role, Staff
from app.models.students import Student
from app.models.subjects import Subject


ADMIN_ROLES = {"Admin", "Head Teacher", "Head master", "Headteacher"}
FINANCE_ROLES = ADMIN_ROLES | {"Bursar", "Finance", "Finance Manager"}
ACADEMIC_ROLES = ADMIN_ROLES | {"Director of Studies", "DOS", "Class Teacher", "Teacher"}


def _active_role(request) -> str:
    session_role = (request.session.get("active_role_name") or "").strip()
    if session_role:
        return session_role
    staff_account = getattr(request.user, "staff_account", None)
    if staff_account and getattr(staff_account, "role", None):
        return staff_account.role.name
    return "Support Staff"


def _role_key(role_name: str) -> str:
    return (role_name or "").strip().lower().replace("_", "-")


def _has_any_role(request, roles) -> bool:
    if getattr(request.user, "is_superuser", False):
        return True
    active = _active_role(request)
    if active in roles:
        return True
    try:
        return request.user.staff_account.staff.roles.filter(name__in=list(roles)).exists()
    except Exception:
        return False


def _money(value):
    try:
        return Decimal(str(value or 0))
    except Exception:
        return Decimal("0")


def _latest_current_scope():
    current_year = AcademicYear.objects.filter(is_current=True).first()
    current_term = Term.objects.filter(is_current=True).select_related("academic_year").first()
    return current_year, current_term


@login_required
def operations_center_view(request):
    """Role-aware landing page for the tasks staff do every day."""
    role = _active_role(request)
    key = _role_key(role)

    quick_actions = []

    def add_action(title, desc, icon, url_name, color="primary"):
        try:
            url = reverse(url_name)
        except Exception:
            return
        quick_actions.append({
            "title": title,
            "description": desc,
            "icon": icon,
            "url": url,
            "color": color,
        })

    if _has_any_role(request, ADMIN_ROLES):
        add_action("Setup Checklist", "Confirm the school is ready for the term.", "fa-check-square-o", "setup_checklist", "info")
        add_action("Register Student", "Add a learner with guardian details.", "fa-user-plus", "add_student", "success")
        add_action("Collect Fees", "Open the fast bursar payment screen.", "fa-money", "bursar_quick_payment", "primary")
        add_action("Create Bills", "Bill a class or manage bill items.", "fa-list-alt", "class_bill_list", "warning")
        add_action("Users & Roles", "Create staff accounts and assign access.", "fa-user-shield", "user_list", "danger")
        add_action("Reports", "Open leadership reports and analytics.", "fa-line-chart", "dashboard_overview", "primary")
    elif key in {"bursar", "finance", "finance-manager", "finance manager"}:
        add_action("Quick Payment", "Search learner, record money, print receipt.", "fa-money", "bursar_quick_payment", "primary")
        add_action("Outstanding Balances", "See debtors and payment status.", "fa-exclamation-circle", "fees_status", "warning")
        add_action("Payment Ledger", "Review all payments and export records.", "fa-book", "payment_ledger", "info")
        add_action("Expenses", "Record and review school expenses.", "fa-credit-card", "expense_page", "danger")
    elif key in {"teacher", "subject-teacher"}:
        add_action("Take Attendance", "Mark learners for today.", "fa-calendar-check-o", "take_attendance", "success")
        add_action("Enter Marks", "Enter BOT/MOT/EOT assessment marks.", "fa-edit", "add_results_page", "primary")
        add_action("My Timetable", "View today’s lessons.", "fa-clock-o", "teacher_timetable", "info")
        add_action("Messages", "Read announcements and staff messages.", "fa-comments", "message_inbox", "warning")
    elif key in {"class-teacher", "class teacher"}:
        add_action("My Class", "Open learners under your care.", "fa-users", "academic_class_page", "primary")
        add_action("Take Attendance", "Mark attendance for your class.", "fa-calendar-check-o", "take_attendance", "success")
        add_action("Report Cards", "Generate learner reports.", "fa-file-text-o", "class_bulk_reports", "info")
        add_action("Fee Alerts", "Check learners with balances.", "fa-money", "fees_status", "warning")
    elif key in {"director-of-studies", "director of studies", "dos"}:
        add_action("Verification Queue", "Check submitted results.", "fa-check-circle", "verification_overview", "primary")
        add_action("Incomplete Marks", "Monitor teachers who still need to submit.", "fa-edit", "school_results_dashboard", "warning")
        add_action("Performance Summary", "Review class and subject performance.", "fa-line-chart", "class_performance_summary", "info")
        add_action("Assessment Setup", "Manage assessments and grading.", "fa-cogs", "assessment_list", "danger")
    else:
        add_action("Search", "Find students, staff, classes, and subjects.", "fa-search", "global_search", "primary")
        add_action("Messages", "Read announcements and staff messages.", "fa-comments", "message_inbox", "info")

    today = timezone.localdate()
    alerts = []
    try:
        pending_verifications = ResultBatch.objects.filter(status="PENDING").count()
        if pending_verifications:
            alerts.append({"label": "Pending result verifications", "value": pending_verifications, "tone": "warning"})
    except Exception:
        pass
    try:
        open_balances = StudentBill.objects.exclude(status="Paid").count()
        if open_balances:
            alerts.append({"label": "Bills not fully paid", "value": open_balances, "tone": "danger"})
    except Exception:
        pass
    try:
        active_students = Student.objects.filter(is_active=True).count()
        alerts.append({"label": "Active learners", "value": active_students, "tone": "success"})
    except Exception:
        pass

    return render(request, "ux/operations_center.html", {
        "active_role_name": role,
        "quick_actions": quick_actions,
        "alerts": alerts,
        "today": today,
    })


@login_required
def setup_checklist_view(request):
    """A guided readiness checklist for onboarding a school/term."""
    if not _has_any_role(request, ADMIN_ROLES):
        messages.error(request, "Only administrators and school leaders can open the setup checklist.")
        return redirect("index_page")

    current_year, current_term = _latest_current_scope()
    checks = [
        ("School profile", "School name, logo, contacts, motto and report settings.", SchoolSetting.objects.exists(), "settings_page"),
        ("Current academic year", "Set the year that the school is currently using.", bool(current_year), "settings_page"),
        ("Current term", "Set the active term before fees, attendance and reports.", bool(current_term), "settings_page"),
        ("Classes", "Create Primary One to Primary Seven or the classes used by the school.", Class.objects.exists(), "class_page"),
        ("Streams", "Create streams such as Blue, Red, East, West or single stream.", Stream.objects.exists(), "stream_page"),
        ("Academic classes", "Join class, academic year and term so learners can be enrolled.", AcademicClass.objects.exists(), "academic_class_page"),
        ("Class streams", "Attach streams and class teachers to each academic class.", AcademicClassStream.objects.exists(), "add_class_stream_page"),
        ("Subjects", "Add subjects offered in the primary school.", Subject.objects.exists(), "subjects_page"),
        ("Staff", "Register teachers, bursar, DOS and administration staff.", Staff.objects.exists(), "staff_page"),
        ("Roles", "Confirm roles are available for staff accounts.", Role.objects.exists(), "user_list"),
        ("Staff accounts", "Create login accounts for staff who will use the system.", StaffAccount.objects.exists(), "user_list"),
        ("Bill items", "Create tuition, transport, lunch, uniform and other fee items.", BillItem.objects.exists(), "bill_item_page"),
        ("Assessment types", "Create BOT, MOT, EOT or the school’s selected assessment structure.", AssessmentType.objects.exists(), "assesment_type_page"),
        ("Assessment papers", "Create assessments for the current term.", Assessment.objects.exists(), "assessment_list"),
        ("Grading system", "Set score ranges and grades before report cards.", GradingSystem.objects.exists(), "add_grading_system_page"),
        ("Report signatures", "Upload/signature settings for head teacher and DOS if needed.", Signature.objects.exists(), "add_signature_page"),
    ]

    rows = []
    complete_count = 0
    for title, description, done, url_name in checks:
        if done:
            complete_count += 1
        try:
            url = reverse(url_name)
        except Exception:
            url = "#"
        rows.append({"title": title, "description": description, "done": done, "url": url})

    percentage = round((complete_count / len(rows)) * 100) if rows else 0
    return render(request, "ux/setup_checklist.html", {
        "checks": rows,
        "complete_count": complete_count,
        "total_checks": len(rows),
        "percentage": percentage,
        "current_year": current_year,
        "current_term": current_term,
    })


@login_required
def bursar_quick_payment_view(request):
    """Fast payment workflow: search learner, pick bill, record money."""
    if not _has_any_role(request, FINANCE_ROLES):
        messages.error(request, "Only Admin, Head Teacher, Bursar or Finance users can record payments.")
        return redirect("index_page")

    query = (request.GET.get("q") or "").strip()
    selected_student_id = (request.GET.get("student") or "").strip()
    selected_bill_id = request.POST.get("bill") or request.GET.get("bill")

    students = []
    selected_student = None
    bills = []
    selected_bill = None
    payment_form = None

    if query:
        students = list(
            Student.objects.filter(
                Q(student_name__icontains=query)
                | Q(reg_no__icontains=query)
                | Q(student_number__icontains=query)
                | Q(guardian__icontains=query)
                | Q(contact__icontains=query)
            ).select_related("current_class", "stream").order_by("student_name")[:12]
        )

    if selected_student_id:
        selected_student = get_object_or_404(Student.objects.select_related("current_class", "stream"), pk=selected_student_id)
        bills = list(
            StudentBill.objects.filter(student=selected_student)
            .select_related("academic_class", "academic_class__Class", "academic_class__term")
            .order_by("-bill_date")
        )
        if selected_bill_id:
            selected_bill = get_object_or_404(StudentBill, pk=selected_bill_id, student=selected_student)
        elif bills:
            selected_bill = next((bill for bill in bills if _money(bill.balance) > 0), bills[0])

    if request.method == "POST" and selected_bill:
        payment_form = PaymentForm(request.POST, bill=selected_bill)
        if payment_form.is_valid():
            payment = payment_form.save(commit=False)
            payment.bill = selected_bill
            payment.recorded_by = getattr(request.user, "username", "") or request.user.get_username()
            if not getattr(payment, "reference_no", None) or str(payment.reference_no).strip() == "":
                payment.reference_no = f"PMT-{selected_bill.id}-{timezone.now().strftime('%Y%m%d%H%M%S%f')}"
            payment.save()
            selected_bill.refresh_from_db()
            selected_bill.status = "Paid" if _money(selected_bill.balance) <= 0 else "Unpaid"
            selected_bill.save(update_fields=["status"])
            messages.success(request, f"Payment of UGX {payment.amount:,.0f} recorded for {selected_student.student_name}. Print or save the official receipt.")
            return redirect(reverse('student_payment_receipt', args=[payment.id]))
        messages.error(request, "Please correct the payment details and try again.")
    elif selected_bill:
        payment_form = PaymentForm(
            bill=selected_bill,
            initial={"payment_date": timezone.localdate(), "amount": selected_bill.balance if _money(selected_bill.balance) > 0 else None},
        )

    totals = {
        "total_billed": Decimal("0"),
        "total_paid": Decimal("0"),
        "balance": Decimal("0"),
    }
    if selected_student:
        total_billed = StudentBill.objects.filter(student=selected_student).aggregate(total=Sum("items__amount"))["total"] or 0
        total_paid = Payment.objects.filter(bill__student=selected_student).aggregate(total=Sum("amount"))["total"] or 0
        totals = {
            "total_billed": _money(total_billed),
            "total_paid": _money(total_paid),
            "balance": _money(total_billed) - _money(total_paid),
        }

    recent_payments = []
    if selected_student:
        recent_payments = list(
            Payment.objects.filter(bill__student=selected_student)
            .select_related("bill")
            .order_by("-payment_date", "-id")[:8]
        )

    return render(request, "fees/quick_payment.html", {
        "query": query,
        "students": students,
        "selected_student": selected_student,
        "bills": bills,
        "selected_bill": selected_bill,
        "payment_form": payment_form,
        "totals": totals,
        "recent_payments": recent_payments,
        "selected_bill_has_balance": bool(selected_bill and _money(selected_bill.balance) > 0),
    })
