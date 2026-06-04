from django.shortcuts import render, HttpResponsePermanentRedirect,redirect
from django.urls import reverse
from django.contrib import messages
from app.constants import *
from app.models.finance import *
from app.models.fees_payment import *
from app.forms.finance import *
from app.models.classes import *
from app.models.school_settings import *
from app.selectors.model_selectors import *
import app.forms.finance as finance_forms
import app.selectors.finance as finance_selector
from django.http import HttpResponse
import csv
from datetime import timedelta
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, F, DecimalField, Value, Q
from django.db.models.functions import TruncMonth, Coalesce
from django.shortcuts import get_object_or_404
from app.models.staffs import Staff

def _get_current_year_and_term():
    """
    Helper: returns (current_year, current_term) where term is bound to the current year when available.
    """
    current_year = AcademicYear.objects.filter(is_current=True).first()
    current_term = Term.objects.filter(is_current=True, academic_year=current_year).first() if current_year else Term.objects.filter(is_current=True).first()
    return current_year, current_term

def _parse_date_any(value):
    """
    Accepts 'YYYY-MM-DD' (HTML date inputs) and common 'DD/MM/YYYY' or 'MM/DD/YYYY' forms.
    Returns a date or None.
    """
    if not value:
        return None
    d = parse_date(value)
    if d:
        return d
    try:
        from datetime import datetime
        for fmt in ("%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%m-%d-%Y"):
            try:
                return datetime.strptime(value, fmt).date()
            except ValueError:
                continue
    except Exception:
        pass
    return None

@login_required
def manage_income_sources(request):
    form = finance_forms.IncomeSourceForm()
    income_sources = get_all_model_records(IncomeSource)
    
    context = {
        "income_sources": income_sources,
        "form": form
    }
    return render(request, "finance/income_sources.html", context)

@login_required
def add_income_source(request):
    if request.method == "POST":
        form = finance_forms.IncomeSourceForm(request.POST)
        
        if form.is_valid():
            form.save()
            
            messages.success(request, SUCCESS_ADD_MESSAGE)
        else:
            messages.error(request, FAILURE_MESSAGE)
    
    return HttpResponsePermanentRedirect(reverse(manage_income_sources))


@login_required
def edit_income_sources(request, id):
    income_source = get_model_record(IncomeSource,id)
    if request.method =="POST":
        form = finance_forms.IncomeSourceForm(request.POST, instance=income_source)
        if form.is_valid():
            form.save()
            messages.success(request, SUCCESS_ADD_MESSAGE)
            return HttpResponsePermanentRedirect(reverse(manage_income_sources))
        else:
            messages.error(request, FAILURE_MESSAGE)
  
    form = finance_forms.IncomeSourceForm(instance=income_source)
    context={
        "form": form,
        "income_source":income_source
    }
    return render(request,"finance/edit_income_sources.html",context)
    
     

@login_required
def delete_income_source(request, id):
    if request.method != "POST":
        messages.error(request, "Delete requests must be submitted via POST.")
        return HttpResponsePermanentRedirect(reverse(manage_income_sources))

    income_source = get_model_record(IncomeSource, id)
    
    income_source.delete()
    messages.success(request, DELETE_MESSAGE)
    
    return HttpResponsePermanentRedirect(reverse(manage_income_sources))

@login_required
def manage_expenses(request):
    form = finance_forms.ExpenseForm()
    expenses = get_all_model_records(Expense)
    edit_forms = {expense.id: finance_forms.ExpenseForm(instance=expense) for expense in expenses}
    
    context = {
        "expenses": expenses,
        "form": form,
        "edit_forms": edit_forms
    }
    return render(request, "finance/expenses.html", context)

@login_required
def add_expense(request):
    if request.method == "POST":
        form = finance_forms.ExpenseForm(request.POST)
        
        if form.is_valid():
            form.save()
            
            messages.success(request, SUCCESS_ADD_MESSAGE)
        else:
            messages.error(request, FAILURE_MESSAGE)
    
    return HttpResponsePermanentRedirect(reverse(manage_expenses))


@login_required
def edit_expenses(request, id):
    expense = get_model_record(Expense, id)
    
    if request.method == 'POST':
        form = finance_forms.ExpenseForm(request.POST, instance=expense)
        if form.is_valid():
            form.save()
            messages.success(request, SUCCESS_ADD_MESSAGE)
            return redirect(manage_expenses)  
        else:
            messages.error(request, FAILURE_MESSAGE)
  
    form = finance_forms.ExpenseForm(instance=expense)
    context = {
        'form': form,
        'expense': expense,
        
    }
    
    return render(request, 'finance/edit_expense.html', context)


@login_required
def delete_expense(request, id):
    if request.method != "POST":
        messages.error(request, "Delete requests must be submitted via POST.")
        return HttpResponsePermanentRedirect(reverse(manage_expenses))

    expense = get_model_record(Expense, id)
    
    expense.delete()
    messages.success(request, DELETE_MESSAGE)
    
    return HttpResponsePermanentRedirect(reverse(manage_expenses))

@login_required
def manage_expenditures(request):
    form = finance_forms.ExpenditureForm()

    # Filters
    start_date = request.GET.get('start_date') or ''
    end_date = request.GET.get('end_date') or ''
    academic_year_id = request.GET.get('academic_year')
    term_id = request.GET.get('term')
    show_all = (request.GET.get('show_all') == '1') or (request.GET.get('all') == '1')
    include_unassigned = (request.GET.get('include_unassigned') == '1')
    ignore_scope = (request.GET.get('ignore_scope') == '1')
    # Date basis: incurred (date_incurred) or recorded (date_recorded)
    date_field = (request.GET.get('date_field') or 'incurred').lower()
    if date_field not in ('incurred', 'recorded'):
        date_field = 'incurred'
    date_field_db = 'date_incurred' if date_field == 'incurred' else 'date_recorded'

    # Determine scope year/term
    current_year, current_term = _get_current_year_and_term()
    scope_year = None
    scope_term = None
    if not show_all:
        if academic_year_id and term_id:
            scope_year = AcademicYear.objects.filter(id=academic_year_id).first()
            scope_term = Term.objects.filter(id=term_id, academic_year=scope_year).first() if scope_year else None
        else:
            scope_year, scope_term = current_year, current_term

    # Parse dates from query (support YYYY-MM-DD and DD/MM/YYYY, MM/DD/YYYY)
    start_date_obj = _parse_date_any(start_date)
    end_date_obj = _parse_date_any(end_date)

    # Default to scoped term's date range if not provided
    if not (start_date_obj and end_date_obj) and scope_term:
        start_date_obj = start_date_obj or scope_term.start_date
        end_date_obj = end_date_obj or scope_term.end_date

    # Normalize for template inputs
    start_date = start_date_obj.isoformat() if start_date_obj else ''
    end_date = end_date_obj.isoformat() if end_date_obj else ''

    # Base queryset with optional scoping
    expenditures_qs = Expenditure.objects.all()
    if scope_year and scope_term and not ignore_scope:
        scope_cond = Q(
            budget_item__budget__academic_year=scope_year,
            budget_item__budget__term=scope_term
        )
        if include_unassigned:
            scope_cond = scope_cond | Q(budget_item__isnull=True)
        expenditures_qs = expenditures_qs.filter(scope_cond)

    # Apply date filters if provided (UI may hide date pickers; server still supports query params)
    if start_date_obj:
        expenditures_qs = expenditures_qs.filter(**{f"{date_field_db}__gte": start_date_obj})
    if end_date_obj:
        expenditures_qs = expenditures_qs.filter(**{f"{date_field_db}__lte": end_date_obj})

    # Optimize relations for listing/export
    expenditures_qs = expenditures_qs.select_related('vendor', 'budget_item__department', 'budget_item__expense')

    expenditures = expenditures_qs.order_by('-date_incurred', '-id')
    edit_forms = {expenditure.id: finance_forms.ExpenditureForm(instance=expenditure) for expenditure in expenditures}

    # Export CSV for current scope
    if request.GET.get('export') == 'csv':
        response = HttpResponse(content_type='text/csv')
        parts = ['expenditures']
        try:
            if scope_year:
                parts.append(f"year_{getattr(scope_year, 'id', scope_year)}")
            if scope_term:
                parts.append(f"term_{getattr(scope_term, 'id', scope_term)}")
        except Exception:
            pass
        fname = "_".join([str(p) for p in parts if p]) or "expenditures"
        response['Content-Disposition'] = f'attachment; filename="{fname}.csv"'
        writer = csv.writer(response)

        writer.writerow(['Expenditures'])
        writer.writerow(['Academic Year ID', getattr(scope_year, 'id', '') if scope_year else ('ALL' if show_all else '')])
        writer.writerow(['Term ID', getattr(scope_term, 'id', '') if scope_term else ('ALL' if show_all else '')])
        writer.writerow([])

        # Header
        writer.writerow([
            'ID',
            'Date Incurred',
            'Date Recorded',
            'Vendor',
            'Department',
            'Expense',
            'Budget Item',
            'Description',
            'Amount',
            'VAT',
            'Payment Status',
            'Approved By'
        ])

        for e in expenditures:
            dept = e.budget_item.department if getattr(e, 'budget_item', None) else ''
            expn = e.budget_item.expense if getattr(e, 'budget_item', None) else ''
            bi = e.budget_item if getattr(e, 'budget_item', None) else ''
            writer.writerow([
                e.id,
                e.date_incurred,
                e.date_recorded,
                e.vendor.name if e.vendor else '',
                str(dept) if dept else '',
                str(expn) if expn else '',
                str(bi) if bi else '',
                e.description,
                e.amount,
                e.vat,
                e.payment_status,
                e.approved_by or ''
            ])

        return response

    # Counts to help users diagnose empty results
    in_scope_count = expenditures.count()
    date_window_qs = Expenditure.objects.all()
    if start_date_obj:
        date_window_qs = date_window_qs.filter(**{f"{date_field_db}__gte": start_date_obj})
    if end_date_obj:
        date_window_qs = date_window_qs.filter(**{f"{date_field_db}__lte": end_date_obj})
    total_in_date_count = date_window_qs.count()
    out_of_scope_count = max(total_in_date_count - in_scope_count, 0)
    scope_applied = bool(scope_year and scope_term) and not show_all

    # Lists for filter UI
    academic_years = get_all_model_records(AcademicYear)
    terms = Term.objects.filter(academic_year=scope_year) if scope_year else get_all_model_records(Term)

    # Extra diagnostics
    unassigned_in_date_count = date_window_qs.filter(budget_item__isnull=True).count()
    
    context = {
        "expenditures": expenditures,
        "form": form,
        "edit_forms": edit_forms,
        "start_date": start_date,
        "end_date": end_date,
        "used_active_term_default": not (request.GET.get('start_date') or request.GET.get('end_date')),
        "academic_years": academic_years,
        "terms": terms,
        "selected_academic_year": int(academic_year_id) if academic_year_id else (current_year.id if current_year else None),
        "selected_term": int(term_id) if term_id else (current_term.id if current_term else None),
        "show_all": show_all,
        "include_unassigned": include_unassigned,
        "date_field": date_field,
        # diagnostics for empty result sets
        "out_of_scope_count": out_of_scope_count,
        "unassigned_in_date_count": unassigned_in_date_count,
        "scope_applied": scope_applied,
    }
    return render(request, "finance/expenditures.html", context)

@login_required
def add_expenditure(request):
    if request.method == "POST":
        form = finance_forms.ExpenditureForm(request.POST, request.FILES)
        if form.is_valid():
            expenditure = form.save()
            messages.success(request, SUCCESS_ADD_MESSAGE)
            return HttpResponsePermanentRedirect(reverse(manage_expenditure_items, args=[expenditure.id]))
        else:
            messages.error(request, FAILURE_MESSAGE)
            return HttpResponsePermanentRedirect(reverse(manage_expenditures))
    return HttpResponsePermanentRedirect(reverse(manage_expenditures))

@login_required
def edit_expenditures(request, id):
    expenditure = get_model_record(Expenditure, id)
    
    if request.method == 'POST':
        form = ExpenditureForm(request.POST, request.FILES, instance=expenditure)
        
        if form.is_valid():
            form.save()
            messages.success(request, SUCCESS_ADD_MESSAGE)
            return redirect(reverse(manage_expenditures))
        else:
            messages.error(request, FAILURE_MESSAGE)
    else:
        form = ExpenditureForm(instance=expenditure)

    # Inline HTML rendering
    return render(request, 'finance/edit_expenditure.html', {'form': form})

@login_required
def delete_expenditure(request, id):
    if request.method != "POST":
        messages.error(request, "Delete requests must be submitted via POST.")
        return HttpResponsePermanentRedirect(reverse(manage_expenditures))

    expenditure = get_model_record(Expenditure, id)
    
    expenditure.delete()
    messages.success(request, DELETE_MESSAGE)
    
    return HttpResponsePermanentRedirect(reverse(manage_expenditures))

@login_required
def manage_expenditure_items(request, id):
    expenditure = get_model_record(Expenditure, id)
    form = finance_forms.ExpenditureItemForm(initial={"expenditure": expenditure})
    expenditure_items = finance_selector.get_expenditure_items(expenditure)

    # Lock editing when the parent expenditure does not belong to the active term
    current_year, current_term = _get_current_year_and_term()
    belongs_to_active = False
    try:
        budget = expenditure.budget_item.budget if expenditure and expenditure.budget_item else None
        if budget and current_year and current_term:
            belongs_to_active = (
                budget.academic_year_id == current_year.id and
                budget.term_id == current_term.id
            )
    except Exception:
        belongs_to_active = False
    
    context = {
        "expenditure_items": expenditure_items,
        "form": form,
        "expenditure": expenditure,
        "editing_locked": not belongs_to_active
    }
    return render(request, "finance/expenditure_items.html", context)

@login_required
def add_expenditure_item(request):
    if request.method == "POST":
        form = finance_forms.ExpenditureItemForm(request.POST)
        expenditure_id = request.POST["expenditure"]

        # Enforce active-term scope for parent expenditure
        exp = get_model_record(Expenditure, expenditure_id)
        current_year, current_term = _get_current_year_and_term()
        allowed = False
        try:
            budget = exp.budget_item.budget if exp and exp.budget_item else None
            if budget and current_year and current_term:
                allowed = (
                    budget.academic_year_id == current_year.id and
                    budget.term_id == current_term.id
                )
        except Exception:
            allowed = False

        if not allowed:
            messages.error(request, "Cannot add items to an expenditure outside the active term.")
        elif form.is_valid():
            form.save()
            messages.success(request, SUCCESS_ADD_MESSAGE)
        else:
            messages.error(request, FAILURE_MESSAGE)

        return HttpResponsePermanentRedirect(reverse(manage_expenditure_items, args=[expenditure_id]))
    return HttpResponsePermanentRedirect(reverse(manage_expenditures))

@login_required
def edit_expenditure_items(request, id):
    expenditure_item = get_model_record(ExpenditureItem, id)
    if request.method == "POST":
        form = finance_forms.ExpenditureItemForm(request.POST, instance=expenditure_item)

        # Enforce active-term scope for parent expenditure
        exp = expenditure_item.expenditure
        current_year, current_term = _get_current_year_and_term()
        allowed = False
        try:
            budget = exp.budget_item.budget if exp and exp.budget_item else None
            if budget and current_year and current_term:
                allowed = (
                    budget.academic_year_id == current_year.id and
                    budget.term_id == current_term.id
                )
        except Exception:
            allowed = False

        if not allowed:
            messages.error(request, "Cannot edit items for an expenditure outside the active term.")
        elif form.is_valid():
            form.save()
            messages.success(request, SUCCESS_ADD_MESSAGE)
        else:
            messages.error(request, FAILURE_MESSAGE)

        expenditure_id = expenditure_item.expenditure.id
        return HttpResponsePermanentRedirect(reverse(manage_expenditure_items, args=[expenditure_id]))

    form = finance_forms.ExpenditureItemForm(instance=expenditure_item)
    # Determine if editing is allowed for this item based on active term
    current_year, current_term = _get_current_year_and_term()
    allowed = False
    try:
        exp = expenditure_item.expenditure
        budget = exp.budget_item.budget if exp and exp.budget_item else None
        if budget and current_year and current_term:
            allowed = (
                budget.academic_year_id == current_year.id and
                budget.term_id == current_term.id
            )
    except Exception:
        allowed = False
    context = {
        "form": form,
        "expenditure_item": expenditure_item,
        "editing_locked": not allowed
    }
    return render(request, "finance/edit_expenditure_item.html", context)

    

@login_required
def delete_expenditure_item(request, id):
    expenditure_item = get_model_record(ExpenditureItem, id)
    expenditure_id = expenditure_item.expenditure.id if getattr(expenditure_item, "expenditure", None) else None

    if request.method != "POST":
        messages.error(request, "Delete requests must be submitted via POST.")
        if expenditure_id:
            return HttpResponsePermanentRedirect(reverse(manage_expenditure_items, args=[expenditure_id]))
        return HttpResponsePermanentRedirect(reverse(manage_expenditures))

    # Enforce active-term scope for deletion
    allowed = False
    try:
        exp = expenditure_item.expenditure
        current_year, current_term = _get_current_year_and_term()
        budget = exp.budget_item.budget if exp and exp.budget_item else None
        if budget and current_year and current_term:
            allowed = (
                budget.academic_year_id == current_year.id and
                budget.term_id == current_term.id
            )
    except Exception:
        allowed = False

    if not allowed:
        messages.error(request, "Cannot delete items for an expenditure outside the active term.")
    else:
        # Delete then redirect back to the parent expenditure items page
        expenditure_item.delete()
        messages.success(request, DELETE_MESSAGE)

    if expenditure_id:
        return HttpResponsePermanentRedirect(reverse(manage_expenditure_items, args=[expenditure_id]))
    # Fallback: go to expenditures list if parent missing
    return HttpResponsePermanentRedirect(reverse(manage_expenditures))

@login_required
def manage_vendors(request):
    form = finance_forms.VendorForm()
    vendors = get_all_model_records(Vendor)
    
    context = {
        "vendors": vendors,
        "form": form
    }
    return render(request, "finance/vendors.html", context)

@login_required
def add_vendor(request):
    if request.method == "POST":
        form = finance_forms.VendorForm(request.POST, request.FILES)
        
        if form.is_valid():
            form.save()
            
            messages.success(request, SUCCESS_ADD_MESSAGE)
        else:
            messages.error(request, FAILURE_MESSAGE)
    
    return HttpResponsePermanentRedirect(reverse(manage_vendors))


@login_required
def edit_vendors(request, id):
    vendor = get_model_record(Vendor, id)
    if request.method=="POST":
        form = finance_forms.VendorForm(request.POST, request.FILES, instance=vendor)
    
        if form.is_valid():
           form.save()
           messages.success(request, SUCCESS_ADD_MESSAGE)
           return HttpResponsePermanentRedirect(reverse(manage_vendors))
        else:
           messages.error(request, FAILURE_MESSAGE)
           
    else:
        form = finance_forms.VendorForm(instance=vendor)
        
    context={
        "form": form,
        "vendor": vendor        
    }
    return render(request,"finance/edit_vendor.html",context)
    
  

@login_required
def delete_vendor(request, id):
    if request.method != "POST":
        messages.error(request, "Delete requests must be submitted via POST.")
        return HttpResponsePermanentRedirect(reverse(manage_vendors))

    vendor = get_model_record(Vendor, id)
    
    vendor.delete()
    messages.success(request, DELETE_MESSAGE)
    
    return HttpResponsePermanentRedirect(reverse(manage_vendors))

@login_required
def manage_budgets(request):
    form = finance_forms.BudgetForm()
    # By default show only the active term's budget; allow ?all=1 to show all
    show_all = request.GET.get('all') == '1' or request.GET.get('show_all') == '1'
    if show_all:
        budgets = get_all_model_records(Budget)
    else:
        current_year, current_term = _get_current_year_and_term()
        budgets = Budget.objects.filter(academic_year=current_year, term=current_term) if (current_year and current_term) else Budget.objects.none()
    
    context = {
        "budgets": budgets,
        "form": form,
        "show_all": show_all
    }
    return render(request, "finance/budgets.html", context)

@login_required
def add_budget(request):
    if request.method == "POST":
        form = finance_forms.BudgetForm(request.POST, request.FILES)
        
        if form.is_valid():
            form.save()
            
            messages.success(request, SUCCESS_ADD_MESSAGE)
        else:
            messages.error(request, FAILURE_MESSAGE)
    
    return HttpResponsePermanentRedirect(reverse(manage_budgets))


@login_required
def edit_budgets(request, id):
    budget = get_model_record(Budget,id)
    if request.method=="POST":
        form = finance_forms.BudgetForm(request.POST, request.FILES, instance=budget)
        
        if form.is_valid():
            form.save()
            messages.success(request,SUCCESS_ADD_MESSAGE)
            return HttpResponsePermanentRedirect(reverse(manage_budgets))
        else:
            messages.error(request,FAILURE_MESSAGE)
  
    form = finance_forms.BudgetForm(instance=budget)
        
    context={
        "form":form,
        "budget":budget
    }
    return render(request,"finance/edit_budget_page.html",context)


@login_required
def delete_budget(request, id):
    if request.method != "POST":
        messages.error(request, "Delete requests must be submitted via POST.")
        return HttpResponsePermanentRedirect(reverse(manage_budgets))

    budget = get_model_record(Budget, id)
    
    budget.delete()
    messages.success(request, DELETE_MESSAGE)
    
    return HttpResponsePermanentRedirect(reverse(manage_budgets))

@login_required
def manage_budget_items(request, id):
    budget = get_model_record(Budget, id)
    form = finance_forms.BudgetItemForm(initial={"budget": budget})
    budget_items = finance_selector.get_budget_items(budget)
    
    context = {
        "budget_items": budget_items,
        "form": form,
        "budget": budget
    }
    return render(request, "finance/budget_items.html", context)

@login_required
def add_budget_item(request):
    if request.method == "POST":
        form = finance_forms.BudgetItemForm(request.POST)
        budget = request.POST["budget"]
        
        if form.is_valid():
            item = form.save()
            
            messages.success(request, SUCCESS_ADD_MESSAGE)
        else:
            messages.error(request, FAILURE_MESSAGE)
    
    return HttpResponsePermanentRedirect(reverse(manage_budget_items, args=[budget]))


@login_required
def edit_budget_items(request, id):
    budget_item = get_model_record(BudgetItem, id)
    if request.method=="POST":
        form = finance_forms.BudgetItemForm(request.POST, instance=budget_item)
    
        if form.is_valid():
           form.save()
           messages.success(request, SUCCESS_ADD_MESSAGE)
    
        else:
            messages.error(request, FAILURE_MESSAGE)
            return HttpResponsePermanentRedirect(reverse(manage_budget_items, args=[budget_item.budget.id]))    
           
    form = finance_forms.BudgetItemForm(instance=budget_item)
    
    context={
        "form": form,
        "budget_item": budget_item
    }
    return render(request,"finance/edit_budget_item.html",context)
           

@login_required
def delete_budget_item(request, id):
    budget_item = get_model_record(BudgetItem, id)

    if request.method != "POST":
        messages.error(request, "Delete requests must be submitted via POST.")
        return HttpResponsePermanentRedirect(reverse(manage_budget_items, args=[budget_item.budget.id]))
    
    budget_item.delete()
    messages.success(request, DELETE_MESSAGE)
    
    return HttpResponsePermanentRedirect(reverse(manage_budget_items, args=[budget_item.budget.id]))





@login_required
def financial_summary_report(request):
    # Get filter parameters
    academic_year_id = request.GET.get('academic_year')
    term_id = request.GET.get('term')

    # Get all academic years and terms for filter dropdowns
    academic_years = get_all_model_records(AcademicYear)
    terms = get_all_model_records(Term)

    # Default to current if no filters
    if not academic_year_id:
        current_year = AcademicYear.objects.filter(is_current=True).first()
        academic_year_id = current_year.id if current_year else None

    if not term_id:
        current_term = Term.objects.filter(is_current=True).first()
        term_id = current_term.id if current_term else None

    # Initialize data structures
    class_data = []
    total_school_fees_billed = 0
    total_school_fees_collected = 0
    total_other_fees_collected = 0
    total_outstanding = 0
    total_other_income = 0
    total_expenditure = 0
    department_breakdown = {}
    total_other_fees_billed_global = 0  # Global accumulator for other fees billed
    over_expenditure_alerts = []
    budget_item_data = []
    academic_year = None
    term = None

    if academic_year_id and term_id:
        academic_year = get_model_record(AcademicYear, academic_year_id)
        term = get_model_record(Term, term_id)

        # Get all academic classes for the selected year and term
        academic_classes = AcademicClass.objects.filter(
            academic_year=academic_year,
            term=term
        ).select_related('Class', 'section')

        for academic_class in academic_classes:
            # Get all student bills for this class with related items
            student_bills = StudentBill.objects.filter(
                academic_class=academic_class,
                student__is_active=True,
            ).select_related('student').prefetch_related('items')

            # Get class bills for this academic class
            class_bills = ClassBill.objects.filter(
                academic_class=academic_class
            ).select_related('bill_item')

            num_students = student_bills.count()

            # Calculate school fees from actual bill items instead of using academic_class.fees_amount
            # This ensures it matches the dashboard calculation
            class_school_fees_billed = 0
            for bill in student_bills:
                for item in bill.items.all():
                    if ('tuition' in item.description.lower() or 'school' in item.description.lower() or 'fee' in item.description.lower()):
                        class_school_fees_billed += item.amount

            # Define school_fees_per_student for template context (use academic class amount for display)
            school_fees_per_student = academic_class.fees_amount

            # Calculate other fees from both StudentBillItem and ClassBill
            total_other_fees_billed = 0
            total_school_fees_collected_for_class = 0
            total_other_fees_collected_for_class = 0
            total_collected_for_class = 0
            total_outstanding_for_class = 0

            # Track students with other fees
            students_with_other_fees = 0

            # Process ClassBill for other fees (applied to all students)
            for class_bill in class_bills:
                if not ('tuition' in class_bill.bill_item.description.lower() or 'school' in class_bill.bill_item.description.lower() or 'fee' in class_bill.bill_item.description.lower()):
                    # This is applied to all students in the class
                    total_other_fees_billed += (class_bill.amount * num_students)

            # Process each student's bill items for additional other fees and payments
            for bill in student_bills:
                student_has_other_fees = False
                school_fees_for_student = 0
                other_fees_for_student = 0

                # Check each bill item for other fees (books, uniform, transport, etc.)
                for item in bill.items.all():
                    # Only count non-school fee items as other income
                    if not ('tuition' in item.description.lower() or 'school' in item.description.lower() or 'fee' in item.description.lower()):
                        total_other_fees_billed += item.amount
                        other_fees_for_student += item.amount
                        student_has_other_fees = True
                    else:
                        # This is a school fee item
                        school_fees_for_student += item.amount

                # Count students who have other fees
                if student_has_other_fees:
                    students_with_other_fees += 1

                # Simply use the actual payment amount as recorded
                # Don't try to allocate proportionally - use the payment as-is
                total_payment = bill.amount_paid
                total_collected_for_class += total_payment
                total_outstanding_for_class += bill.balance

                # For reporting purposes, assume all payments contribute to school fees collection
                # This gives a realistic view of collection performance
                total_school_fees_collected_for_class += total_payment

            # Calculate average other fees per student (only for students who have other fees)
            other_fees_per_student = total_other_fees_billed / students_with_other_fees if students_with_other_fees > 0 else 0

            # Calculate total collected for the class (both school and other fees)
            total_collected_for_class = total_school_fees_collected_for_class + total_other_fees_collected_for_class

            # Calculate collection rate: total collected / total billed
            # Use the actual payment amounts as recorded for realistic percentages
            total_billed_for_class = class_school_fees_billed + total_other_fees_billed
            collection_rate = (total_collected_for_class / total_billed_for_class * 100) if total_billed_for_class > 0 else 0

            class_data.append({
                'class_name': str(academic_class),
                'school_fees_per_student': school_fees_per_student,
                'other_fees_per_student': round(other_fees_per_student, 2),
                'num_students': num_students,
                'students_with_other_fees': students_with_other_fees,
                'total_school_fees': class_school_fees_billed,
                'total_other_fees': total_other_fees_billed,
                'total_collected': total_collected_for_class,
                'outstanding': total_outstanding_for_class,
                'collection_rate': round(collection_rate, 1)
            })

            total_school_fees_billed += class_school_fees_billed
            total_school_fees_collected += total_school_fees_collected_for_class
            total_other_fees_collected += total_other_fees_collected_for_class
            total_outstanding += total_outstanding_for_class
            # Add collected other fees to other income (not billed amount)
            total_other_income += total_other_fees_collected_for_class
            # Accumulate other fees billed globally
            total_other_fees_billed_global += total_other_fees_billed

            # Accumulate other fees billed globally
            total_other_fees_billed_global += total_other_fees_billed

        # Other income is now calculated from non-school fee bill items above
        # (books, uniform, transport, etc. are considered other income, not school fees)

        # Expenditures for the selected period
        budget = Budget.objects.filter(
            academic_year=academic_year,
            term=term
        ).first()

        expenditure_data = []

        if budget:
            # Get detailed expenditure data
            expenditures = Expenditure.objects.filter(
                budget_item__budget=budget
            ).select_related('budget_item__expense', 'budget_item__department')

            # Group expenditures by budget item
            expenditure_by_item = {}
            for expenditure in expenditures:
                item_key = expenditure.budget_item.id
                if item_key not in expenditure_by_item:
                    expenditure_by_item[item_key] = {
                        'budget_item': expenditure.budget_item,
                        'total_spent': 0,
                        'expenditures': []
                    }
                expenditure_by_item[item_key]['total_spent'] += expenditure.amount
                expenditure_by_item[item_key]['expenditures'].append(expenditure)
                total_expenditure += expenditure.amount

            # Get all budget items with expenditure data
            budget_items = BudgetItem.objects.filter(
                budget=budget
            ).select_related('department', 'expense')

            for item in budget_items:
                item_expenditure = expenditure_by_item.get(item.id, {'total_spent': 0, 'expenditures': []})

                # Calculate utilization percentage
                utilization = 0
                if item.allocated_amount > 0:
                    utilization = (item_expenditure['total_spent'] / item.allocated_amount) * 100

                budget_item_data.append({
                    'budget_item': item,
                    'allocated': item.allocated_amount,
                    'spent': item_expenditure['total_spent'],
                    'remaining': item.remaining_amount,
                    'utilization': round(utilization, 1),
                    'expenditures': item_expenditure['expenditures']
                })

                # Flag over-expenditure alerts
                if item_expenditure['total_spent'] > item.allocated_amount:
                    over_expenditure_alerts.append({
                        'department': str(item.department),
                        'expense': str(item.expense),
                        'allocated': item.allocated_amount,
                        'spent': item_expenditure['total_spent'],
                        'over_by': item_expenditure['total_spent'] - item.allocated_amount,
                        'utilization': round(utilization, 1),
                    })

                # Department breakdown for existing logic
                dept_name = str(item.department)
                if dept_name not in department_breakdown:
                    department_breakdown[dept_name] = {
                        'allocated': 0,
                        'spent': 0,
                        'remaining': 0,
                        'utilization': 0
                    }
                department_breakdown[dept_name]['allocated'] += item.allocated_amount
                department_breakdown[dept_name]['spent'] += item.amount_spent
                department_breakdown[dept_name]['remaining'] += item.remaining_amount

                # Calculate utilization for department
                if department_breakdown[dept_name]['allocated'] > 0:
                    department_breakdown[dept_name]['utilization'] = round((department_breakdown[dept_name]['spent'] / department_breakdown[dept_name]['allocated']) * 100, 1)
                else:
                    department_breakdown[dept_name]['utilization'] = 0


    total_income = total_school_fees_collected + total_other_income
    net_balance = total_income - total_expenditure

    # Calculate overall collection rate using actual payments received
    total_billed = total_school_fees_billed + total_other_fees_billed_global
    total_collected = total_income  # This is already school_fees_collected + other_income
    collection_rate = (total_collected / total_billed * 100) if total_billed > 0 else 0

    # Calculate budget utilization
    total_allocated = sum(item['allocated'] for item in budget_item_data) if budget_item_data else 0
    budget_utilization = (total_expenditure / total_allocated * 100) if total_allocated > 0 else 0

    # Calculate remaining budget explicitly
    remaining_budget = total_allocated - total_expenditure


    # Data Quality Validation
    data_quality_warnings = []

    # Check collection rate
    if collection_rate > 150:
        data_quality_warnings.append({
            'type': 'warning',
            'message': f'Collection rate ({collection_rate:.1f}%) is unusually high. This may indicate data quality issues.',
            'severity': 'high'
        })

    # Check outstanding balance ratio
    outstanding_ratio = (total_outstanding / total_income * 100) if total_income > 0 else 0
    if outstanding_ratio > 100:
        data_quality_warnings.append({
            'type': 'warning',
            'message': f'Outstanding balance (UGX {total_outstanding:,}) is {outstanding_ratio:.1f}% of total revenue. This seems unusually high.',
            'severity': 'high'
        })

    # Check for classes with unrealistic collection rates
    unrealistic_classes = []
    for class_info in class_data:
        if class_info['collection_rate'] > 200:  # Over 200% is definitely suspicious
            unrealistic_classes.append(f"{class_info['class_name']} ({class_info['collection_rate']:.1f}%)")

    if unrealistic_classes:
        data_quality_warnings.append({
            'type': 'error',
            'message': f'Classes with unrealistic collection rates: {", ".join(unrealistic_classes)}. Please verify payment data.',
            'severity': 'critical'
        })

    # Check if collected amounts are way higher than billed
    if total_collected > total_billed * 2:
        data_quality_warnings.append({
            'type': 'warning',
            'message': f'Total collected (UGX {total_collected:,}) is more than double the billed amount (UGX {total_billed:,}). This may indicate payment misallocation.',
            'severity': 'medium'
        })

    # Overall data quality assessment
    if data_quality_warnings:
        overall_quality = 'poor' if any(w['severity'] == 'critical' for w in data_quality_warnings) else 'fair'
    else:
        overall_quality = 'good'

    # Get names for display
    academic_year_name = academic_year.academic_year if academic_year_id and term_id else None
    term_name = term.term if academic_year_id and term_id else None

    context = {
        'academic_years': academic_years,
        'terms': terms,
        'selected_academic_year': academic_year_id,
        'selected_term': term_id,
        'academic_year_name': academic_year_name,
        'term_name': term_name,
        'class_data': class_data,
        'total_school_fees_billed': total_school_fees_billed,
        'total_school_fees_collected': total_school_fees_collected,
        'total_other_fees_collected': total_other_fees_collected,
        'total_outstanding': total_outstanding,
        'total_other_income': total_other_income,
        'total_income': total_income,
        'total_expenditure': total_expenditure,
        'net_balance': net_balance,
        'department_breakdown': department_breakdown,
        'budget_item_data': budget_item_data,
        'total_allocated': total_allocated,
        'remaining_budget': remaining_budget,
        'collection_rate': round(collection_rate, 2),
        'budget_utilization': round(budget_utilization, 2),
        'data_quality_warnings': data_quality_warnings,
        'overall_quality': overall_quality,
        'over_expenditure_alerts': over_expenditure_alerts,
        # Debug information
        'debug_info': {
            'total_billed': total_billed,
            'total_collected': total_collected,
            'total_income': total_income,
            'total_school_fees_billed': total_school_fees_billed,
            'total_other_fees_billed_global': total_other_fees_billed_global,
            'total_other_income': total_other_income,
            'net_balance': net_balance,
            'collection_rate_calc': f"{total_collected}/{total_billed} = {collection_rate:.1f}%" if total_billed > 0 else "No fees billed",
            'calculation_explanation': 'total_billed = school_fees_billed + other_fees_billed_global, total_collected = school_fees_collected + other_fees_collected'
        }
    }

    # CSV export
    if request.GET.get('export') == 'csv':
        response = HttpResponse(content_type='text/csv')
        filename_parts = []
        if academic_year_name:
            filename_parts.append(str(academic_year_name))
        if term_name:
            filename_parts.append(str(term_name))
        suffix = "_".join(filename_parts) if filename_parts else "all"
        response['Content-Disposition'] = f'attachment; filename="financial_summary_{suffix}.csv"'
        writer = csv.writer(response)

        # Executive summary section
        writer.writerow(['Financial Summary'])
        writer.writerow(['Academic Year', academic_year_name or ''])
        writer.writerow(['Term', term_name or ''])
        writer.writerow(['Total Revenue', total_income])
        writer.writerow(['Total Expenditure', total_expenditure])
        writer.writerow(['Net Balance', net_balance])
        writer.writerow(['Collection Rate (%)', round(collection_rate, 2)])
        writer.writerow(['Budget Utilization (%)', round(budget_utilization, 2)])
        writer.writerow([])

        # Class collection breakdown
        writer.writerow(['Class', 'Tuition per Student', 'Other Fees per Student', 'Students', 'Total Tuition Billed', 'Total Other Fees', 'Total Collected', 'Outstanding', 'Collection Rate (%)'])
        for c in class_data:
            writer.writerow([
                c.get('class_name', ''),
                c.get('school_fees_per_student', 0),
                c.get('other_fees_per_student', 0),
                c.get('num_students', 0),
                c.get('total_school_fees', 0),
                c.get('total_other_fees', 0),
                c.get('total_collected', 0),
                c.get('outstanding', 0),
                c.get('collection_rate', 0),
            ])
        writer.writerow([])

        # Budget items with utilization
        writer.writerow(['Department', 'Expense', 'Allocated', 'Spent', 'Remaining', 'Utilization (%)'])
        for bi in budget_item_data:
            writer.writerow([
                str(bi['budget_item'].department),
                str(bi['budget_item'].expense),
                bi.get('allocated', 0),
                bi.get('spent', 0),
                bi.get('remaining', 0),
                bi.get('utilization', 0),
            ])
        writer.writerow([])

        # Over-expenditure alerts
        if over_expenditure_alerts:
            writer.writerow(['Over-expenditure Alerts'])
            writer.writerow(['Department', 'Expense', 'Allocated', 'Spent', 'Over By', 'Utilization (%)'])
            for a in over_expenditure_alerts:
                writer.writerow([
                    a.get('department', ''),
                    a.get('expense', ''),
                    a.get('allocated', 0),
                    a.get('spent', 0),
                    a.get('over_by', 0),
                    a.get('utilization', 0),
                ])

        return response

    return render(request, 'finance/financial_summary_report.html', context)
           
           





@login_required
def vendor_payments_report(request):
    """
    Vendor Payments Report with optional vendor and date filters, plus CSV export.
    Non-destructive: reads existing Expenditures and aggregates by vendor.
    """
    vendor_id = request.GET.get('vendor')
    start_date_str = request.GET.get('start_date') or ''
    end_date_str = request.GET.get('end_date') or ''

    start_date = parse_date(start_date_str) if start_date_str else None
    end_date = parse_date(end_date_str) if end_date_str else None

    # Optional Year/Term overrides + Show All
    academic_year_id = request.GET.get('academic_year')
    term_id = request.GET.get('term')
    show_all = (request.GET.get('show_all') == '1') or (request.GET.get('all') == '1')

    current_year, current_term = _get_current_year_and_term()
    scope_year = None
    scope_term = None
    if not show_all:
        if academic_year_id and term_id:
            scope_year = AcademicYear.objects.filter(id=academic_year_id).first()
            scope_term = Term.objects.filter(id=term_id, academic_year=scope_year).first() if scope_year else None
        else:
            scope_year, scope_term = current_year, current_term

    # Default to scoped term dates if none provided
    if not (start_date and end_date) and scope_term:
        start_date = start_date or scope_term.start_date
        end_date = end_date or scope_term.end_date
        start_date_str = start_date.isoformat()
        end_date_str = end_date.isoformat()

    vendors = get_all_model_records(Vendor)

    expenditures_qs = (
        Expenditure.objects.select_related('vendor', 'budget_item__department', 'budget_item__expense')
        .filter(vendor__isnull=False)
    )

    # Restrict to selected/active term unless show_all
    if scope_year and scope_term:
        expenditures_qs = expenditures_qs.filter(
            budget_item__budget__academic_year=scope_year,
            budget_item__budget__term=scope_term,
        )

    expenditures_qs = expenditures_qs.order_by('-date_incurred', '-id')

    if vendor_id:
        expenditures_qs = expenditures_qs.filter(vendor_id=vendor_id)
    if start_date:
        expenditures_qs = expenditures_qs.filter(date_incurred__gte=start_date)
    if end_date:
        expenditures_qs = expenditures_qs.filter(date_incurred__lte=end_date)

    # Aggregate in Python since Expenditure.amount is a computed property
    vendor_summary = {}
    total_spent = 0
    breakdown = list(expenditures_qs)

    for e in breakdown:
        amt = e.amount
        total_spent += amt
        key = e.vendor_id
        if key not in vendor_summary:
            vendor_summary[key] = {'vendor': e.vendor, 'count': 0, 'total': 0}
        vendor_summary[key]['count'] += 1
        vendor_summary[key]['total'] += amt

    summary = sorted(
        [{'vendor': v['vendor'], 'count': v['count'], 'total': v['total']} for v in vendor_summary.values()],
        key=lambda x: x['total'],
        reverse=True
    )
    # Add percentage share per vendor (of total spent) for template display
    for row in summary:
        row['pct'] = round((row['total'] / total_spent * 100), 1) if total_spent else 0

    # CSV export
    if request.GET.get('export') == 'csv':
        response = HttpResponse(content_type='text/csv')
        filename_parts = ['vendor_payments']
        if vendor_id:
            try:
                vendor_obj = Vendor.objects.get(id=vendor_id)
                filename_parts.append(vendor_obj.name.replace(' ', '_'))
            except Vendor.DoesNotExist:
                pass
        if start_date_str:
            filename_parts.append(f"from_{start_date_str}")
        if end_date_str:
            filename_parts.append(f"to_{end_date_str}")
        if scope_year:
            filename_parts.append(f"year_{scope_year.id}")
        if scope_term:
            filename_parts.append(f"term_{scope_term.id}")
        fname = "_".join(filename_parts) if filename_parts else "vendor_payments"
        response['Content-Disposition'] = f'attachment; filename="{fname}.csv"'
        writer = csv.writer(response)

        writer.writerow(['Vendor Payments Summary'])
        writer.writerow(['Vendor', 'Transactions', 'Total Spent'])
        for row in summary:
            writer.writerow([
                row['vendor'].name if row['vendor'] else '',
                row['count'],
                row['total'],
            ])
        writer.writerow([])

        writer.writerow(['Detailed Expenditures'])
        writer.writerow(['Date', 'Vendor', 'Department', 'Expense', 'Description', 'Amount', 'VAT'])
        for e in breakdown:
            writer.writerow([
                e.date_incurred,
                e.vendor.name if e.vendor else '',
                str(e.budget_item.department) if e.budget_item else '',
                str(e.budget_item.expense) if e.budget_item else '',
                e.description,
                e.amount,
                e.vat,
            ])
        return response

    # Lists for filter UI
    academic_years = get_all_model_records(AcademicYear)
    terms = Term.objects.filter(academic_year=scope_year) if scope_year else get_all_model_records(Term)

    context = {
        'vendors': vendors,
        'selected_vendor': int(vendor_id) if vendor_id else None,
        'start_date': start_date_str,
        'end_date': end_date_str,
        'summary': summary,
        'breakdown': breakdown,
        'total_spent': total_spent,
        'academic_years': academic_years,
        'terms': terms,
        'selected_academic_year': int(academic_year_id) if academic_year_id else (current_year.id if current_year else None),
        'selected_term': int(term_id) if term_id else (current_term.id if current_term else None),
        'show_all': show_all,
    }
    return render(request, 'finance/vendor_report.html', context)

@login_required
def approve_expenditure(request, id):
    """Approve an expenditure by setting the approved_by field to the current user."""
    expenditure = get_model_record(Expenditure, id)
    if request.method == "POST":
        approver = ""
        try:
            approver = request.user.get_full_name()
        except Exception:
            pass
        approver = approver or getattr(request.user, "username", str(request.user))

        expenditure.approved_by = approver
        expenditure.save(update_fields=["approved_by"])
        messages.success(request, "Expenditure approved successfully.")
    else:
        messages.error(request, "Invalid request method. Use POST to approve.")
    return HttpResponsePermanentRedirect(reverse(manage_expenditures))


@login_required
def revoke_expenditure_approval(request, id):
    """Revoke approval for an expenditure by clearing the approved_by field."""
    expenditure = get_model_record(Expenditure, id)
    if request.method == "POST":
        expenditure.approved_by = None
        expenditure.save(update_fields=["approved_by"])
        messages.success(request, "Expenditure approval revoked.")
    else:
        messages.error(request, "Invalid request method. Use POST to revoke approval.")
    return HttpResponsePermanentRedirect(reverse(manage_expenditures))

@login_required
def income_statement_report(request):
    """
    Income Statement using Transaction model, with date filters and CSV export.
    Non-destructive: reads existing Transactions; does not mutate data.
    """
    start_date_str = request.GET.get('start_date') or ''
    end_date_str = request.GET.get('end_date') or ''
    start_date = parse_date(start_date_str) if start_date_str else None
    end_date = parse_date(end_date_str) if end_date_str else None

    used_term_default = False
    # Default to current term when no explicit range is provided
    if not (start_date and end_date):
        current_year = AcademicYear.objects.filter(is_current=True).first()
        current_term = Term.objects.filter(is_current=True, academic_year=current_year).first() if current_year else Term.objects.filter(is_current=True).first()
        if current_term and getattr(current_term, "start_date", None) and getattr(current_term, "end_date", None):
            start_date = current_term.start_date
            end_date = current_term.end_date
            start_date_str = start_date.isoformat()
            end_date_str = end_date.isoformat()
            used_term_default = True

    has_range = bool(start_date and end_date)
    # Toggle basis for Income Statement: 'accrual' (default) or 'cash'
    mode = (request.GET.get('mode') or 'accrual').lower()
    if mode not in ('accrual', 'cash'):
        mode = 'accrual'

    if has_range:
        tx_qs = (
            Transaction.objects.all()
            .order_by('date')
            .filter(date__gte=start_date, date__lte=end_date)
        )
    else:
        tx_qs = Transaction.objects.none()

    # Build Income Statement data based on selected mode
    class SimpleIncome:
        def __init__(self, date, description, amount, source_name='School fees'):
            self.date = date
            self.description = description
            self.amount = amount
            # minimal object with .name for template compatibility
            self.related_income_source = type('Src', (), {'name': source_name})()

    class SimpleExpense:
        def __init__(self, date, description, amount):
            self.date = date
            self.description = description
            self.amount = amount

    if mode == 'accrual':
        # Revenue: billed (earned) within date range (student bill items by bill date)
        billed_qs = StudentBillItem.objects.filter(
            bill__bill_date__gte=start_date,
            bill__bill_date__lte=end_date,
            bill__student__is_active=True,
        ).select_related('bill')

        income_list = [
            SimpleIncome(
                sbi.bill.bill_date,
                sbi.description,
                sbi.amount
            ) for sbi in billed_qs
        ]
    
        # Group identical accrual income rows by (date, description, source) to avoid visually noisy duplicates
        if mode == 'accrual':
            buckets = {}
            for r in income_list:
                key = (r.date, r.description, getattr(r.related_income_source, 'name', ''))
                if key in buckets:
                    buckets[key].amount += r.amount
                else:
                    buckets[key] = SimpleIncome(
                        r.date,
                        r.description,
                        r.amount,
                        getattr(r.related_income_source, 'name', 'School fees')
                    )
            income_list = [buckets[k] for k in sorted(buckets.keys(), key=lambda x: (x[0], x[1]))]

        # In accrual mode, include non-fee income transactions from the ledger.
        # School-fee cash receipts are excluded to avoid double-counting billed fees.
        accrual_other_income_qs = (
            tx_qs.filter(transaction_type='Income')
            .exclude(related_income_source__name__iexact='School fees')
            .select_related('related_income_source')
        )
        income_list.extend(accrual_other_income_qs)
        income_list = sorted(
            income_list,
            key=lambda row: (
                row.date,
                row.description,
                getattr(getattr(row, 'related_income_source', None), 'name', ''),
            ),
        )

        # Expenses: incurred within date range
        expenditures_qs = Expenditure.objects.filter(
            date_incurred__gte=start_date,
            date_incurred__lte=end_date
        ).select_related('vendor')

        expense_list = [
            SimpleExpense(
                e.date_incurred,
                f"Expenditure#{e.id} {(e.vendor.name if e.vendor else 'No vendor')}",
                e.amount
            ) for e in expenditures_qs
        ]
    else:
        # Cash mode: revenue comes from income transactions (including fee mirrors and other income sources)
        income_list = list(
            tx_qs.filter(transaction_type='Income')
            .select_related('related_income_source')
            .order_by('date')
        )

        expenditures_paid_qs = Expenditure.objects.filter(
            payment_status='Paid',
            date_recorded__gte=start_date,
            date_recorded__lte=end_date
        ).select_related('vendor')

        expense_list = [
            SimpleExpense(
                e.date_recorded,
                f"Expenditure#{e.id} {(e.vendor.name if e.vendor else 'No vendor')}",
                e.amount
            ) for e in expenditures_paid_qs
        ]

    # Totals
    total_income = sum((i.amount for i in income_list), 0)
    total_expense = sum((e.amount for e in expense_list), 0)
    net_income = total_income - total_expense

    # Income by Source
    income_totals_by_source = {}
    for row in income_list:
        source_name = getattr(getattr(row, 'related_income_source', None), 'name', None) or 'Other Income'
        income_totals_by_source[source_name] = income_totals_by_source.get(source_name, 0) + row.amount
    income_breakdown = [
        {'source': source_name, 'total': total}
        for source_name, total in income_totals_by_source.items()
    ]
    income_breakdown.sort(key=lambda x: x['total'], reverse=True)

    # CSV export
    if request.GET.get('export') == 'csv':
        response = HttpResponse(content_type='text/csv')
        parts = ['income_statement']
        if start_date_str:
            parts.append(f'from_{start_date_str}')
        if end_date_str:
            parts.append(f'to_{end_date_str}')
        fname = '_'.join(parts)
        response['Content-Disposition'] = f'attachment; filename="{fname}.csv"'
        w = csv.writer(response)

        w.writerow(['Income Statement'])
        w.writerow(['Start Date', start_date_str])
        w.writerow(['End Date', end_date_str])
        w.writerow(['Total Income', total_income])
        w.writerow(['Total Expense', total_expense])
        w.writerow(['Net Income', net_income])
        w.writerow([])

        w.writerow(['Income by Source'])
        w.writerow(['Source', 'Amount'])
        for row in income_breakdown:
            w.writerow([row['source'], row['total']])
        w.writerow([])

        w.writerow(['Income Transactions'])
        w.writerow(['Date', 'Description', 'Source', 'Amount'])
        for t in income_list:
            w.writerow([
                t.date,
                t.description,
                t.related_income_source.name if t.related_income_source else '',
                t.amount
            ])
        w.writerow([])

        w.writerow(['Expense Transactions'])
        w.writerow(['Date', 'Description', 'Amount'])
        for t in expense_list:
            w.writerow([t.date, t.description, t.amount])

        return response

    context = {
        'start_date': start_date_str,
        'end_date': end_date_str,
        'used_term_default': used_term_default,
        'mode': mode,
        'total_income': total_income,
        'total_expense': total_expense,
        'net_income': net_income,
        'income_breakdown': income_breakdown,
        'income_tx': income_list,
        'expense_tx': expense_list,
        # sample rows for notice banner
        'sample_income': income_list[:5],
        'sample_expense': expense_list[:5],
    }
    return render(request, 'finance/income_statement.html', context)

@login_required
def cash_flow_report(request):
    """
    Cash Flow Report using Transaction model with date filters and CSV export.
    Non-destructive: reads existing Transactions; does not mutate data.
    """
    start_date_str = request.GET.get('start_date') or ''
    end_date_str = request.GET.get('end_date') or ''
    start_date = parse_date(start_date_str) if start_date_str else None
    end_date = parse_date(end_date_str) if end_date_str else None

    # Default to current term when no explicit range is provided
    used_term_default = False
    if not (start_date and end_date):
        current_year = AcademicYear.objects.filter(is_current=True).first()
        current_term = Term.objects.filter(is_current=True, academic_year=current_year).first() if current_year else Term.objects.filter(is_current=True).first()
        if current_term and getattr(current_term, "start_date", None) and getattr(current_term, "end_date", None):
            start_date = current_term.start_date
            end_date = current_term.end_date
            start_date_str = start_date.isoformat()
            end_date_str = end_date.isoformat()
            used_term_default = True

    has_range = bool(start_date and end_date)
    if has_range:
        tx_qs = Transaction.objects.filter(date__gte=start_date, date__lte=end_date).order_by('date')
    else:
        tx_qs = Transaction.objects.none()

    # Cash basis: inflows from Payments; outflows only from actually paid Expenditures
    pay_qs = Payment.objects.filter(
        payment_date__gte=start_date,
        payment_date__lte=end_date,
        bill__student__is_active=True,
    )

    # If your workflow marks paid expenditures via payment_status, we approximate cash payments
    # using payment_status='Paid' and date_recorded as the paid date.
    exp_qs = Expenditure.objects.filter(
        payment_status='Paid',
        date_recorded__gte=start_date,
        date_recorded__lte=end_date
    ).select_related('vendor')

    class SimpleIncome:
        def __init__(self, date, description, amount):
            self.date = date
            self.description = description
            self.amount = amount

    class SimpleExpense:
        def __init__(self, date, description, amount):
            self.date = date
            self.description = description
            self.amount = amount

    income_list = [
        SimpleIncome(
            p.payment_date,
            f"Student payment bill#{p.bill_id} ref {p.reference_no}",
            p.amount
        ) for p in pay_qs
    ]
    expense_list = [
        SimpleExpense(
            e.date_recorded,
            f"Expenditure#{e.id} {(e.vendor.name if e.vendor else 'No vendor')}",
            e.amount
        ) for e in exp_qs
    ]

    # Totals
    total_income = sum((t.amount for t in income_list), 0)
    total_expenses = sum((t.amount for t in expense_list), 0)
    net_cash_flow = total_income - total_expenses

    # Daily net flow timeline (cash movements)
    flow_by_date = {}
    for t in income_list:
        key = t.date
        flow_by_date[key] = flow_by_date.get(key, 0) + t.amount
    for t in expense_list:
        key = t.date
        flow_by_date[key] = flow_by_date.get(key, 0) - t.amount

    daily_flow = [{'date': d, 'net': flow_by_date[d]} for d in sorted(flow_by_date.keys())]

    # CSV export
    if request.GET.get('export') == 'csv':
        response = HttpResponse(content_type='text/csv')
        parts = ['cash_flow']
        if start_date_str:
            parts.append(f'from_{start_date_str}')
        if end_date_str:
            parts.append(f'to_{end_date_str}')
        fname = '_'.join(parts)
        response['Content-Disposition'] = f'attachment; filename="{fname}.csv"'
        w = csv.writer(response)

        w.writerow(['Cash Flow Report'])
        w.writerow(['Start Date', start_date_str])
        w.writerow(['End Date', end_date_str])
        w.writerow(['Total Income', total_income])
        w.writerow(['Total Expenses', total_expenses])
        w.writerow(['Net Cash Flow', net_cash_flow])
        w.writerow([])

        w.writerow(['Daily Net Flow'])
        w.writerow(['Date', 'Net'])
        for row in daily_flow:
            w.writerow([row['date'], row['net']])
        w.writerow([])

        w.writerow(['Income Transactions'])
        w.writerow(['Date', 'Description', 'Amount'])
        for t in income_list:
            w.writerow([t.date, t.description, t.amount])
        w.writerow([])

        w.writerow(['Expense Transactions'])
        w.writerow(['Date', 'Description', 'Amount'])
        for t in expense_list:
            w.writerow([t.date, t.description, t.amount])

        return response

    context = {
        'start_date': start_date_str,
        'end_date': end_date_str,
        'used_term_default': used_term_default,
        'total_income': total_income,
        'total_expenses': total_expenses,
        'net_cash_flow': net_cash_flow,
        'daily_flow': daily_flow,
        'income_tx': income_list,
        'expense_tx': expense_list,
        # sample rows for notice banner
        'sample_income': income_list[:5],
        'sample_expense': expense_list[:5],
    }
    return render(request, 'finance/cash_flow.html', context)

@login_required
def bank_reconciliation_view(request):
    """Enhanced bank reconciliation with automated matching"""
    bank_accounts = BankAccount.objects.all()
    statements = BankStatement.objects.select_related('bank_account').order_by('-statement_date')

    # Optional Year/Term overrides + Show All
    academic_year_id = request.GET.get('academic_year')
    term_id = request.GET.get('term')
    show_all = (request.GET.get('show_all') == '1') or (request.GET.get('all') == '1')

    current_year, current_term = _get_current_year_and_term()
    scope_year = None
    scope_term = None
    if not show_all:
        if academic_year_id and term_id:
            scope_year = AcademicYear.objects.filter(id=academic_year_id).first()
            scope_term = Term.objects.filter(id=term_id, academic_year=scope_year).first() if scope_year else None
        else:
            scope_year, scope_term = current_year, current_term

    # Get unreconciled bank transactions with optional term window
    unreconciled_transactions = BankTransaction.objects.filter(
        reconciled=False
    ).select_related('bank_statement__bank_account')

    if scope_term:
        unreconciled_transactions = unreconciled_transactions.filter(
            transaction_date__gte=scope_term.start_date,
            transaction_date__lte=scope_term.end_date
        )

    unreconciled_transactions = unreconciled_transactions.order_by('-transaction_date')

    # Get unmatched payments for reconciliation (exclude payments already reconciled by any bank transaction)
    unmatched_payments = Payment.objects.exclude(
        id__in=BankTransaction.objects.filter(
            reconciled=True, reconciled_with__isnull=False
        ).values_list('reconciled_with_id', flat=True)
    ).filter(bill__student__is_active=True)

    # Scope unmatched payments to selected/active year/term and date window
    if scope_year and scope_term:
        unmatched_payments = unmatched_payments.filter(
            bill__academic_class__academic_year=scope_year,
            bill__academic_class__term=scope_term,
            payment_date__gte=scope_term.start_date,
            payment_date__lte=scope_term.end_date
        )

    unmatched_payments = unmatched_payments.order_by('-payment_date')

    # Lists for filter UI
    academic_years = get_all_model_records(AcademicYear)
    terms = Term.objects.filter(academic_year=scope_year) if scope_year else get_all_model_records(Term)

    context = {
        'bank_accounts': bank_accounts,
        'statements': statements,
        'unreconciled_transactions': unreconciled_transactions,
        'unmatched_payments': unmatched_payments,
        'academic_years': academic_years,
        'terms': terms,
        'selected_academic_year': int(academic_year_id) if academic_year_id else (current_year.id if current_year else None),
        'selected_term': int(term_id) if term_id else (current_term.id if current_term else None),
        'show_all': show_all,
    }
    return render(request, 'finance/bank_reconciliation.html', context)

@login_required
def upload_bank_statement_view(request):
    """Upload and process bank statements"""
    if request.method == 'POST' and request.FILES.get('statement_file'):
        bank_account_id = request.POST.get('bank_account')
        statement_date = request.POST.get('statement_date')

        try:
            bank_account = BankAccount.objects.get(id=bank_account_id)
            statement = BankStatement.objects.create(
                bank_account=bank_account,
                statement_date=statement_date,
                opening_balance=request.POST.get('opening_balance', 0),
                closing_balance=request.POST.get('closing_balance', 0),
                uploaded_by=request.user.staff if hasattr(request.user, 'staff') else None,
                file=request.FILES.get('statement_file')
            )

            # Process CSV file
            if statement.file.name.endswith('.csv'):
                process_bank_statement_csv(statement)

            messages.success(request, "Bank statement uploaded successfully")
        except Exception as e:
            messages.error(request, f"Error uploading statement: {str(e)}")

    return redirect('bank_reconciliation')

def process_bank_statement_csv(statement):
    """Process uploaded CSV bank statement"""
    import csv
    import codecs

    with open(statement.file.path, 'r', encoding='utf-8') as file:
        reader = csv.DictReader(file)

        for row in reader:
            BankTransaction.objects.create(
                bank_statement=statement,
                transaction_date=row.get('Date', row.get('date')),
                description=row.get('Description', row.get('description', '')),
                amount=row.get('Amount', row.get('amount', 0)),
                transaction_type='Credit' if float(row.get('Amount', 0)) > 0 else 'Debit',
                reference=row.get('Reference', row.get('reference', '')),
            )

@login_required
def reconcile_transaction_view(request, transaction_id):
    """Reconcile bank transaction with payment"""
    if request.method == 'POST':
        transaction = get_object_or_404(BankTransaction, id=transaction_id)
        payment_id = request.POST.get('payment_id')

        if payment_id:
            payment = get_object_or_404(Payment, id=payment_id)
            transaction.reconciled = True
            transaction.reconciled_with = payment
            transaction.reconciliation_date = timezone.now()
            transaction.save()

            messages.success(request, "Transaction reconciled successfully")
        else:
            messages.error(request, "Please select a payment to reconcile with")

    return redirect('bank_reconciliation')

@login_required
def financial_dashboard_view(request):
    """Enhanced financial dashboard with charts and KPIs"""
    # Get current academic year and term
    current_year = AcademicYear.objects.filter(is_current=True).first()
    current_term = Term.objects.filter(is_current=True, academic_year=current_year).first() if current_year else None

    dashboard_data = {}

    if current_year and current_term:
        # Fee Collection KPIs
        # Sum billed amounts from actual bill items since total_amount is a Python property (not a DB field)
        total_billed = StudentBillItem.objects.filter(
            bill__academic_class__academic_year=current_year,
            bill__academic_class__term=current_term,
            bill__student__is_active=True,
        ).aggregate(total=Sum('amount'))['total'] or 0

        total_collected = Payment.objects.filter(
            bill__academic_class__academic_year=current_year,
            bill__academic_class__term=current_term,
            bill__student__is_active=True,
        ).aggregate(total=Sum('amount'))['total'] or 0

        collection_rate = (total_collected / total_billed * 100) if total_billed > 0 else 0

        # Budget vs Actual
        budget = Budget.objects.filter(academic_year=current_year, term=current_term).first()
        total_budget = budget.budget_total if budget else 0
        # Use Python-side aggregation because Expenditure.amount is a property
        if budget:
            exp_list = list(
                Expenditure.objects.filter(
                    budget_item__budget=budget,
                    date_incurred__gte=current_term.start_date,
                    date_incurred__lte=current_term.end_date
                ).prefetch_related('items')
            )
            total_expenditure = sum((e.amount for e in exp_list), 0)
        else:
            total_expenditure = 0

        budget_utilization = (total_expenditure / total_budget * 100) if total_budget > 0 else 0

        # Monthly trends
        monthly_collection = Payment.objects.filter(
            bill__academic_class__academic_year=current_year,
            bill__academic_class__term=current_term,
            bill__student__is_active=True,
        ).annotate(
            month=TruncMonth('payment_date')
        ).values('month').annotate(
            total=Sum('amount')
        ).order_by('month')

        # Compute monthly expenditure in Python
        if budget:
            month_totals = {}
            for e in exp_list:
                m = e.date_incurred.replace(day=1)
                month_totals[m] = month_totals.get(m, 0) + e.amount
            monthly_expenditure = [{'month': m, 'total': t} for m, t in sorted(month_totals.items())]
        else:
            monthly_expenditure = []

        dashboard_data = {
            'collection_rate': round(collection_rate, 1),
            'total_billed': total_billed,
            'total_collected': total_collected,
            'budget_utilization': round(budget_utilization, 1),
            'total_budget': total_budget,
            'total_expenditure': total_expenditure,
            'monthly_collection': list(monthly_collection),
            'monthly_expenditure': list(monthly_expenditure),
            'current_year': current_year,
            'current_term': current_term,
        }

    context = {
        'dashboard_data': dashboard_data,
        'recent_expenditures': Expenditure.objects.order_by('-date_incurred')[:10],
        'pending_approvals': (
            ApprovalWorkflow.objects.filter(
                current_approver=request.user.staff, status='pending'
            ).select_related('expenditure')
            if hasattr(request.user, 'staff') and request.user.staff
            else ApprovalWorkflow.objects.filter(status='pending').select_related('expenditure')[:10]
        ),
    }
    return render(request, 'finance/financial_dashboard.html', context)

@login_required
def send_payment_reminders_view(request):
    """Send automated payment reminders to parents"""
    if request.method == 'POST':
        reminder_type = request.POST.get('reminder_type', 'upcoming_deadline')

        # Get students with outstanding fees
        if reminder_type == 'upcoming_deadline':
            # Students with fees due in next 7 days
            upcoming_bills = StudentBill.objects.filter(
                due_date__gte=timezone.now().date(),
                due_date__lte=timezone.now().date() + timedelta(days=7),
                status__in=['Unpaid', 'Partial'],
                student__is_active=True,
            ).select_related('student')

        elif reminder_type == 'overdue':
            # Students with overdue fees
            overdue_bills = StudentBill.objects.filter(
                due_date__lt=timezone.now().date(),
                status__in=['Unpaid', 'Partial'],
                student__is_active=True,
            ).select_related('student')

        elif reminder_type == 'final_notice':
            # Students with fees overdue by more than 30 days
            final_notice_bills = StudentBill.objects.filter(
                due_date__lt=timezone.now().date() - timedelta(days=30),
                status__in=['Unpaid', 'Partial'],
                student__is_active=True,
            ).select_related('student')

        # Send notifications (implement email/SMS logic here)
        notifications_sent = 0

        # Create in-app notifications
        for bill in StudentBill.objects.filter(
            status__in=['Unpaid', 'Partial'],
            student__is_active=True,
        ):
            FinancialNotification.objects.create(
                recipient=bill.student,
                notification_type='payment_reminder',
                title='School Fee Reminder',
                message=f'Dear {bill.student.student_name}, you have outstanding fees of UGX {bill.balance:,} for {bill.academic_class}. Please make payment before the due date.',
                action_required=True,
                related_object_type='StudentBill',
                related_object_id=bill.id
            )
            notifications_sent += 1

        messages.success(request, f"Payment reminders sent to {notifications_sent} students")

    return redirect('financial_dashboard')

@login_required
def approval_workflow_view(request):
    """Multi-level approval workflow for expenditures"""
    if request.method == 'POST':
        expenditure_id = request.POST.get('expenditure_id')
        action = request.POST.get('action')  # approve, reject, escalate

        expenditure = get_object_or_404(Expenditure, id=expenditure_id)
        workflow = expenditure.approval_workflow

        if action == 'approve':
            if workflow.approval_level < workflow.max_approval_level:
                # Escalate to next level
                next_approver = get_next_approver(workflow.approval_level + 1)
                workflow.current_approver = next_approver
                workflow.approval_level += 1
                workflow.comments = request.POST.get('comments', '')
                workflow.save()
                messages.info(request, f"Expenditure escalated to level {workflow.approval_level} approval")
            else:
                # Final approval
                workflow.status = 'approved'
                workflow.approved_by = request.user.staff if hasattr(request.user, 'staff') else None
                workflow.approved_date = timezone.now()
                workflow.save()

                # Update expenditure status
                expenditure.payment_status = 'Approved'
                expenditure.save()

                messages.success(request, "Expenditure fully approved")

        elif action == 'reject':
            workflow.status = 'rejected'
            workflow.rejection_reason = request.POST.get('rejection_reason', '')
            workflow.save()

            expenditure.payment_status = 'Rejected'
            expenditure.save()

            messages.success(request, "Expenditure rejected")

    # Get pending approvals for current user
    pending_approvals = ApprovalWorkflow.objects.filter(
        current_approver=request.user.staff if hasattr(request.user, 'staff') else None,
        status='pending'
    ).select_related('expenditure')

    context = {
        'pending_approvals': pending_approvals,
    }
    return render(request, 'finance/approval_workflow.html', context)

def get_next_approver(level):
    """Get next approver based on level (implement your logic)"""
    # This is a placeholder - implement based on your organizational structure
    staff = Staff.objects.filter(role__name='Head Teacher').first()
    return staff

@login_required
def export_financial_data_view(request):
    """Export financial data for accounting software integration"""
    export_type = request.GET.get('type', 'quickbooks')

    if export_type == 'quickbooks':
        # Generate QuickBooks IIF format
        response = HttpResponse(content_type='text/plain')
        response['Content-Disposition'] = 'attachment; filename="financial_data.iif"'

        # Generate IIF content (simplified example)
        content = generate_quickbooks_iif()
        response.write(content)

    elif export_type == 'sage':
        # Generate Sage CSV format
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="financial_data.csv"'

        content = generate_sage_csv()
        response.write(content)

    return response

def generate_quickbooks_iif():
    """Generate QuickBooks IIF format export"""
    iif_content = "!TRNS\tTRNSTYPE\tDATE\tACCNT\tNAME\tAMOUNT\tMEMO\n"
    iif_content += "!SPL\tTRNSTYPE\tDATE\tACCNT\tNAME\tAMOUNT\tMEMO\n"
    iif_content += "!ENDTRNS\n"

    # Add transaction data here
    return iif_content

def generate_sage_csv():
    """Generate Sage CSV format export"""
    csv_content = "Date,Account,Description,Amount,Reference\n"

    # Add transaction data here
    return csv_content
