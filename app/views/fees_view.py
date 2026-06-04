from django.shortcuts import render, redirect, HttpResponseRedirect,get_object_or_404
from django.http import HttpResponse, JsonResponse
from django.template.loader import render_to_string
from django.contrib import messages
from django.urls import reverse
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from app.selectors.model_selectors import *
from app.constants import *
from app.selectors.fees_selectors import * 
from app.forms.fees_payment import * 
from django.contrib.auth.decorators import login_required
from app.models.students import *
from app.models.classes import *
from app.models.school_settings import AcademicYear
from app.models.students import StudentDocument
from app.services.fees_ledger import (
    build_ledger_rows,
    build_ledger_workbook,
    get_ledger_filter_options,
    parse_date_value,
)
from app.services.fees_carry_forward import (
    build_carry_forward_preview,
    post_carry_forward,
)

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import cm, inch
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from io import BytesIO
from decimal import Decimal
from django.utils import timezone


STUDENT_BILL_MANAGE_ROLES = {
    "admin",
    "head master",
    "head teacher",
    "headteacher",
    "bursar",
    "finance",
}


def _get_effective_role(request):
    staff_account = getattr(request.user, "staff_account", None)
    role_name = staff_account.role.name if staff_account and staff_account.role else ""
    return (request.session.get("active_role_name") or role_name or "").strip()


def _can_manage_student_bill(request):
    return request.user.is_superuser or _get_effective_role(request).lower() in STUDENT_BILL_MANAGE_ROLES


@login_required
def manage_bill_items_view(request):
    bill_items = get_bill_items()
    bill_item_form = BillItemForm()
    
    context = {
        "bill_items": bill_items,
        "bill_item_form": bill_item_form
    }
    return render(request, "fees/bill_items.html", context)

@login_required
def add_bill_item_view(request):
    if request.method == "POST":
        bill_item_form = BillItemForm(request.POST)
    
        if bill_item_form.is_valid():
            bill_item_form.save()
            
            messages.success(request, SUCCESS_ADD_MESSAGE)
        else:
            messages.error(request, FAILURE_MESSAGE)
    else:
        messages.warning(request, "Not a Post Method")
        
    return HttpResponseRedirect(reverse(manage_bill_items_view))


@login_required
def edit_bill_item_view(request,id):
    bill_item = get_model_record(BillItem,id)
    if request.method =="POST":
        form= BillItemForm(request.POST,instance=bill_item)
        if form.is_valid():
            form.save()

            messages.success(request,SUCCESS_ADD_MESSAGE)
            return HttpResponseRedirect(reverse(manage_bill_items_view))
        else:
            messages.error(request,FAILURE_MESSAGE)
            
    form = BillItemForm(instance=bill_item)
    context={
        "form":form,
        "bill_item":bill_item
        
    }
    return render(request,"fees/edit_bill_item.html",context)


@login_required
def delete_bill_item_view(request, id):
    if request.method != "POST":
        messages.error(request, "Delete requests must be submitted via POST.")
        return HttpResponseRedirect(reverse(manage_bill_items_view))

    bill_item = get_model_record(BillItem, id)
    
    bill_item.delete()
    
    messages.success(request, DELETE_MESSAGE)

    return HttpResponseRedirect(reverse(manage_bill_items_view))



@login_required
def manage_student_bills_view(request):
    # Get filter parameters
    academic_year_id = request.GET.get('academic_year')
    term_id = request.GET.get('term')
    class_id = request.GET.get('class')
    search_query = request.GET.get('search', '').strip()

    # Convert 'None' strings to None
    if academic_year_id == 'None' or academic_year_id == '':
        academic_year_id = None
    if term_id == 'None' or term_id == '':
        term_id = None
    if class_id == 'None' or class_id == '':
        class_id = None

    # Get all filter options
    academic_years = AcademicYear.objects.all()
    terms = Term.objects.all()
    classes = Class.objects.all()

    # Start with all student bills
    student_bills = StudentBill.objects.select_related(
        'student', 'academic_class', 'academic_class__academic_year',
        'academic_class__term', 'academic_class__Class'
    ).order_by('-bill_date')

    # Apply filters
    if academic_year_id:
        student_bills = student_bills.filter(academic_class__academic_year_id=academic_year_id)

    if term_id:
        student_bills = student_bills.filter(academic_class__term_id=term_id)

    if class_id:
        student_bills = student_bills.filter(academic_class__Class_id=class_id)

    if search_query:
        student_bills = student_bills.filter(
            student__student_name__icontains=search_query
        )

    # Calculate summary statistics before pagination
    all_bills = student_bills  # Keep reference for statistics
    total_bills = all_bills.count()
    total_amount = sum(bill.total_amount for bill in all_bills)
    total_paid = sum(bill.amount_paid for bill in all_bills)
    total_outstanding = total_amount - total_paid

    # Status breakdown
    paid_bills = all_bills.filter(status='Paid').count()
    unpaid_bills = all_bills.filter(status='Unpaid').count()
    overdue_bills = all_bills.filter(status='Overdue').count()

    # Pagination
    page = request.GET.get('page', 1)
    paginator = Paginator(student_bills, 25)  # 25 bills per page

    try:
        student_bills = paginator.page(page)
    except PageNotAnInteger:
        student_bills = paginator.page(1)
    except EmptyPage:
        student_bills = paginator.page(paginator.num_pages)

    context = {
        "student_bills": student_bills,
        "academic_years": academic_years,
        "terms": terms,
        "classes": classes,
        "selected_academic_year": str(academic_year_id) if academic_year_id else '',
        "selected_term": str(term_id) if term_id else '',
        "selected_class": str(class_id) if class_id else '',
        "search_query": search_query,
        # Summary statistics
        "total_bills": total_bills,
        "total_amount": total_amount,
        "total_paid": total_paid,
        "total_outstanding": total_outstanding,
        "paid_bills": paid_bills,
        "unpaid_bills": unpaid_bills,
        "overdue_bills": overdue_bills,
    }
    return render(request, "fees/student_bills.html", context)

@login_required
def manage_student_bill_details_view(request, id):
    context = get_student_bill_details(id)
    context["bill_item_form"] = StudentBillItemForm(initial={"bill": context["student_bill"]})
    # Pre-fill recorded_by so bursar doesn't need to type it
    context["payment_form"] = PaymentForm(
        bill=context["student_bill"],
        initial={
            "bill": context["student_bill"],
            "recorded_by": getattr(request.user, "username", "") or getattr(request.user, "get_username", lambda: "")()
        },
    )
    student = context["student_bill"].student
    context["academic_year"] = student.academic_year
    context["term"] = student.term
    context["bill_documents"] = student.documents.filter(bill=context["student_bill"])
    context["document_type_choices"] = DOCUMENT_TYPES
    # School settings for receipt
    from app.models.school_settings import SchoolSetting
    context["school_settings"] = SchoolSetting.load()
    context["effective_role"] = _get_effective_role(request)
    context["can_manage_student_bill"] = _can_manage_student_bill(request)

    return render(request, "fees/student_bill_details.html", context)



@login_required
def add_student_bill_item_view(request, id):
    bill = get_student_bill(id)
    if not _can_manage_student_bill(request):
        messages.error(request, "Only Admin, Bursar, or Finance can add bill items.")
        return HttpResponseRedirect(reverse(manage_student_bill_details_view, args=[bill.id]))
    
    if request.method == "POST":
        post_data = request.POST.copy()
        post_data["bill"] = bill.id
        form = StudentBillItemForm(post_data)
        
        if form.is_valid():
            bill_item = form.save(commit=False)
            bill_item.bill = bill
            bill_item.save()
            
            messages.success(request, SUCCESS_ADD_MESSAGE)
        else:
            messages.error(request, FAILURE_MESSAGE)
    else:
        messages.warning(request, "Not a Post Method")
        
    return HttpResponseRedirect(reverse(manage_student_bill_details_view, args=[bill.id]))

@login_required
def add_student_payment_view(request, id):
    bill = get_student_bill(id)
    if not _can_manage_student_bill(request):
        messages.error(request, "Only Admin, Bursar, or Finance can record payments.")
        return HttpResponseRedirect(reverse(manage_student_bill_details_view, args=[bill.id]))
    
    if request.method == "POST":
        form = PaymentForm(request.POST, bill=bill)
        
        if form.is_valid():
            payment = form.save(commit=False)
            # Ensure the recorder is always the current user regardless of form input
            payment.bill = bill  # enforce bill from URL context
            payment.recorded_by = getattr(request.user, "username", "") or getattr(request.user, "get_username", lambda: "")()
            # Auto-generate reference_no if not provided or blank
            if not getattr(payment, "reference_no", None) or str(payment.reference_no).strip() == "":
                payment.reference_no = f"PMT-{bill.id}-{timezone.now().strftime('%Y%m%d%H%M%S%f')}"
            payment.save()
            messages.success(request, "Payment recorded successfully. Print or save the official receipt.")
            return HttpResponseRedirect(reverse('student_payment_receipt', args=[payment.id]))
        else:
            # Print errors for debugging
            print("Form errors:", form.errors)
            messages.error(request, FAILURE_MESSAGE)
    else:
        # Show the payment form
        form = PaymentForm(bill=bill, initial={'bill': bill, 'payment_date': timezone.now().date()})
        return render(request, 'fees/payment_form_page.html', {'form': form, 'bill': bill})
    
    return HttpResponseRedirect(reverse(manage_student_bill_details_view, args=[bill.id]))


@login_required
def ajax_payment_form_view(request, bill_id):
    """AJAX view to get payment form for a bill (used in modal)"""
    from django.http import JsonResponse
    from django.middleware.csrf import get_token
    
    bill = get_object_or_404(StudentBill, pk=bill_id)
    if not _can_manage_student_bill(request):
        return JsonResponse({'success': False, 'message': 'Only Admin, Bursar, or Finance can record payments.'}, status=403)
    
    if request.method == 'POST':
        form = PaymentForm(request.POST, bill=bill)
        if form.is_valid():
            payment = form.save(commit=False)
            payment.bill = bill
            payment.recorded_by = getattr(request.user, 'username', '') or getattr(request.user, 'get_username', lambda: '')()
            if not getattr(payment, 'reference_no', None) or str(payment.reference_no).strip() == '':
                payment.reference_no = f'PMT-{bill.id}-{timezone.now().strftime("%Y%m%d%H%M%S%f")}'
            payment.save()
            return JsonResponse({
                'success': True,
                'message': 'Payment recorded successfully!',
                'receipt_url': reverse('student_payment_receipt', args=[payment.id]),
            })
        else:
            return JsonResponse({'success': False, 'errors': form.errors})
    else:
        # Return the form for GET request
        form = PaymentForm(bill=bill, initial={'bill': bill, 'payment_date': timezone.now().date()})
        form_html = render_to_string('fees/payment_form_partial.html', {'bill': bill, 'payment_form': form, 'today': timezone.now().date()}, request=request)
        return JsonResponse({'form_html': form_html})


@login_required
def carry_forward_balances_view(request):
    if not _can_manage_student_bill(request):
        messages.error(request, "Only Admin, Bursar, or Finance can carry forward balances.")
        return HttpResponseRedirect(reverse(student_fees_status_view))

    current_year = AcademicYear.objects.filter(is_current=True).first()
    current_term = Term.objects.filter(is_current=True).select_related("academic_year").first()
    previous_term = None
    if current_term:
        previous_term = (
            Term.objects.filter(
                academic_year=current_term.academic_year,
                end_date__lt=current_term.start_date,
            )
            .exclude(pk=current_term.pk)
            .order_by("-end_date", "-id")
            .first()
        )

    source_term_id = request.POST.get("source_term") or request.GET.get("source_term") or (previous_term.id if previous_term else "")
    target_term_id = request.POST.get("target_term") or request.GET.get("target_term") or (current_term.id if current_term else "")
    selected_class_id = request.POST.get("class") or request.GET.get("class") or ""
    active_students_only = (request.POST.get("active_only") if request.method == "POST" else request.GET.get("active_only", "1")) != "0"

    source_term = Term.objects.filter(pk=source_term_id).select_related("academic_year").first() if source_term_id else None
    target_term = Term.objects.filter(pk=target_term_id).select_related("academic_year").first() if target_term_id else None

    preview_rows = []
    if source_term and target_term:
        if source_term.id == target_term.id:
            messages.warning(request, "Choose two different terms before carrying balances forward.")
        else:
            preview_rows = build_carry_forward_preview(
                source_term=source_term,
                target_term=target_term,
                class_id=selected_class_id,
                active_students_only=active_students_only,
            )

    if request.method == "POST" and request.POST.get("action") == "post":
        confirmed = request.POST.get("confirmed") == "1"
        if not source_term or not target_term or source_term.id == target_term.id:
            messages.error(request, "Select a valid source term and target term.")
        elif not preview_rows:
            messages.warning(request, "No outstanding balances were found for the selected scope.")
        elif not confirmed:
            messages.error(request, "Confirm that the preview has been reviewed before posting carried-forward balances.")
        else:
            result = post_carry_forward(
                source_term=source_term,
                target_term=target_term,
                class_id=selected_class_id,
                active_students_only=active_students_only,
            )
            messages.success(
                request,
                f"Carried forward UGX {result['posted_total']:,.0f} for {result['posted_count']} learner(s).",
            )
            if result["skipped_count"]:
                messages.warning(
                    request,
                    f"{result['skipped_count']} learner(s) were skipped because the target class/term is not set up.",
                )
            return HttpResponseRedirect(
                f"{reverse(carry_forward_balances_view)}?source_term={source_term.id}&target_term={target_term.id}&class={selected_class_id}&active_only={'1' if active_students_only else '0'}"
            )

    total_outstanding = sum((row.outstanding for row in preview_rows), 0)
    postable_rows = [row for row in preview_rows if row.can_post]
    skipped_rows = [row for row in preview_rows if not row.can_post]

    context = {
        "academic_years": AcademicYear.objects.order_by("-academic_year"),
        "terms": Term.objects.select_related("academic_year").order_by("-academic_year__academic_year", "term"),
        "classes": Class.objects.order_by("code", "name"),
        "current_year": current_year,
        "source_term": source_term,
        "target_term": target_term,
        "selected_source_term": int(source_term_id) if str(source_term_id).isdigit() else "",
        "selected_target_term": int(target_term_id) if str(target_term_id).isdigit() else "",
        "selected_class": int(selected_class_id) if str(selected_class_id).isdigit() else "",
        "active_students_only": active_students_only,
        "preview_rows": preview_rows,
        "postable_rows": postable_rows,
        "skipped_rows": skipped_rows,
        "total_outstanding": total_outstanding,
    }
    return render(request, "fees/carry_forward_balances.html", context)
    

  

@login_required
def student_fees_status_view(request):
    """Fees status scoped to current academic year and term, enrolled students only, with due dates and payment history."""
    # Scope: current academic year and current term by default
    current_year = AcademicYear.objects.filter(is_current=True).first()
    current_term = Term.objects.filter(is_current=True, academic_year=current_year).first() if current_year else None

    selected_academic_class = request.GET.get("academic_class")
    selected_term_id = request.GET.get("term")
    selected_year_id = request.GET.get("year")
    selected_status = (request.GET.get("status") or "").strip().lower()

    # Resolve selected academic year (defaults to current)
    selected_year = None
    if selected_year_id:
        selected_year = AcademicYear.objects.filter(id=selected_year_id).first()
    if not selected_year:
        selected_year = current_year

    # Available filters (limited to selected year)
    academic_years = AcademicYear.objects.all().order_by('-id')
    academic_classes = AcademicClass.objects.filter(academic_year=selected_year) if selected_year else AcademicClass.objects.none()
    terms = Term.objects.filter(academic_year=selected_year) if selected_year else Term.objects.none()

    # Apply selected filters
    filtered_academic_classes = academic_classes
    if selected_academic_class:
        filtered_academic_classes = filtered_academic_classes.filter(Class_id=selected_academic_class)
    if selected_term_id:
        filtered_academic_classes = filtered_academic_classes.filter(term_id=selected_term_id)
    else:
        # default to current term of selected year
        default_term = Term.objects.filter(is_current=True, academic_year=selected_year).first()
        if default_term:
            filtered_academic_classes = filtered_academic_classes.filter(term=default_term)

    # Determine effective term
    term_obj = Term.objects.filter(id=selected_term_id).first() if selected_term_id else Term.objects.filter(is_current=True, academic_year=selected_year).first()

    # Build rows from StudentBill to ensure we show existing billed data
    student_fees_data = []
    now = timezone.now().date()
    bills_qs = StudentBill.objects.filter(
        academic_class__academic_year=selected_year,
        academic_class__term=term_obj,
    )
    if selected_academic_class:
        bills_qs = bills_qs.filter(academic_class__Class_id=selected_academic_class)

    for bill in bills_qs.select_related("student", "academic_class", "academic_class__Class"):
        total_amount = bill.total_amount
        amount_paid = bill.amount_paid
        due_date = bill.due_date

        if amount_paid >= total_amount and total_amount > 0:
            payment_status = "Paid"; balance = 0; balance_label = ""
        elif amount_paid == 0 and total_amount == 0:
            payment_status = "No Bill"; balance = 0; balance_label = ""
        else:
            balance = abs(total_amount - amount_paid)
            if amount_paid > total_amount:
                payment_status = "Overpaid"; balance_label = "CR"
            elif amount_paid == 0 and total_amount > 0:
                is_overdue = bool(due_date and now > due_date)
                payment_status = "Overdue" if is_overdue else "Unpaid"; balance_label = "DR"
            else:
                is_overdue = bool(due_date and now > due_date and amount_paid < total_amount)
                payment_status = "Overdue" if is_overdue else "Partial"; balance_label = "DR"

        recent_payments = list(
            Payment.objects.filter(bill=bill).order_by("-payment_date").values("amount", "payment_date")[:3]
        )

        student_fees_data.append({
            "student": bill.student,
            "student_id": bill.student.id,
            "academic_class": bill.academic_class,
            "academic_year": bill.academic_class.academic_year,
            "term": bill.academic_class.term,
            "total_amount": total_amount,
            "amount_paid": amount_paid,
            "amount_paid_percentage": (amount_paid / total_amount * 100) if total_amount > 0 else 0,
            "payment_status": payment_status,
            "balance": balance if 'balance' in locals() else 0,
            "balance_label": balance_label if 'balance_label' in locals() else "",
            "recent_payments": recent_payments,
            "bill_id": bill.id,
        })


    # Fallback: if no rows for selected term, try latest term WITH data in the selected year
    if not student_fees_data:
        from django.db.models import Max
        # Find latest term (by start_date) within selected year that has any StudentBill
        term_ids_with_bills = (
            StudentBill.objects.filter(
                academic_class__academic_year=selected_year,
            )
            .values_list('academic_class__term_id', flat=True)
            .distinct()
        )
        fallback_term = (
            Term.objects.filter(id__in=term_ids_with_bills, academic_year=selected_year)
            .order_by('-start_date')
            .first()
        )
        if fallback_term and (not selected_term_id or str(fallback_term.id) != str(selected_term_id)):
            term_obj = fallback_term
            # Rebuild from bills for fallback term
            bills_qs = StudentBill.objects.filter(
                academic_class__academic_year=selected_year,
                academic_class__term=term_obj,
            )
            if selected_academic_class:
                bills_qs = bills_qs.filter(academic_class__Class_id=selected_academic_class)
            student_fees_data = []
            now = timezone.now().date()
            for bill in bills_qs.select_related("student", "academic_class", "academic_class__Class"):
                total_amount = bill.total_amount
                amount_paid = bill.amount_paid
                due_date = bill.due_date
                if amount_paid >= total_amount and total_amount > 0:
                    payment_status = "Paid"; balance = 0; balance_label = ""
                elif amount_paid == 0 and total_amount == 0:
                    payment_status = "No Bill"; balance = 0; balance_label = ""
                else:
                    balance = abs(total_amount - amount_paid)
                    if amount_paid > total_amount:
                        payment_status = "Overpaid"; balance_label = "CR"
                    elif amount_paid == 0 and total_amount > 0:
                        is_overdue = bool(due_date and now > due_date)
                        payment_status = "Overdue" if is_overdue else "Unpaid"; balance_label = "DR"
                    else:
                        is_overdue = bool(due_date and now > due_date and amount_paid < total_amount)
                        payment_status = "Overdue" if is_overdue else "Partial"; balance_label = "DR"
                recent_payments = list(
                    Payment.objects.filter(bill=bill).order_by('-payment_date').values('amount','payment_date')[:3]
                )
                student_fees_data.append({
                    "student": bill.student,
                    "academic_class": bill.academic_class,
                    "academic_year": bill.academic_class.academic_year,
                    "term": bill.academic_class.term,
                    "total_amount": total_amount,
                    "amount_paid": amount_paid,
                    "amount_paid_percentage": (amount_paid / total_amount * 100) if total_amount > 0 else 0,
                    "payment_status": payment_status,
                    "balance": balance if 'balance' in locals() else 0,
                    "balance_label": balance_label if 'balance_label' in locals() else "",
                    "recent_payments": recent_payments,
                    "bill_id": bill.id,
                })
            # Update the effective filters
            selected_term_id = str(fallback_term.id)

    # Optional payment status filter (applies after class/year/term scope)
    status_filters = {
        "outstanding": {"Unpaid", "Partial", "Overdue"},
        "paid": {"Paid"},
        "overpaid": {"Overpaid"},
        "unpaid": {"Unpaid"},
        "partial": {"Partial"},
        "overdue": {"Overdue"},
        "no_bill": {"No Bill"},
    }
    if selected_status in status_filters:
        allowed_statuses = status_filters[selected_status]
        student_fees_data = [row for row in student_fees_data if row.get("payment_status") in allowed_statuses]

    # Summary metrics for UX
    total_fees = sum(row["total_amount"] for row in student_fees_data)
    total_paid = sum(row["amount_paid"] for row in student_fees_data)
    total_balance = sum(row["balance"] for row in student_fees_data if row.get("balance_label") != "CR")
    collection_rate = (total_paid / total_fees * 100) if total_fees > 0 else 0

    if request.GET.get("download_pdf"):
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.units import inch

        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=landscape(A4),
                               rightMargin=72, leftMargin=72,
                               topMargin=72, bottomMargin=72)

        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=18,
            spaceAfter=30,
            alignment=1,  # Center alignment
            textColor=colors.darkblue
        )

        subtitle_style = ParagraphStyle(
            'CustomSubtitle',
            parent=styles['Normal'],
            fontSize=12,
            spaceAfter=20,
            alignment=1,
            textColor=colors.darkgrey
        )

        normal_style = styles['Normal']

        # Build the PDF content
        content = []

        # Title
        content.append(Paragraph("Student Fees Payment Status Report", title_style))
        content.append(Spacer(1, 12))

        # Report details
        report_info = f"""
        <b>Report Generated:</b> {timezone.now().strftime('%B %d, %Y at %I:%M %p')}<br/>
        <b>Academic Year:</b> {selected_year.academic_year if selected_year else 'All Years'}<br/>
        <b>Term:</b> {term_obj.term if term_obj else 'All Terms'}<br/>
        <b>Class Filter:</b> {AcademicClass.objects.filter(id=selected_academic_class).first().Class.name if selected_academic_class else 'All Classes'}<br/>
        <b>Status Filter:</b> {selected_status.replace('_', ' ').title() if selected_status else 'All Statuses'}<br/>
        <b>Total Students:</b> {len(student_fees_data)}<br/>
        <b>Total Fees:</b> UGX {total_fees:,.0f}<br/>
        <b>Total Paid:</b> UGX {total_paid:,.0f}<br/>
        <b>Outstanding Balance:</b> UGX {total_balance:,.0f}
        """
        content.append(Paragraph(report_info, normal_style))
        content.append(Spacer(1, 20))

        # Table data
        table_data = [['#', 'Class', 'Student Name', 'Reg. No.', 'Total Fees', 'Amount Paid', 'Balance', 'Status']]

        for idx, row in enumerate(student_fees_data, 1):
            balance_str = f"{row['balance_label']} {row['balance']:,.0f}" if row["balance_label"] else f"{row['balance']:,.0f}"
            table_data.append([
                str(idx),
                str(row["academic_class"]),
                row["student"].student_name,
                row["student"].reg_no,
                f"UGX {row['total_amount']:,.0f}",
                f"UGX {row['amount_paid']:,.0f}",
                balance_str,
                row["payment_status"]
            ])

        # Create table
        table = Table(table_data, repeatRows=1)

        # Table style
        table_style = TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.darkblue),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.white),
            ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),
            ('ALIGN', (0, 1), (-1, 1), 'CENTER'),
            ('ALIGN', (4, 1), (6, -1), 'RIGHT'),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ])

        # Alternate row colors
        for i in range(1, len(table_data)):
            if i % 2 == 0:
                table_style.add('BACKGROUND', (0, i), (-1, i), colors.lightgrey)

        table.setStyle(table_style)
        content.append(table)

        # Footer
        content.append(Spacer(1, 30))
        footer_text = f"""
        <i>This report was generated by the School Management System on {timezone.now().strftime('%B %d, %Y')}.</i><br/>
        <i>For any inquiries, please contact the school administration.</i>
        """
        content.append(Paragraph(footer_text, ParagraphStyle('Footer', parent=styles['Normal'], fontSize=8, alignment=1, textColor=colors.grey)))

        # Build PDF
        doc.build(content)
        buffer.seek(0)
        response = HttpResponse(buffer, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="student_fees_status_{timezone.now().strftime("%Y%m%d_%H%M%S")}.pdf"'
        return response

    context = {
        "academic_years": academic_years,
        "academic_classes": academic_classes,
        "terms": terms,
        "class_filter": int(selected_academic_class) if selected_academic_class else "",
        "academic_class_filter": int(selected_academic_class) if selected_academic_class else "",
        "term_filter": int(selected_term_id) if selected_term_id else (current_term.id if current_term else ""),
        "year_filter": int(selected_year.id) if selected_year else "",
        "student_fees_data": student_fees_data,
        "total_fees": total_fees,
        "total_paid": total_paid,
        "total_balance": total_balance,
        "collection_rate": collection_rate,
        "status_filter": selected_status,
        "current_term": term_obj if 'term_obj' in locals() and term_obj else current_term,
        "current_year": selected_year,
    }
    return render(request, "fees/student_fees_status.html", context)


@login_required
def payment_ledger_view(request):
    selected_student_id = (request.GET.get("student") or "").strip()
    selected_class_id = (request.GET.get("classroom") or "").strip()
    selected_year_id = (request.GET.get("year") or "").strip()
    selected_term_id = (request.GET.get("term") or "").strip()
    selected_classroom_group = (request.GET.get("classroom_group") or "").strip().upper()
    selected_classroom_code = (request.GET.get("classroom_code") or "").strip()
    selected_balance_mode = (request.GET.get("balance_mode") or "student").strip().lower()
    if selected_balance_mode not in {"student", "overall"}:
        selected_balance_mode = "student"
    selected_categories = [value for value in request.GET.getlist("category") if value]
    selected_methods = [value for value in request.GET.getlist("payment_method") if value]
    date_from = parse_date_value(request.GET.get("date_from"))
    date_to = parse_date_value(request.GET.get("date_to"))
    if date_from and date_to and date_from > date_to:
        date_from, date_to = date_to, date_from

    ledger_payload = build_ledger_rows(
        student_id=selected_student_id,
        class_id=selected_class_id,
        academic_year_id=selected_year_id,
        term_id=selected_term_id,
        classroom_group=selected_classroom_group,
        classroom_code=selected_classroom_code,
        categories=selected_categories,
        payment_methods=selected_methods,
        date_from=date_from,
        date_to=date_to,
        balance_mode=selected_balance_mode,
    )
    filter_options = get_ledger_filter_options()
    selected_student = (
        Student.objects.filter(pk=selected_student_id).only("id", "student_name", "reg_no", "student_number").first()
        if selected_student_id
        else None
    )
    selected_classroom = (
        Class.objects.filter(pk=selected_class_id).only("id", "code", "name").first()
        if selected_class_id
        else None
    )
    selected_year = (
        AcademicYear.objects.filter(pk=selected_year_id).only("id", "academic_year").first()
        if selected_year_id
        else None
    )
    selected_term = (
        Term.objects.select_related("academic_year").filter(pk=selected_term_id).only(
            "id",
            "term",
            "academic_year__academic_year",
        ).first()
        if selected_term_id
        else None
    )
    selected_student_summary = next(
        (
            summary
            for summary in ledger_payload["student_summaries"]
            if str(summary["student_pk"]) == selected_student_id
        ),
        None,
    )
    balance_scope_label = (
        "Running balance for this student" if selected_balance_mode == "student" else "Running balance across all results"
    )
    balance_column_label = "Student Balance" if selected_balance_mode == "student" else "Overall Balance"
    active_filter_items = []
    if selected_student:
        active_filter_items.append(
            {"label": "Student", "value": f"{selected_student.student_name} ({selected_student.student_number or selected_student.reg_no})"}
        )
    if selected_classroom_group:
        active_filter_items.append({"label": "Group", "value": selected_classroom_group.title()})
    if selected_classroom_code:
        active_filter_items.append({"label": "Classroom Code", "value": selected_classroom_code.upper()})
    if selected_classroom:
        active_filter_items.append(
            {"label": "Classroom", "value": selected_classroom.code or selected_classroom.name}
        )
    if selected_year:
        active_filter_items.append({"label": "Year", "value": str(selected_year.academic_year)})
    if selected_term:
        active_filter_items.append(
            {"label": "Term", "value": f"Term {selected_term.term} {selected_term.academic_year.academic_year}"}
        )
    if selected_balance_mode == "overall":
        active_filter_items.append({"label": "Balance", "value": "Overall ledger"})
    for category in selected_categories:
        active_filter_items.append({"label": "Category", "value": category})
    for method in selected_methods:
        active_filter_items.append({"label": "Method", "value": method})
    if date_from or date_to:
        if date_from and date_to:
            date_value = f"{date_from.strftime('%d %b %Y')} to {date_to.strftime('%d %b %Y')}"
        elif date_from:
            date_value = f"From {date_from.strftime('%d %b %Y')}"
        else:
            date_value = f"Up to {date_to.strftime('%d %b %Y')}"
        active_filter_items.append({"label": "Date", "value": date_value})

    export_format = (request.GET.get("export") or "").strip().lower()
    if export_format in {"excel", "xlsx"}:
        workbook_bytes = build_ledger_workbook(ledger_payload["rows"])
        response = HttpResponse(
            workbook_bytes,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = (
            f'attachment; filename="student_payment_ledger_{timezone.now().strftime("%Y%m%d_%H%M%S")}.xlsx"'
        )
        return response

    context = {
        "ledger_rows": ledger_payload["rows"],
        "ledger_total_charged": ledger_payload["total_charged"],
        "ledger_total_paid": ledger_payload["total_paid"],
        "ledger_running_balance": ledger_payload["running_balance"],
        "ledger_students": filter_options["students"],
        "ledger_classes": filter_options["classes"],
        "ledger_academic_years": filter_options["academic_years"],
        "ledger_terms": filter_options["terms"],
        "selected_student_id": selected_student_id,
        "selected_class_id": selected_class_id,
        "selected_year_id": selected_year_id,
        "selected_term_id": selected_term_id,
        "selected_classroom_group": selected_classroom_group,
        "selected_classroom_code": selected_classroom_code,
        "selected_balance_mode": selected_balance_mode,
        "selected_student": selected_student,
        "selected_classroom": selected_classroom,
        "selected_year": selected_year,
        "selected_term": selected_term,
        "selected_student_summary": selected_student_summary,
        "selected_categories": selected_categories,
        "selected_methods": selected_methods,
        "selected_date_from": date_from.isoformat() if date_from else "",
        "selected_date_to": date_to.isoformat() if date_to else "",
        "active_filter_items": active_filter_items,
        "active_filter_count": len(active_filter_items),
        "ledger_has_filters": bool(active_filter_items),
        "ledger_advanced_filters_open": bool(selected_categories or selected_methods),
        "balance_scope_label": balance_scope_label,
        "balance_column_label": balance_column_label,
        "show_student_group_headers": selected_balance_mode == "student" and not selected_student_id,
        "ledger_transaction_count": ledger_payload["transaction_count"],
        "ledger_student_count": ledger_payload["student_count"],
        "ledger_credit_row_count": ledger_payload["credit_row_count"],
        "ledger_total_outstanding": ledger_payload["total_outstanding"],
        "ledger_total_credit": ledger_payload["total_credit"],
        "ledger_top_outstanding_student": ledger_payload["top_outstanding_student"],
        "ledger_top_credit_student": ledger_payload["top_credit_student"],
        "ledger_largest_charge_category": ledger_payload["largest_charge_category"],
        "category_choices": LEDGER_CATEGORY_CHOICES,
        "method_choices": PAYMENT_METHODS,
    }
    return render(request, "fees/payment_ledger.html", context)


@login_required
def fees_help_view(request):
    context = {
        "ledger_columns": [
            "Date",
            "Student ID",
            "Student Name",
            "Classroom",
            "Term",
            "Category",
            "Payment Method",
            "Amount Charged",
            "Amount Paid",
            "Notes",
        ],
        "payment_methods": ["Cash", "SchoolPay", "Bank", "Other"],
        "categories": ["Tuition", "Transport", "Uniform", "Other"],
    }
    return render(request, "fees/help.html", context)


@login_required
def student_fees_history_view(request, student_id):
    """Show all bills for a particular student across every academic year and term."""
    student = get_object_or_404(Student, pk=student_id)
    
    # Get selected year from query params
    selected_year_id = request.GET.get('year')
    
    # Get all academic years for the student (for filter dropdown)
    student_years = AcademicYear.objects.filter(
        academicclass__studentbill__student=student
    ).distinct().order_by('-academic_year')
    
    # Base query - get all bills for student
    bills_qs = (
        StudentBill.objects
        .filter(student=student)
        .select_related('academic_class', 'academic_class__Class',
                        'academic_class__academic_year', 'academic_class__term')
        .prefetch_related('items', 'items__bill_item', 'payments')
    )
    
    # Get all bills for lifetime calculation (always show all years)
    # We'll calculate lifetime from years_data after it's built
    lifetime_billed = 0
    lifetime_paid = 0
    
    # Query for display (with prefetch for efficiency)
    bills_qs = (
        StudentBill.objects
        .filter(student=student)
        .select_related('academic_class', 'academic_class__Class',
                        'academic_class__academic_year', 'academic_class__term')
        .prefetch_related('items', 'items__bill_item', 'payments')
    )
    if selected_year_id:
        bills_qs = bills_qs.filter(academic_class__academic_year_id=selected_year_id)
    
    # Order by term
    bills_qs = bills_qs.order_by('-academic_class__term__term')
    
    # Deduplicate bills by ID (prefetch_related can cause duplicates)
    bills_qs = list({bill.id: bill for bill in bills_qs}.values())
    
    now = timezone.now().date()
    lifetime_outstanding = 0

    # Group bills by academic year (only for filtered/displayed bills)
    from collections import OrderedDict
    years_data = OrderedDict()

    for bill in bills_qs:
        total_amount = bill.total_amount
        amount_paid = bill.amount_paid
        balance = total_amount - amount_paid

        # Payment status
        if total_amount == 0 and amount_paid == 0:
            payment_status = "No Bill"
            balance_label = ""
        elif amount_paid >= total_amount and total_amount > 0:
            payment_status = "Paid"
            balance_label = ""
            balance = 0
        elif amount_paid > total_amount:
            payment_status = "Overpaid"
            balance_label = "CR"
            balance = abs(balance)
        elif amount_paid == 0 and total_amount > 0:
            is_overdue = bool(bill.due_date and now > bill.due_date)
            payment_status = "Overdue" if is_overdue else "Unpaid"
            balance_label = "DR"
            balance = abs(balance)
        else:
            is_overdue = bool(bill.due_date and now > bill.due_date and amount_paid < total_amount)
            payment_status = "Overdue" if is_overdue else "Partial"
            balance_label = "DR"
            balance = abs(balance)

        bill_data = {
            "bill": bill,
            "academic_class": bill.academic_class,
            "term": bill.academic_class.term,
            "total_amount": total_amount,
            "amount_paid": amount_paid,
            "balance": balance,
            "balance_label": balance_label,
            "payment_status": payment_status,
            "progress": (amount_paid / total_amount * 100) if total_amount > 0 else 0,
            "items": bill.items.all(),
            "payments": bill.payments.all().order_by('-payment_date'),
        }

        year_obj = bill.academic_class.academic_year
        year_key = year_obj.id
        if year_key not in years_data:
            years_data[year_key] = {
                "year": year_obj,
                "bills": [],
                "year_total": 0,
                "year_paid": 0,
                "year_outstanding": 0,
            }
        years_data[year_key]["bills"].append(bill_data)
        years_data[year_key]["year_total"] += total_amount
        years_data[year_key]["year_paid"] += amount_paid
    
    # Calculate lifetime totals from years_data (sums all years - this is the correct way)
    # This ensures we get all bills regardless of any year filter
    lifetime_billed = sum(yt['year_total'] for yt in years_data.values())
    lifetime_paid = sum(yt['year_paid'] for yt in years_data.values())
    
    # Calculate year_outstanding for each year as net: total - paid (can be negative)
    for year_key in years_data:
        yt = years_data[year_key]
        yt["year_outstanding"] = yt["year_total"] - yt["year_paid"]
        yt["year_outstanding_abs"] = abs(yt["year_outstanding"]) if yt["year_outstanding"] < 0 else 0

    # Calculate correct net balance: total billed - total paid
    # Positive = outstanding (student owes), Negative = credit (student overpaid)
    lifetime_outstanding = lifetime_billed - lifetime_paid
    lifetime_outstanding_abs = abs(lifetime_outstanding) if lifetime_outstanding < 0 else 0

    context = {
        "student": student,
        "years_data": years_data,
        "student_years": student_years,
        "selected_year_id": int(selected_year_id) if selected_year_id else None,
        "lifetime_billed": lifetime_billed,
        "lifetime_paid": lifetime_paid,
        "lifetime_outstanding": lifetime_outstanding,
        "lifetime_outstanding_abs": lifetime_outstanding_abs,
        "lifetime_progress": (lifetime_paid / lifetime_billed * 100) if lifetime_billed > 0 else 0,
        "bill_count": len(bills_qs),
        "today": timezone.now().date(),
    }
    return render(request, "fees/student_fees_history.html", context)


@login_required
def upload_bill_document(request, id):
    bill = get_student_bill(id)

    if request.method == "POST":
        document_type = request.POST.get('document_type')
        file = request.FILES.get('file')

        if document_type and file:
            StudentDocument.objects.create(
                student=bill.student,
                bill=bill,
                document_type=document_type,
                file=file
            )
            messages.success(request, SUCCESS_ADD_MESSAGE)
        else:
            messages.error(request, "Document type and file are required.")

    return HttpResponseRedirect(reverse(manage_student_bill_details_view, args=[bill.id]))


@login_required
def delete_bill_document(request, id):
    document = get_object_or_404(StudentDocument, id=id)
    bill_id = document.bill.id
    document.delete()
    messages.success(request, DELETE_MESSAGE)
    return HttpResponseRedirect(reverse(manage_student_bill_details_view, args=[bill_id]))


@login_required
def student_payment_receipt_view(request, payment_id):
    """Print-ready official receipt for one actual payment transaction."""
    from app.models.school_settings import SchoolSetting

    payment = get_object_or_404(
        Payment.objects.select_related(
            "bill",
            "bill__student",
            "bill__academic_class",
            "bill__academic_class__Class",
            "bill__academic_class__academic_year",
            "bill__academic_class__term",
        ).prefetch_related("bill__items", "bill__items__bill_item", "bill__payments"),
        pk=payment_id,
    )
    bill = payment.bill
    student = bill.student

    amount_paid_after = Decimal(str(bill.amount_paid or 0))
    payment_amount = Decimal(str(payment.amount or 0))
    amount_paid_before = max(amount_paid_after - payment_amount, Decimal("0"))
    bill_total = Decimal(str(bill.total_amount or 0))
    balance_before = bill_total - amount_paid_before
    balance_after = bill_total - amount_paid_after

    if balance_after < 0:
        receipt_status = "CREDIT BALANCE"
        status_class = "credit"
        balance_label = "Credit after payment"
        balance_display = abs(balance_after)
    elif balance_after == 0:
        receipt_status = "FULLY PAID"
        status_class = "paid"
        balance_label = "Balance after payment"
        balance_display = Decimal("0")
    else:
        receipt_status = "PART PAYMENT"
        status_class = "partial"
        balance_label = "Balance after payment"
        balance_display = balance_after

    try:
        school_settings = SchoolSetting.load()
    except Exception:
        school_settings = None

    return render(request, "fees/payment_receipt.html", {
        "payment": payment,
        "bill": bill,
        "student": student,
        "school_settings": school_settings,
        "bill_total": bill_total,
        "amount_paid_before": amount_paid_before,
        "amount_paid_after": amount_paid_after,
        "payment_amount": payment_amount,
        "balance_before": balance_before,
        "balance_after": balance_after,
        "balance_display": balance_display,
        "balance_label": balance_label,
        "receipt_status": receipt_status,
        "status_class": status_class,
        "printed_at": timezone.localtime(),
    })

@login_required
def student_fees_receipt_pdf_view(request, student_id):
    """Generate a PDF account statement for all student fees payments across all years."""
    from collections import OrderedDict
    from app.utils.pdf_utils import generate_student_fees_receipt_pdf
    from app.models.school_settings import SchoolSetting
    
    student = get_object_or_404(Student, pk=student_id)
    
    # Get all bills for the student
    bills_qs = (
        StudentBill.objects
        .filter(student=student)
        .select_related('academic_class', 'academic_class__Class',
                        'academic_class__academic_year', 'academic_class__term')
        .prefetch_related('items', 'items__bill_item', 'payments')
        .order_by('-academic_class__academic_year__id', '-academic_class__term__id')
    )
    
    now = timezone.now().date()
    
    # Build years_data structure for PDF
    years_data = OrderedDict()
    
    for bill in bills_qs:
        total_amount = bill.total_amount
        amount_paid = bill.amount_paid
        balance = total_amount - amount_paid
        
        # Determine balance label
        if total_amount == 0 and amount_paid == 0:
            balance_label = ""
        elif amount_paid >= total_amount and total_amount > 0:
            balance_label = ""
            balance = 0
        elif amount_paid > total_amount:
            balance_label = "CR"
            balance = abs(balance)
        else:
            balance_label = "DR"
            balance = abs(balance)
        
        # Get term name
        term_obj = bill.academic_class.term if bill.academic_class else None
        term_name = str(term_obj) if term_obj else "N/A"
        
        # Build bill data for PDF
        bill_data = {
            "description": f"Term {term_name}",
            "term": term_name,
            "total_amount": total_amount,
            "amount_paid": amount_paid,
            "balance": balance,
        }
        
        year_obj = bill.academic_class.academic_year
        year_key = str(year_obj.academic_year)  # Use year string as key
        
        if year_key not in years_data:
            years_data[year_key] = {
                "year": year_obj,
                "bills": [],
            }
        years_data[year_key]["bills"].append(bill_data)
    
    # Get school settings
    try:
        school = SchoolSetting.objects.first()
    except:
        school = None
    
    # Generate PDF
    pdf_buffer = generate_student_fees_receipt_pdf(student, years_data, school)
    
    # Return PDF response
    response = HttpResponse(pdf_buffer, content_type='application/pdf')
    filename = f"Fees_Statement_{student.reg_no}_{timezone.now().strftime('%Y%m%d')}.pdf"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@login_required
def reconcile_student_overpayments(request, student_id):
    """Reconcile overpayments from later terms to cover earlier term balances."""
    from app.models.fees_payment import StudentBill, StudentCredit
    from app.models.classes import AcademicClass
    
    student = get_object_or_404(Student, pk=student_id)
    
    # Get all bills for student ordered by term (earliest first)
    bills = (
        StudentBill.objects
        .filter(student=student)
        .select_related('academic_class__term', 'academic_class__academic_year')
        .order_by('academic_class__academic_year__academic_year', 'academic_class__term__term')
    )
    
    bills_list = list(bills)
    total_transferred = 0
    
    # Get all existing credits to avoid duplicates
    existing_credits = StudentCredit.objects.filter(
        student=student,
        is_applied=True
    ).values_list('original_bill_id', 'applied_to_bill_id')
    existing_pairs = set(existing_credits)
    
    # Find overpayments in later terms (higher index) and apply to earlier term balances (lower index)
    # Iterate from the last bill (latest term) backwards to the first (earliest term)
    for i in range(len(bills_list) - 1, -1, -1):
        later_bill = bills_list[i]
        later_bill.refresh_from_db()
        
        # Use raw balance (total_amount - amount_paid)
        raw_balance = later_bill.total_amount - later_bill.amount_paid
        
        # If there's a raw overpayment (paid more than billed)
        if raw_balance < 0:
            overpayment = abs(raw_balance)
            
            # Find earlier bills with outstanding balances (index < i)
            for j in range(i):
                if overpayment <= 0:
                    break
                    
                earlier_bill = bills_list[j]
                earlier_bill.refresh_from_db()
                
                # Use raw balance for earlier bills too
                earlier_raw_balance = earlier_bill.total_amount - earlier_bill.amount_paid
                
                if earlier_raw_balance > 0:  # Earlier bill has outstanding balance
                    # Calculate how much can be transferred
                    transfer_amount = min(overpayment, earlier_raw_balance)
                    
                    # Check if this credit already exists
                    credit_key = (later_bill.id, earlier_bill.id)
                    if credit_key not in existing_pairs:
                        # Create credit (negative amount to reduce balance)
                        StudentCredit.objects.create(
                            student=student,
                            amount=-transfer_amount,
                            description=f"Auto-transfer from Term {later_bill.academic_class.term} overpayment to cover earlier balance",
                            original_bill=later_bill,
                            applied_to_bill=earlier_bill,
                            is_applied=True,
                            applied_date=timezone.now().date()
                        )
                        existing_pairs.add(credit_key)
                        total_transferred += transfer_amount
                        overpayment -= transfer_amount
    
    if total_transferred > 0:
        messages.success(request, f"Successfully transferred UGX {total_transferred:,.0f} from overpayments to cover earlier balances.")
    else:
        messages.info(request, "No overpayments to reconcile.")
    
    return HttpResponseRedirect(reverse('student_fees_history', args=[student.id]))


@login_required
def student_ledger_modal_view(request, student_id):
    """AJAX view returning ledger rows for a single student (used in modal)."""
    student = get_object_or_404(Student, pk=student_id)
    ledger_payload = build_ledger_rows(student_id=str(student_id), balance_mode="student")
    context = {
        "student": student,
        "ledger_rows": ledger_payload["rows"],
        "total_charged": ledger_payload["total_charged"],
        "total_paid": ledger_payload["total_paid"],
        "running_balance": ledger_payload["running_balance"],
        "transaction_count": ledger_payload["transaction_count"],
    }
    return render(request, "fees/student_ledger_modal.html", context)
