from django.shortcuts import render, redirect, HttpResponseRedirect
from django.contrib import messages
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from app.constants import *
from app.forms.school_settings import SectionForm
from app.models.school_settings import (
    SchoolSetting,
    Currency,
    Section,
)
from app.services.level_scope import get_level_sections_queryset
from app.services.school_level import get_level_label, set_active_school_level
import app.selectors.school_settings as school_settings_selectors
import app.services.school_settings as school_settings_services
import app.forms.school_settings as school_settings_forms
from app.selectors.model_selectors import *
from django.contrib.auth.decorators import *
from app.decorators.decorators import *


def _normalize_section_name(value: str) -> str:
    return "".join(ch for ch in (value or "").lower() if ch.isalnum())


def _ensure_default_sections_for_enabled_levels(school_setting: SchoolSetting) -> None:
    desired_sections = []
    if school_setting.offers_primary:
        desired_sections.append("Primary")
    if school_setting.offers_secondary_lower or school_setting.offers_secondary_upper:
        desired_sections.extend(["O-Level", "A-Level"])

    if not desired_sections:
        desired_sections = ["Primary"]

    existing_names = list(Section.objects.values_list("section_name", flat=True))
    existing_keys = {_normalize_section_name(name) for name in existing_names}
    for section_name in desired_sections:
        key = _normalize_section_name(section_name)
        if key in existing_keys:
            continue
        Section.objects.create(section_name=section_name)
        existing_keys.add(key)


@login_required
def settings_page(request):
    all_currencies = school_settings_selectors.get_all_currencies()
    school_settings = SchoolSetting.load()
    _ensure_default_sections_for_enabled_levels(school_settings)
    school_sections = get_level_sections_queryset(request=request)
    signatures = school_settings_selectors.get_signatures()
    departments = school_settings_selectors.get_all_departments()   
    school_settings_form = school_settings_forms.SchoolSettingForm(instance=school_settings)
    sections_form = school_settings_forms.SectionForm()
    signature_form = school_settings_forms.SignatureForm()
    department_form = school_settings_forms.DepartmentForm()
    
    context = {
        "currencies": all_currencies,
        "school_settings": school_settings,
        "school_sections": school_sections,
        "school_settings_form": school_settings_form,
        "sections_form": sections_form,
        "signatures": signatures,
        "signature_form": signature_form,
        "departments": departments,
        "department_form": department_form,
    }
    return render(request, 'school_settings/settings_page.html', context)

@login_required
def update_school_settings(request):
    school_settings = SchoolSetting.load()
    count = SchoolSetting.objects.count()
    
    if request.method == 'POST':
        school_settings_form = school_settings_forms.SchoolSettingForm(request.POST, request.FILES, instance=school_settings)
        
        if school_settings_form.is_valid():
            school_settings = school_settings_form.save()
            _ensure_default_sections_for_enabled_levels(school_settings)
            messages.success(request, SUCCESS_EDIT_MESSAGE)
        else:
            messages.error(request, FAILURE_MESSAGE)
    
    return HttpResponseRedirect(reverse('settings_page'))


@login_required
def switch_active_school_level(request):
    if request.method != "POST":
        return HttpResponseRedirect(reverse("index_page"))

    school_settings = SchoolSetting.load()
    selected_level = (request.POST.get("active_school_level") or "").strip()

    try:
        set_active_school_level(request, selected_level, school_setting=school_settings)
        messages.success(
            request,
            f"Active school level switched to {get_level_label(selected_level)}.",
        )
    except ValueError:
        messages.error(
            request,
            "Selected school level is not enabled. Update School Settings first.",
        )

    next_url = (request.POST.get("next") or "").strip()
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        return HttpResponseRedirect(next_url)

    return HttpResponseRedirect(reverse("index_page"))


@login_required
def add_currency(request):
    if request.POST:
        code = request.POST.get('code')
        desc = request.POST.get('desc')
        cost = request.POST.get('cost')

        school_settings_services.create_currency(code, desc, cost)
        messages.success(request, SUCCESS_ADD_MESSAGE)

        return HttpResponseRedirect(reverse('settings_page'))
    messages.error(request, 'You sent a get request')
    return HttpResponseRedirect(reverse('settings_page'))

@login_required
def edit_currency_page(request, currency_id):
    currency = school_settings_selectors.get_currency(currency_id)
    if request.POST:
        code = request.POST.get('code')
        desc = request.POST.get('desc')
        cost = request.POST.get('cost')
        school_settings_services.update_currency(currency, code, desc, cost)
        messages.success(request, SUCCESS_EDIT_MESSAGE)
        return HttpResponseRedirect(reverse('settings_page'))
    context = {
        "currency": currency
    }
    return render(request, 'settings/edit_currency.html', context)


@login_required
def delete_currency(request, currency_id):
    if request.method != "POST":
        messages.error(request, "Delete requests must be submitted via POST.")
        return HttpResponseRedirect(reverse('settings_page'))

    currency = school_settings_selectors.get_currency(currency_id)
    currency.delete()
    messages.success(request, DELETE_MESSAGE)
    return HttpResponseRedirect(reverse('settings_page'))

@login_required
def school_section_view(request):
    
    if request.method == "POST":
        section_form = school_settings_forms.SectionForm(request.POST)
        
        if section_form.is_valid():
            section_form.save()
            
            messages.success(request, SUCCESS_ADD_MESSAGE)
        else:
            messages.error(request, FAILURE_MESSAGE)
    
    return HttpResponseRedirect(reverse('settings_page'))

@login_required
def edit_section_view(request, id):
    section = get_model_record(Section,id)
    
    if request.method == "POST":
        section_form = school_settings_forms.SectionForm(request.POST, request.FILES, instance=section)
        
        if section_form.is_valid():
            section_form.save()
            
            messages.success(request, SUCCESS_EDIT_MESSAGE)
        else:
            messages.error(request, FAILURE_MESSAGE)
        return redirect(settings_page)
    
    section_form = SectionForm(instance=section)
    context ={
        "form": section_form,
        "section":section
    }
    return render(request,"school_settings/edit_section.html",context)


@login_required
def delete_section_view(request, id):
    if request.method != "POST":
        messages.error(request, "Delete requests must be submitted via POST.")
        return HttpResponseRedirect(reverse("settings_page"))

    section = school_settings_selectors.get_section(id)
    
    section.delete()
    
    messages.success(request, DELETE_MESSAGE)
    return HttpResponseRedirect(reverse("settings_page"))

@login_required
def add_signature_view(request):
    if request.method == "POST":
        signature_form = school_settings_forms.SignatureForm(request.POST, request.FILES)
        
        if signature_form.is_valid():
            signature_form.save()
            messages.success(request, SUCCESS_ADD_MESSAGE)
        else:
            messages.error(request, FAILURE_MESSAGE)
    return HttpResponseRedirect(reverse("settings_page"))


@login_required
def edit_signature_view(request, id):
    signature = school_settings_selectors.get_signature(id)
    
    if request.method == "POST":
        signature_form = school_settings_forms.SignatureForm(request.POST, request.FILES, instance=signature)
        
        if signature_form.is_valid():
            signature_form.save()
            messages.success(request, SUCCESS_EDIT_MESSAGE)
            
        else:
            messages.error(request, FAILURE_MESSAGE)
        return HttpResponseRedirect(reverse(settings_page))    
    else:
        signature_form = school_settings_forms.SignatureForm(instance=signature)

    context = {
        "form": signature_form,
        "signature": signature  
    }
    return render(request, "school_settings/edit_signature.html", context)

@login_required
def delete_signature_view(request, id):
    if request.method != "POST":
        messages.error(request, "Delete requests must be submitted via POST.")
        return HttpResponseRedirect(reverse("settings_page"))

    signature = school_settings_selectors.get_signature(id)
    
    signature.delete()
    
    messages.success(request, DELETE_MESSAGE)
    
    return HttpResponseRedirect(reverse("settings_page"))

@login_required
def add_department_view(request):
    
    if request.method == "POST":
        form = school_settings_forms.DepartmentForm(request.POST)
        
        if form.is_valid():
            form.save()
            messages.success(request, SUCCESS_ADD_MESSAGE)
        else:
            messages.error(request, FAILURE_MESSAGE)
            
    return HttpResponseRedirect(reverse("settings_page"))

@login_required
def edit_department_view(request,id):
    department = school_settings_selectors.get_department(id)
    
    if request.method == "POST":
        department_form = school_settings_forms.DepartmentForm(request.POST, request.FILES, instance=department)
        
        if department_form.is_valid():
            department_form.save()
            
            messages.success(request, SUCCESS_EDIT_MESSAGE)
        else:
            messages.error(request, FAILURE_MESSAGE)
        return HttpResponseRedirect(reverse("settings_page"))
    else:
        department_form = school_settings_forms.DepartmentForm(instance = department)
    context={
        "form":department_form,
        "department":department
    }
    return render(request,"school_settings/edit_department.html",context)

@login_required
def delete_department_view(request, id):
    if request.method != "POST":
        messages.error(request, "Delete requests must be submitted via POST.")
        return redirect("settings_page")

    department = school_settings_selectors.get_department(id)
    
    department.delete()
    
    messages.success(request, DELETE_MESSAGE)
    
    return redirect(add_department_view)
