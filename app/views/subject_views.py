from django.shortcuts import render, redirect, HttpResponseRedirect, HttpResponse, get_object_or_404
from django.contrib import messages
from django.urls import reverse
import csv
from django.db import IntegrityError
from app.selectors.model_selectors import *
from app.constants import *
from app.forms.subjects import SubjectForm
from app.models.subjects import Subject
import app.forms.subjects as subject_forms

import app.selectors.subjects as subject_selectors
from django.contrib.auth.decorators import login_required
from app.services.level_scope import bind_form_level_querysets, get_level_subjects_queryset
from app.services.school_level import get_active_school_level


def _can_manage_subjects(request):
    active_role = request.session.get("active_role_name")
    if active_role:
        role_name = active_role
    else:
        staff_account = getattr(request.user, "staff_account", None)
        role_name = staff_account.role.name if staff_account and staff_account.role else None
    return role_name in {"Admin", "Director of Studies", "DOS"}


@login_required
def manage_subjects_view(request):
    active_level = get_active_school_level(request)
    can_manage_subjects = _can_manage_subjects(request)

    subject_form = subject_forms.SubjectForm()
    bind_form_level_querysets(subject_form, active_level=active_level)
    all_subjects = subject_selectors.get_all_subjects(active_level=active_level)
    
    context = {
        "subject_form": subject_form,
        "subjects": all_subjects,
        "is_dos": can_manage_subjects,
        "can_manage_subjects": can_manage_subjects,
    }
    return render(request, "subjects/manage_subjects.html", context)

@login_required
def add_subject_view(request):
    active_level = get_active_school_level(request)
    if not _can_manage_subjects(request):
        messages.error(request, "Only Admin or Director of Studies can add subjects.")
        return HttpResponseRedirect(reverse(manage_subjects_view))

    subject_form = subject_forms.SubjectForm(request.POST)
    bind_form_level_querysets(subject_form, active_level=active_level)
    
    if subject_form.is_valid():
        subject_form.save()
        
        messages.success(request, SUCCESS_ADD_MESSAGE)
    else:
        messages.error(request, FAILURE_MESSAGE)
    
    return HttpResponseRedirect(reverse(manage_subjects_view))

@login_required
def edit_subject_view(request,id):
    active_level = get_active_school_level(request)
    if not _can_manage_subjects(request):
        messages.error(request, "Only Admin or Director of Studies can edit subjects.")
        return redirect(manage_subjects_view)

    subject = get_object_or_404(get_level_subjects_queryset(active_level=active_level), pk=id)
    
    if request.method == 'POST':
        subject_form = SubjectForm(request.POST, instance=subject)
        bind_form_level_querysets(subject_form, active_level=active_level)
        if subject_form.is_valid():
            subject_form.save()
            
            messages.success(request, SUCCESS_ADD_MESSAGE)    
        else:
            messages.error(request, FAILURE_MESSAGE)
        return redirect(add_subject_view)
    else:
        subject_form = SubjectForm(instance=subject)
        bind_form_level_querysets(subject_form, active_level=active_level)
    
    context = {
        "form": subject_form,
        "subject": subject
    }
    
    return render(request, "subjects/edit_subject.html", context)

@login_required
def delete_subject_view(request, id):
    active_level = get_active_school_level(request)
    if not _can_manage_subjects(request):
        messages.error(request, "Only Admin or Director of Studies can delete subjects.")
        return HttpResponseRedirect(reverse(manage_subjects_view))

    subject = get_object_or_404(get_level_subjects_queryset(active_level=active_level), pk=id)
    
    subject.delete()
    
    messages.success(request, DELETE_MESSAGE)

    return HttpResponseRedirect(reverse(manage_subjects_view))
    
