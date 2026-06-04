from django.shortcuts import render, redirect, HttpResponseRedirect, HttpResponse,get_object_or_404
from django.contrib import messages
from django.urls import reverse
import csv
from django.db import IntegrityError
from app.selectors.model_selectors import *
from app.constants import *
from app.forms.staff import *
from app.models.staffs import Staff, StaffDocument
import app.selectors.staffs as staff_selectors
import app.forms.staff as staff_forms
from django.contrib.auth.decorators import login_required
from app.services.teacher_assignments import get_teacher_assignments

@login_required
def manage_staff_view(request):
    
    staffs = staff_selectors.get_all_staffs()
    staff_form = staff_forms.StaffForm()
    
    context = {
        "staffs":staffs,
        "staff_form": staff_form
    }
    return render(request, "staff/manage_staff.html", context)

@login_required
def add_staff(request):
    if request.method == "POST":
        staff_form = staff_forms.StaffForm(request.POST, request.FILES)
        
        if staff_form.is_valid():
            staff_form.save()
            
            messages.success(request, SUCCESS_ADD_MESSAGE)
        else:
            messages.error(request, FAILURE_MESSAGE)
    
    return HttpResponseRedirect(reverse(manage_staff_view))

@login_required
def staff_details_view(request, id):
    staff = get_object_or_404(Staff, id=id)
    teaching_assignments = get_teacher_assignments(staff)
    staff_documents = StaffDocument.objects.filter(staff=staff)

    if request.method == "POST":
        document_type = request.POST.get("document_type")
        file = request.FILES.get("file")
        
        if document_type and file:
            StaffDocument.objects.create(
                staff=staff,
                document_type=document_type,
                file=file
            )
            messages.success(request, "Document uploaded successfully!")
            return redirect('staff_details_page', id=staff.id)  
        else:
            messages.error(request, "Both fields are required.")

    context = {
        "staff": staff,
        "teaching_assignments": teaching_assignments,
        "staff_documents": staff_documents,
    }
    
    return render(request, "staff/staff_details.html", context)

@login_required
def delete_staff_document(request, id):
    document = get_object_or_404(StaffDocument, id=id)
    staff_id = document.staff.id  # Get the staff ID before deletion
    document.delete()
    messages.success(request, "Document deleted successfully.")
    return redirect('staff_details_page', id=staff_id)

@login_required
def edit_staff_details_view(request, id):
    staff_details = get_model_record(Staff, id)

    if request.method == "POST":
        staff_detail_form = StaffForm(request.POST, request.FILES, instance=staff_details) 

        if staff_detail_form.is_valid():
            staff_detail_form.save()
            messages.success(request, SUCCESS_ADD_MESSAGE)

            return redirect(staff_details_view, id=id)
        else:
            messages.error(request, FAILURE_MESSAGE)

    else:
        staff_detail_form = StaffForm(instance=staff_details)

    context = {
        "form": staff_detail_form,
        "staff_details": staff_details,
    }

    return render(request, "staff/edit_staff_details.html", context)



@login_required
def delete_staff_view(request, id):
    if request.method != "POST":
        messages.error(request, "Delete requests must be submitted via POST.")
        return HttpResponseRedirect(reverse(manage_staff_view))

    staff = staff_selectors.get_staff(id)
    
    staff.delete()
    
    messages.success(request, DELETE_MESSAGE)

    return HttpResponseRedirect(reverse(manage_staff_view))
