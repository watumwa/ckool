from django.shortcuts import render, redirect, HttpResponseRedirect,get_object_or_404, redirect
from django.contrib import messages
from django.urls import reverse
from django.db.models import Avg, Count, Prefetch, Q, Sum
from django.core.paginator import Paginator
from django.http import HttpResponse
from urllib.parse import urlencode
from collections import defaultdict
import csv
import re
import logging
logger = logging.getLogger(__name__)
from app.constants import *
from app.models.students  import Student
from app.models.classes import Class, AcademicClass, Stream, AcademicClassStream,ClassSubjectAllocation
from app.forms.classes import (
    AcademicClassForm,
    AcademicClassStreamForm,
    ClassForm,
    ClassPromotionForm,
    StreamForm,
)
from app.models.students import ClassRegister
from app.forms.fees_payment import StudentBillItemForm,ClassBillForm
from app.selectors.model_selectors import *
import app.selectors.classes as class_selectors
import app.selectors.school_settings as school_settings_selectors
import app.selectors.fees_selectors as fees_selectors
from app.services.students import create_class_bill_item
from django.contrib.auth.decorators import login_required
from app.decorators.decorators import *
from app.models.accounts import *
from app.models.fees_payment import *
from app.models.school_settings import *
from app.models.classes import *
from itertools import groupby
from operator import attrgetter
from app.services.level_scope import (
    bind_form_level_querysets,
    get_level_academic_classes_queryset,
    get_level_classes_queryset,
    get_level_class_streams_queryset,
    get_level_subjects_queryset,
)
from app.services.school_level import get_active_school_level
from app.services.teacher_assignments import (
    copy_allocations_for_term_transition,
    delete_class_subject_allocation_record,
    get_allocation_queryset,
    save_class_subject_allocation,
    upsert_class_subject_allocation,
)
from app.services.class_promotions import promote_students_to_academic_class
from app.models.attendance import (
    AttendancePolicy,
    AttendanceRecord,
    AttendanceSession,
    AttendanceStatus,
)
from app.models.results import Result

ACADEMIC_CLASS_MANAGE_ROLES = {"Admin", "Head master", "Head Teacher", "Director of Studies", "DOS"}
ACADEMIC_CLASS_FINANCE_ROLES = {"Bursar", "Finance"}
PROMOTION_PASS_MARK = 50.0
PROMOTION_TABS = ("eligible", "conditional", "repeat", "graduating", "archived")
PROMOTION_MANAGE_ROLES = {"admin", "director of studies", "dos"}


def _get_effective_role_and_staff_account(request):
    staff_account = getattr(request.user, "staff_account", None)
    role_name = staff_account.role.name if staff_account and staff_account.role else None
    active_role = request.session.get("active_role_name")
    effective_role = active_role or role_name or ""
    return effective_role, staff_account


def _can_manage_class_records(effective_role):
    # Preserve legacy behavior where only Class Teacher is read-only on class records.
    return effective_role != "Class Teacher"


def _can_manage_stream_records(effective_role):
    return effective_role in ACADEMIC_CLASS_MANAGE_ROLES


def _can_manage_promotions(effective_role):
    normalized_role = (effective_role or "").strip().lower()
    return normalized_role in PROMOTION_MANAGE_ROLES


def _format_academic_class_label(academic_class):
    class_name = academic_class.Class.name or academic_class.Class.code
    return f"{class_name} - Term {academic_class.term.term} ({academic_class.academic_year.academic_year})"


def _to_int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _class_sort_key(class_obj):
    code = (class_obj.code or "").strip().upper()
    name = (class_obj.name or "").strip().upper()
    raw = code or name
    match = re.search(r"(\d+)", raw) or re.search(r"(\d+)", name)
    number = int(match.group(1)) if match else 999
    prefix = re.sub(r"\d+", "", raw) or raw
    return (prefix, number, raw, class_obj.id)


def _build_next_class_map(active_level):
    classes = list(
        get_level_classes_queryset(active_level=active_level)
        .select_related("section")
        .order_by("section_id", "name", "code")
    )
    grouped = defaultdict(list)
    for class_obj in classes:
        grouped[class_obj.section_id].append(class_obj)

    next_class_map = {}
    for section_classes in grouped.values():
        ordered = sorted(section_classes, key=_class_sort_key)
        for idx, class_obj in enumerate(ordered[:-1]):
            next_class_map[class_obj.id] = ordered[idx + 1]
    return next_class_map

@login_required
def class_view(request):
    active_level = get_active_school_level(request)
    scoped_classes = get_level_classes_queryset(active_level=active_level)
    effective_role, staff_account = _get_effective_role_and_staff_account(request)
    can_manage_classes = _can_manage_class_records(effective_role)

    if not can_manage_classes:
        class_form = ClassForm()
        bind_form_level_querysets(class_form, active_level=active_level)
        classes_qs = Class.objects.none()
        if staff_account and staff_account.staff:
            assigned_class_ids = get_level_class_streams_queryset(active_level=active_level).filter(
                class_teacher=staff_account.staff
            ).values_list("academic_class__Class_id", flat=True).distinct()
            classes_qs = scoped_classes.filter(id__in=assigned_class_ids).order_by("name")
        context = {
            "form": class_form,
            "classes": classes_qs,
            "can_manage_classes": can_manage_classes,
            "effective_role": effective_role,
        }
        return render(request, "classes/_class.html", context)

    if request.method == "POST":
        if not can_manage_classes:
            messages.error(request, "You have view-only access for class records.")
            return redirect("class_page")
        class_form = ClassForm(request.POST)
        bind_form_level_querysets(class_form, active_level=active_level)
        
        if class_form.is_valid():
            class_form.save()
            messages.success(request, SUCCESS_ADD_MESSAGE)
        else:
            messages.error(request, FAILURE_MESSAGE)
    
    class_form = ClassForm()
    bind_form_level_querysets(class_form, active_level=active_level)
    
    context = {
        "form": class_form,
        "classes": class_selectors.get_classes(active_level=active_level),
        "can_manage_classes": can_manage_classes,
        "effective_role": effective_role,
    }
    return render(request, "classes/_class.html", context)

@login_required
def edit_classe_view(request, id):
    effective_role, _ = _get_effective_role_and_staff_account(request)
    if not _can_manage_class_records(effective_role):
        messages.error(request, "You have view-only access for class records.")
        return redirect("class_page")

    active_level = get_active_school_level(request)
    classe = get_object_or_404(get_level_classes_queryset(active_level=active_level), id=id)
    
    if request.method == "POST":
        class_form = ClassForm(request.POST, instance= classe)
        bind_form_level_querysets(class_form, active_level=active_level)
        
        if class_form.is_valid():
            class_form.save()
            messages.success(request, SUCCESS_ADD_MESSAGE)
            return redirect(class_view)  
        else:
            messages.error(request, FAILURE_MESSAGE)
    
    else:
        class_form = ClassForm(instance=classe)
        bind_form_level_querysets(class_form, active_level=active_level)
    
    context = {
        "form":class_form,
        "classe":classe
    }
    
    return render(request, "classes/edit_class.html", context)


@login_required
def delete_class_view(request, id):
    effective_role, _ = _get_effective_role_and_staff_account(request)
    if not _can_manage_class_records(effective_role):
        messages.error(request, "You have view-only access for class records.")
        return redirect("class_page")

    active_level = get_active_school_level(request)
    classe = get_object_or_404(get_level_classes_queryset(active_level=active_level), pk=id)
    if request.method != "POST":
        messages.error(request, "Delete requests must be submitted via POST.")
        return redirect("class_page")
    
    classe.delete()
    messages.success(request, DELETE_MESSAGE)
    
    return redirect(class_view)

@login_required
def stream_view(request):
    effective_role, _ = _get_effective_role_and_staff_account(request)
    is_dos = effective_role in {"Director of Studies", "DOS"}
    is_admin = effective_role in {"Admin", "Head master", "Head Teacher"}
    can_manage_streams = _can_manage_stream_records(effective_role)

    if request.method == "POST" and not can_manage_streams:
        messages.error(request, "Only Admin or Academic Head can manage streams.")
        return redirect(stream_view)

    if request.method == "POST":
        stream_form = StreamForm(request.POST)
        
        if stream_form.is_valid():
            stream_form.save()
            messages.success(request, SUCCESS_ADD_MESSAGE)
        else:
            messages.error(request, FAILURE_MESSAGE)
    
    stream_form = StreamForm()
    streams = Stream.objects.all()
    
    context = {
        "form": stream_form,
        "streams": streams,
        "is_dos": is_dos,
        "is_admin": is_admin,
        "can_manage_streams": can_manage_streams,
        "effective_role": effective_role,
    }
    return render(request, "classes/stream.html", context)


@login_required
def edit_stream(request,id):
    effective_role, _ = _get_effective_role_and_staff_account(request)
    if not _can_manage_stream_records(effective_role):
        messages.error(request, "Only Admin or Academic Head can manage streams.")
        return redirect("stream_page")

    stream = get_model_record(Stream,id)
    if request.method =="POST":
        stream_form =StreamForm(request.POST,instance=stream)
        
        if stream_form.is_valid():
            stream_form.save()

            messages.success(request, SUCCESS_ADD_MESSAGE)
            return redirect(stream_view)
        else:
            messages.error(request, FAILURE_MESSAGE)
    
            
    stream_form =StreamForm(instance=stream)
    
    context ={
        "form":stream_form,
        "stream":stream
    }
    
    return render(request, "classes/edit_stream.html",context)


@login_required
def delete_stream_view(request, id):
    effective_role, _ = _get_effective_role_and_staff_account(request)
    if not _can_manage_stream_records(effective_role):
        messages.error(request, "Only Admin or Academic Head can manage streams.")
        return redirect("stream_page")

    try:
        stream = Stream.objects.get(pk=id)
        if request.method != "POST":
            messages.error(request, "Delete requests must be submitted via POST.")
            return redirect("stream_page")
        
        stream.delete()
        messages.success(request, DELETE_MESSAGE)
        
        return redirect(stream_view)
    except:
        logger.critical("Failed Delete record")


@login_required
def academic_class_view(request):
    active_level = get_active_school_level(request)
    scoped_academic_classes = get_level_academic_classes_queryset(active_level=active_level)

    effective_role, staff_account = _get_effective_role_and_staff_account(request)
    can_manage_classes = effective_role in ACADEMIC_CLASS_MANAGE_ROLES
    can_manage_promotions = _can_manage_promotions(effective_role)
    can_view_fees = can_manage_classes or effective_role in ACADEMIC_CLASS_FINANCE_ROLES
    is_class_teacher = effective_role == "Class Teacher"
    is_teacher = effective_role == "Teacher"

    if request.method == "POST":
        if not can_manage_classes:
            messages.error(request, "You have view-only access. Only Admin or Academic Head can create academic classes.")
            return redirect("academic_class_page")

        academic_class_form = AcademicClassForm(request.POST)
        bind_form_level_querysets(academic_class_form, active_level=active_level)
        if academic_class_form.is_valid():
            academic_class_form.save()
            messages.success(request, SUCCESS_ADD_MESSAGE)
        else:
            messages.error(request, FAILURE_MESSAGE)

    academic_class_form = AcademicClassForm()
    bind_form_level_querysets(academic_class_form, active_level=active_level)

    # Get base queryset based on user role
    if is_class_teacher:
        if staff_account and staff_account.staff:
            base_queryset = scoped_academic_classes.filter(
                id__in=AcademicClassStream.objects.filter(
                    class_teacher=staff_account.staff
                ).values_list("academic_class_id", flat=True)
            ).distinct()
        else:
            base_queryset = scoped_academic_classes.none()
    elif is_teacher:
        if staff_account and staff_account.staff:
            base_queryset = scoped_academic_classes.filter(
                id__in=ClassSubjectAllocation.objects.filter(
                    subject_teacher=staff_account.staff
                ).values_list("academic_class_stream__academic_class_id", flat=True)
            ).distinct()
        else:
            base_queryset = scoped_academic_classes.none()
    elif can_manage_classes or effective_role in ACADEMIC_CLASS_FINANCE_ROLES:
        base_queryset = scoped_academic_classes
    else:
        base_queryset = scoped_academic_classes.none()

    search_query = (request.GET.get("search") or "").strip()
    academic_year_filter = request.GET.get('academic_year')
    term_filter = request.GET.get('term')
    class_filter = request.GET.get('class')
    section_filter = request.GET.get('section')

    academic_classes = base_queryset

    if search_query:
        academic_classes = academic_classes.filter(
            Q(Class__name__icontains=search_query)
            | Q(Class__code__icontains=search_query)
            | Q(section__section_name__icontains=search_query)
            | Q(academic_year__academic_year__icontains=search_query)
            | Q(term__term__icontains=search_query)
        )

    if academic_year_filter and academic_year_filter != '':
        academic_classes = academic_classes.filter(academic_year_id=academic_year_filter)

    if term_filter and term_filter != '':
        academic_classes = academic_classes.filter(term_id=term_filter)

    if class_filter and class_filter != '':
        academic_classes = academic_classes.filter(Class_id=class_filter)

    if section_filter and section_filter != '':
        academic_classes = academic_classes.filter(section_id=section_filter)

    academic_classes = (
        academic_classes
        .select_related('Class', 'academic_year', 'term', 'section')
        .prefetch_related(
            Prefetch(
                "class_streams",
                queryset=AcademicClassStream.objects.select_related("stream", "class_teacher").order_by("stream__stream"),
            )
        )
        .annotate(streams_count=Count("class_streams", distinct=True))
        .order_by("Class__name", "academic_year__academic_year", "term__term")
    )

    total_classes = academic_classes.count()
    distinct_terms = academic_classes.values_list('term', flat=True).distinct().count() if academic_classes.exists() else 0
    distinct_sections = academic_classes.values_list('section', flat=True).distinct().count() if academic_classes.exists() else 0
    academic_years_count = school_settings_selectors.get_academic_years().count()

    section_ids = base_queryset.values_list('section_id', flat=True).distinct()
    sections_list = Section.objects.filter(id__in=section_ids).order_by("section_name")

    class_ids = list(academic_classes.values_list("id", flat=True))
    total_streams = 0
    total_students = 0
    average_fees = 0
    if class_ids:
        total_streams = AcademicClassStream.objects.filter(academic_class_id__in=class_ids).count()
        total_students = (
            ClassRegister.objects.filter(
                academic_class_stream__academic_class_id__in=class_ids,
                student__is_active=True,
            )
            .values("student_id")
            .distinct()
            .count()
        )
        average_fees = int(academic_classes.aggregate(avg=Avg("fees_amount"))["avg"] or 0)

    all_academic_years = school_settings_selectors.get_academic_years()
    all_classes = class_selectors.get_classes(active_level=active_level)
    all_terms = []  
    selected_year_label = "All Academic Years"

    # Get terms for the selected academic year or all terms
    if academic_year_filter and academic_year_filter != '':
        try:
            selected_year = all_academic_years.get(id=academic_year_filter)
            all_terms = selected_year.term_set.all()
            selected_year_label = selected_year.academic_year
        except:
            all_terms = []
    else:
        # Get all terms from all years
        all_terms = Term.objects.all()

    context = {
        "form": academic_class_form,
        "academic_years": all_academic_years,
        "academic_classes": academic_classes,
        "classes": all_classes,
        "all_terms": all_terms,
        # Statistics
        "total_classes": total_classes,
        "distinct_terms": distinct_terms,
        "distinct_sections": distinct_sections,
        "academic_years_count": academic_years_count,
        "sections_list": sections_list,
        # Current filter values
        "current_academic_year": academic_year_filter,
        "current_term": term_filter,
        "current_class": class_filter,
        "current_section": section_filter,
        "search_query": search_query,
        "show_advanced_filters": bool(class_filter or section_filter),
        # UI/permissions
        "can_manage_classes": can_manage_classes,
        "can_manage_promotions": can_manage_promotions,
        "can_view_fees": can_view_fees,
        "is_read_only": not can_manage_classes,
        "effective_role": effective_role,
        # Right panel summary
        "selected_year_label": selected_year_label,
        "total_streams": total_streams,
        "total_students": total_students,
        "average_fees": average_fees,
    }

    return render(request, "classes/academic_class.html", context)


@login_required
def bulk_academic_class_action_view(request):
    if request.method != "POST":
        return redirect("academic_class_page")

    active_level = get_active_school_level(request)
    effective_role, _ = _get_effective_role_and_staff_account(request)
    if effective_role not in ACADEMIC_CLASS_MANAGE_ROLES:
        messages.error(request, "You have view-only access. Only Admin or Academic Head can run bulk actions.")
        return redirect("academic_class_page")

    action = (request.POST.get("action") or "").strip()
    raw_ids = (request.POST.get("selected_ids") or "").strip()
    next_url = (request.POST.get("next_url") or "").strip()

    selected_ids = []
    if raw_ids:
        for value in raw_ids.split(","):
            value = value.strip()
            if not value:
                continue
            if value.isdigit():
                selected_ids.append(int(value))

    if not selected_ids:
        messages.warning(request, "No classes selected for bulk action.")
        return redirect(next_url or "academic_class_page")

    scoped_queryset = get_level_academic_classes_queryset(active_level=active_level).filter(id__in=selected_ids)
    selected_count = scoped_queryset.count()
    if selected_count == 0:
        messages.warning(request, "Selected classes were not found in your current school scope.")
        return redirect(next_url or "academic_class_page")

    if action == "bulk_delete":
        deleted_count = selected_count
        scoped_queryset.delete()
        messages.success(request, f"Deleted {deleted_count} academic class record(s).")
    else:
        messages.error(request, "Unsupported bulk action requested.")

    return redirect(next_url or "academic_class_page")




@login_required
def edit_academic_class_view(request, class_id):
    active_level = get_active_school_level(request)
    academic_class = get_object_or_404(get_level_academic_classes_queryset(active_level=active_level), id=class_id)

    if request.method == "POST":
        academic_class_form = AcademicClassForm(request.POST, instance=academic_class)
        bind_form_level_querysets(academic_class_form, active_level=active_level)
        
        if academic_class_form.is_valid():
            academic_class_form.save()
            messages.success(request,SUCCESS_ADD_MESSAGE)
            return redirect("academic_class_view")  
        else:
            messages.error(request,FAILURE_MESSAGE)
    else:
        academic_class_form = AcademicClassForm(instance=academic_class)
        bind_form_level_querysets(academic_class_form, active_level=active_level)

    context = {
        "form": academic_class_form,
        "academic_class": academic_class,
    }
    return render(request, "classes/edit_academic_class.html", context)


@login_required
def delete_academic_class_view(request, id):
    effective_role, _ = _get_effective_role_and_staff_account(request)
    if effective_role not in ACADEMIC_CLASS_MANAGE_ROLES:
        messages.error(request, "You have view-only access. Only Admin or Academic Head can delete academic classes.")
        return redirect("academic_class_page")

    active_level = get_active_school_level(request)
    academic_class = get_object_or_404(get_level_academic_classes_queryset(active_level=active_level), id=id)
    if request.method != "POST":
        messages.error(request, "Delete requests must be submitted via POST.")
        return redirect("academic_class_page")
    
    academic_class.delete()
    messages.success(request, DELETE_MESSAGE)
    
    return redirect(academic_class_view)

@login_required
def academic_class_details_view(request, id):
    active_level = get_active_school_level(request)
    academic_class = get_object_or_404(get_level_academic_classes_queryset(active_level=active_level), pk=id)
    effective_role, _ = _get_effective_role_and_staff_account(request)
    can_manage_class_detail = effective_role in ACADEMIC_CLASS_MANAGE_ROLES
    can_manage_promotions = _can_manage_promotions(effective_role)

    academic_class_streams = (
        class_selectors.get_academic_class_streams(academic_class)
        .select_related("stream", "class_teacher")
        .prefetch_related("class_teacher__roles")
        .order_by("stream__stream")
    )
    stream_ids = list(academic_class_streams.values_list("id", flat=True))
    class_register_all = (
        ClassRegister.objects.filter(
            academic_class_stream_id__in=stream_ids,
            student__is_active=True,
        )
        .select_related("student", "academic_class_stream__stream")
        .order_by("student__student_name")
    )

    search_query = (request.GET.get("q") or "").strip()
    selected_stream_filter = (request.GET.get("stream") or "").strip()
    class_register = class_register_all
    if selected_stream_filter.isdigit():
        selected_stream_id = int(selected_stream_filter)
        if selected_stream_id in stream_ids:
            class_register = class_register.filter(academic_class_stream_id=selected_stream_id)
        else:
            selected_stream_filter = ""
    else:
        selected_stream_filter = ""

    if search_query:
        class_register = class_register.filter(
            Q(student__student_name__icontains=search_query)
            | Q(student__reg_no__icontains=search_query)
            | Q(student__gender__icontains=search_query)
        )

    class_stream_form = AcademicClassStreamForm(initial={"academic_class": academic_class})
    promotion_form = ClassPromotionForm(
        source_academic_class=academic_class,
        target_queryset=get_level_academic_classes_queryset(active_level=active_level),
    )
    bill_item_form = StudentBillItemForm()

    # Calculate student statistics
    total_students = class_register_all.values("student_id").distinct().count()
    male_students = (
        class_register_all.filter(student__gender__iexact="M")
        .values("student_id")
        .distinct()
        .count()
    )
    female_students = (
        class_register_all.filter(student__gender__iexact="F")
        .values("student_id")
        .distinct()
        .count()
    )
    stream_count = academic_class_streams.count()

    # Calculate percentages
    male_percentage = (male_students / total_students * 100) if total_students > 0 else 0
    female_percentage = (female_students / total_students * 100) if total_students > 0 else 0

    # Stream cards + duplicate teacher warning
    stream_cards = []
    teacher_stream_counts = {}
    for stream in academic_class_streams:
        teacher = stream.class_teacher
        role_label = "-"
        if teacher:
            role_names = [role.name for role in teacher.roles.all()]
            role_label = ", ".join(role_names[:2]) if role_names else (teacher.department or "-")
            teacher_stream_counts[teacher.id] = teacher_stream_counts.get(teacher.id, 0) + 1
        stream_cards.append(
            {
                "id": stream.id,
                "stream_name": stream.stream.stream if stream.stream else "-",
                "teacher_name": str(teacher) if teacher else "Unassigned",
                "teacher_role": role_label,
                "has_teacher": bool(teacher),
            }
        )

    has_duplicate_teacher_assignment = any(count > 1 for count in teacher_stream_counts.values())

    # Attendance quick summary (term-scoped for this class)
    present_like_statuses = [AttendanceStatus.PRESENT, AttendanceStatus.LATE]
    attendance_sessions = AttendanceSession.objects.filter(
        class_stream_id__in=stream_ids,
        academic_year=academic_class.academic_year,
        term=academic_class.term,
    )
    lessons_conducted = attendance_sessions.count()
    attendance_records = AttendanceRecord.objects.filter(session__in=attendance_sessions)
    total_attendance_records = attendance_records.count()
    present_like_count = attendance_records.filter(status__in=present_like_statuses).count()
    attendance_average_rate = (
        round((present_like_count / total_attendance_records) * 100, 1)
        if total_attendance_records
        else 0
    )

    policy = AttendancePolicy.objects.first()
    minimum_attendance_percent = policy.minimum_attendance_percent if policy else 75
    chronic_absentees_count = 0
    attendance_by_student = {}
    student_rollups = attendance_records.values("student_id").annotate(
        total=Count("id"),
        present_like=Count("id", filter=Q(status__in=present_like_statuses)),
    )
    for row in student_rollups:
        total = row["total"] or 0
        present_like = row["present_like"] or 0
        rate = round((present_like / total) * 100, 1) if total else 0
        if total >= 5 and rate < minimum_attendance_percent:
            chronic_absentees_count += 1
        if total == 0:
            tone = "muted"
            status_label = "No Data"
        elif rate >= minimum_attendance_percent:
            tone = "success"
            status_label = "On Track"
        else:
            tone = "danger"
            status_label = "At Risk"
        attendance_by_student[row["student_id"]] = {
            "rate": rate,
            "status_label": status_label,
            "tone": tone,
            "total": total,
        }

    register_rows = []
    for idx, register in enumerate(class_register, start=1):
        rollup = attendance_by_student.get(register.student_id, None)
        if rollup:
            attendance_rate = rollup["rate"]
            attendance_status_label = rollup["status_label"]
            attendance_status_tone = rollup["tone"]
        else:
            attendance_rate = 0
            attendance_status_label = "No Data"
            attendance_status_tone = "muted"
        register_rows.append(
            {
                "index": idx,
                "register": register,
                "attendance_rate": attendance_rate,
                "attendance_status_label": attendance_status_label,
                "attendance_status_tone": attendance_status_tone,
            }
        )

    recent_promotion_history = (
        StudentPromotionHistory.objects.filter(
            Q(source_academic_class=academic_class) | Q(target_academic_class=academic_class)
        )
        .select_related(
            "promoted_by",
            "source_stream__stream",
            "source_academic_class__Class",
            "source_academic_class__term",
            "source_academic_class__academic_year",
            "target_academic_class__Class",
            "target_academic_class__term",
            "target_academic_class__academic_year",
        )
        .order_by("-promoted_at")[:8]
    )

    context = {
        "academic_class": academic_class,
        "class_streams": academic_class_streams,
        "class_stream_form": class_stream_form,
        "promotion_form": promotion_form,
        "class_register": class_register,
        "register_rows": register_rows,
        "bill_item_form": bill_item_form,
        "can_manage_class_detail": can_manage_class_detail,
        "can_manage_promotions": can_manage_promotions,
        # Student statistics
        "total_students": total_students,
        "male_students": male_students,
        "female_students": female_students,
        "male_percentage": round(male_percentage, 1),
        "female_percentage": round(female_percentage, 1),
        "stream_count": stream_count,
        # Streams panel
        "stream_cards": stream_cards,
        "has_duplicate_teacher_assignment": has_duplicate_teacher_assignment,
        # Register filters
        "search_query": search_query,
        "selected_stream_filter": selected_stream_filter,
        # Attendance summary
        "attendance_average_rate": attendance_average_rate,
        "lessons_conducted": lessons_conducted,
        "chronic_absentees_count": chronic_absentees_count,
        "minimum_attendance_percent": minimum_attendance_percent,
        "recent_promotion_history": recent_promotion_history,
    }

    return render(request, "classes/academic_class_details.html", context)


def _build_promotion_filter_query(
    *,
    source_year_id,
    source_term_id,
    target_year_id,
    target_term_id,
    section_id,
    source_academic_class_id,
    target_academic_class_id,
    search_query,
    tab,
    sort_by,
    sort_dir,
):
    params = {}
    if source_year_id:
        params["source_year_id"] = source_year_id
    if source_term_id:
        params["source_term_id"] = source_term_id
    if target_year_id:
        params["target_year_id"] = target_year_id
    if target_term_id:
        params["target_term_id"] = target_term_id
    if section_id:
        params["section_id"] = section_id
    if source_academic_class_id:
        params["source_academic_class_id"] = source_academic_class_id
    if target_academic_class_id:
        params["target_academic_class_id"] = target_academic_class_id
    if search_query:
        params["q"] = search_query
    if tab:
        params["tab"] = tab
    if sort_by:
        params["sort"] = sort_by
    if sort_dir:
        params["order"] = sort_dir
    return urlencode(params)


def _parse_selected_student_ids(request):
    selected_ids = set()
    for raw_value in request.POST.getlist("selected_student_ids"):
        parsed = _to_int(raw_value)
        if parsed:
            selected_ids.add(parsed)
    for raw_value in (request.POST.get("selected_student_ids_csv") or "").split(","):
        parsed = _to_int(raw_value.strip())
        if parsed:
            selected_ids.add(parsed)
    return sorted(selected_ids)


def _build_student_promotion_rows(
    *,
    source_academic_class,
    active_level,
    search_query="",
    active_tab="eligible",
    next_class_obj=None,
):
    registers_qs = (
        ClassRegister.objects.filter(
            academic_class_stream__academic_class=source_academic_class,
            student__is_active=True,
        )
        .select_related("student", "student__current_class", "student__stream", "academic_class_stream__stream")
        .order_by("student__student_name", "student__reg_no", "id")
    )
    if search_query:
        registers_qs = registers_qs.filter(
            Q(student__student_name__icontains=search_query)
            | Q(student__reg_no__icontains=search_query)
        )

    register_by_student = {}
    for row in registers_qs:
        register_by_student.setdefault(row.student_id, row)

    register_rows = list(register_by_student.values())
    student_ids = [row.student_id for row in register_rows]

    score_map = {}
    score_count_map = {}
    if student_ids:
        score_rows = (
            Result.objects.filter(
                assessment__academic_class=source_academic_class,
                student_id__in=student_ids,
            )
            .values("student_id")
            .annotate(avg_score=Avg("score"), result_count=Count("id"))
        )
        for row in score_rows:
            score_map[row["student_id"]] = float(row["avg_score"] or 0)
            score_count_map[row["student_id"]] = row["result_count"] or 0

    billed_map = {}
    paid_map = {}
    credits_map = {}
    if student_ids:
        billed_rows = (
            StudentBillItem.objects.filter(
                bill__student_id__in=student_ids,
                bill__academic_class=source_academic_class,
            )
            .values("bill__student_id")
            .annotate(total=Sum("amount"))
        )
        billed_map = {row["bill__student_id"]: row["total"] or 0 for row in billed_rows}

        paid_rows = (
            Payment.objects.filter(
                bill__student_id__in=student_ids,
                bill__academic_class=source_academic_class,
            )
            .values("bill__student_id")
            .annotate(total=Sum("amount"))
        )
        paid_map = {row["bill__student_id"]: row["total"] or 0 for row in paid_rows}

        credit_rows = (
            StudentCredit.objects.filter(
                student_id__in=student_ids,
                applied_to_bill__academic_class=source_academic_class,
                amount__lt=0,
            )
            .values("student_id")
            .annotate(total=Sum("amount"))
        )
        credits_map = {row["student_id"]: row["total"] or 0 for row in credit_rows}

    attendance_policy = AttendancePolicy.objects.first()
    attendance_threshold = attendance_policy.minimum_attendance_percent if attendance_policy else 75
    attendance_map = {}
    attendance_count_map = {}
    if student_ids:
        attendance_rows = (
            AttendanceRecord.objects.filter(
                session__class_stream__academic_class=source_academic_class,
                student_id__in=student_ids,
            )
            .values("student_id")
            .annotate(
                total=Count("id"),
                present_like=Count(
                    "id",
                    filter=Q(status__in=[AttendanceStatus.PRESENT, AttendanceStatus.LATE]),
                ),
            )
        )
        for row in attendance_rows:
            total = row["total"] or 0
            present_like = row["present_like"] or 0
            attendance_count_map[row["student_id"]] = total
            attendance_map[row["student_id"]] = round((present_like / total) * 100, 1) if total else 0

    status_label_map = {
        "eligible": "Eligible",
        "conditional": "Conditional",
        "repeat": "Repeat",
        "incomplete": "Incomplete",
        "graduating": "Graduating",
        "archived": "Archived",
    }
    status_tone_map = {
        "eligible": "success",
        "conditional": "warning",
        "repeat": "danger",
        "incomplete": "muted",
        "graduating": "info",
        "archived": "muted",
    }

    all_rows = []
    summary = {
        "total": 0,
        "academic_pass": 0,
        "fees_cleared": 0,
        "discipline_cleared": 0,
        "attendance_pass": 0,
        "promotable": 0,
    }
    tab_counts = {tab_name: 0 for tab_name in PROMOTION_TABS}

    for register in register_rows:
        student = register.student
        avg_score = score_map.get(student.id)
        result_count = score_count_map.get(student.id, 0)
        attendance_percent = attendance_map.get(student.id)
        attendance_count = attendance_count_map.get(student.id, 0)
        fee_balance = (
            (billed_map.get(student.id, 0) or 0)
            - (paid_map.get(student.id, 0) or 0)
            + (credits_map.get(student.id, 0) or 0)
        )

        academic_ok = bool(result_count and avg_score is not None and avg_score >= PROMOTION_PASS_MARK)
        fees_ok = fee_balance <= 0
        attendance_ok = bool(attendance_count and attendance_percent is not None and attendance_percent >= attendance_threshold)
        discipline_ok = True  # Discipline workflow is not modeled yet.

        if not student.is_active:
            status_key = "archived"
        elif not next_class_obj:
            status_key = "graduating"
        elif result_count == 0 and attendance_count == 0:
            status_key = "incomplete"
        else:
            failed_checks = [not academic_ok, not fees_ok, not attendance_ok, not discipline_ok]
            failed_count = sum(1 for failed in failed_checks if failed)
            if failed_count == 0:
                status_key = "eligible"
            elif failed_count == 1:
                status_key = "conditional"
            else:
                status_key = "repeat"

        can_promote = status_key == "eligible"
        if status_key == "eligible":
            tab_counts["eligible"] += 1
        elif status_key in {"conditional", "incomplete"}:
            tab_counts["conditional"] += 1
        elif status_key == "repeat":
            tab_counts["repeat"] += 1
        elif status_key == "graduating":
            tab_counts["graduating"] += 1
        elif status_key == "archived":
            tab_counts["archived"] += 1

        summary["total"] += 1
        summary["academic_pass"] += 1 if academic_ok else 0
        summary["fees_cleared"] += 1 if fees_ok else 0
        summary["discipline_cleared"] += 1 if discipline_ok else 0
        summary["attendance_pass"] += 1 if attendance_ok else 0
        summary["promotable"] += 1 if can_promote else 0

        all_rows.append(
            {
                "student_id": student.id,
                "register_id": register.id,
                "photo_url": getattr(getattr(student, "photo", None), "url", ""),
                "student_name": student.student_name,
                "admission_no": student.reg_no,
                "gender": student.gender,
                "stream_name": register.academic_class_stream.stream.stream if register.academic_class_stream_id else "-",
                "current_class_label": student.current_class.name if student.current_class_id else "-",
                "avg_score": round(avg_score, 1) if avg_score is not None else None,
                "status_key": status_key,
                "status_label": status_label_map.get(status_key, status_key.title()),
                "status_tone": status_tone_map.get(status_key, "muted"),
                "is_active": bool(student.is_active),
                "can_promote": can_promote,
                "academic_ok": academic_ok,
                "fees_ok": fees_ok,
                "discipline_ok": discipline_ok,
                "attendance_ok": attendance_ok,
                "attendance_percent": attendance_percent,
                "attendance_count": attendance_count,
                "result_count": result_count,
                "fee_balance": fee_balance,
            }
        )

    summary["blocked"] = max(summary["total"] - summary["promotable"], 0)

    active_tab = active_tab if active_tab in PROMOTION_TABS else "eligible"
    tab_filter_map = {
        "eligible": {"eligible"},
        "conditional": {"conditional", "incomplete"},
        "repeat": {"repeat"},
        "graduating": {"graduating"},
        "archived": {"archived"},
    }
    allowed_statuses = tab_filter_map.get(active_tab, {"eligible"})
    filtered_rows = [row for row in all_rows if row["status_key"] in allowed_statuses]

    return {
        "all_rows": all_rows,
        "rows": filtered_rows,
        "tab_counts": tab_counts,
        "summary": summary,
        "attendance_threshold": attendance_threshold,
    }


@login_required
def student_promotion_workflow(request):
    active_level = get_active_school_level(request)
    effective_role, _ = _get_effective_role_and_staff_account(request)
    if not _can_manage_promotions(effective_role):
        messages.error(request, "Only Admin or Director of Studies can access student promotion workflow.")
        return redirect("academic_class_page")

    scoped_academic_classes = get_level_academic_classes_queryset(active_level=active_level).select_related(
        "Class",
        "academic_year",
        "term",
        "section",
    )
    section_ids = scoped_academic_classes.values_list("section_id", flat=True).distinct()
    sections = Section.objects.filter(id__in=section_ids).order_by("section_name")
    academic_year_ids = scoped_academic_classes.values_list("academic_year_id", flat=True).distinct()
    academic_years = AcademicYear.objects.filter(id__in=academic_year_ids).order_by("academic_year")
    current_term = Term.objects.filter(is_current=True).select_related("academic_year").first()

    input_data = request.POST if request.method == "POST" else request.GET
    search_query = (input_data.get("q") or "").strip()
    active_tab = (input_data.get("tab") or "eligible").strip().lower()
    if active_tab not in PROMOTION_TABS:
        active_tab = "eligible"
    sort_by = (input_data.get("sort") or "name").strip().lower()
    if sort_by not in {"name", "adm_no", "avg_score", "status"}:
        sort_by = "name"
    sort_dir = (input_data.get("order") or "asc").strip().lower()
    if sort_dir not in {"asc", "desc"}:
        sort_dir = "asc"

    requested_source_class_id = _to_int(input_data.get("source_academic_class_id"))
    requested_source_class = None
    if requested_source_class_id:
        requested_source_class = scoped_academic_classes.filter(id=requested_source_class_id).first()

    default_source_year_id = None
    if requested_source_class:
        default_source_year_id = requested_source_class.academic_year_id
    elif current_term and current_term.academic_year_id in set(academic_year_ids):
        default_source_year_id = current_term.academic_year_id
    elif academic_years:
        default_source_year_id = academic_years.first().id
    source_year_id = _to_int(input_data.get("source_year_id"), default_source_year_id)
    source_terms = Term.objects.filter(academic_year_id=source_year_id).order_by("term")
    default_source_term_id = None
    if requested_source_class and requested_source_class.academic_year_id == source_year_id:
        default_source_term_id = requested_source_class.term_id
    elif current_term and current_term.academic_year_id == source_year_id:
        default_source_term_id = current_term.id
    elif source_terms:
        default_source_term_id = source_terms.first().id
    source_term_id = _to_int(input_data.get("source_term_id"), default_source_term_id)

    academic_year_list = list(academic_years)
    default_target_year_id = source_year_id
    for idx, year in enumerate(academic_year_list):
        if year.id == source_year_id and idx + 1 < len(academic_year_list):
            default_target_year_id = academic_year_list[idx + 1].id
            break
    target_year_id = _to_int(input_data.get("target_year_id"), default_target_year_id)
    target_terms = Term.objects.filter(academic_year_id=target_year_id).order_by("term")
    default_target_term_id = target_terms.first().id if target_terms else None
    target_term_id = _to_int(input_data.get("target_term_id"), default_target_term_id)

    section_id = _to_int(input_data.get("section_id"))
    if not section_id and requested_source_class:
        section_id = requested_source_class.section_id
    source_class_options = scoped_academic_classes.filter(
        academic_year_id=source_year_id,
        term_id=source_term_id,
    )
    if section_id:
        source_class_options = source_class_options.filter(section_id=section_id)
    source_class_options = source_class_options.order_by("Class__name", "Class__code")

    source_academic_class_id = requested_source_class_id
    if not source_academic_class_id and source_class_options.exists():
        source_academic_class_id = source_class_options.first().id
    selected_source_class = source_class_options.filter(id=source_academic_class_id).first()
    if selected_source_class and not section_id:
        section_id = selected_source_class.section_id

    target_class_options = scoped_academic_classes.filter(
        academic_year_id=target_year_id,
        term_id=target_term_id,
    )
    if section_id:
        target_class_options = target_class_options.filter(section_id=section_id)
    target_class_options = target_class_options.order_by("Class__name", "Class__code")

    next_class_map = _build_next_class_map(active_level)
    next_class_obj = None
    if selected_source_class:
        next_class_obj = next_class_map.get(selected_source_class.Class_id)

    target_academic_class_id = _to_int(input_data.get("target_academic_class_id"))
    if not target_academic_class_id and selected_source_class and next_class_obj:
        auto_target = target_class_options.filter(
            Class_id=next_class_obj.id,
            section_id=selected_source_class.section_id,
        ).first()
        if auto_target:
            target_academic_class_id = auto_target.id
    selected_target_class = target_class_options.filter(id=target_academic_class_id).first()

    promotion_rows_data = {
        "all_rows": [],
        "rows": [],
        "tab_counts": {tab_name: 0 for tab_name in PROMOTION_TABS},
        "summary": {
            "total": 0,
            "academic_pass": 0,
            "fees_cleared": 0,
            "discipline_cleared": 0,
            "attendance_pass": 0,
            "promotable": 0,
            "blocked": 0,
        },
        "attendance_threshold": 75,
    }
    if selected_source_class:
        promotion_rows_data = _build_student_promotion_rows(
            source_academic_class=selected_source_class,
            active_level=active_level,
            search_query=search_query,
            active_tab=active_tab,
            next_class_obj=next_class_obj,
        )

    filtered_rows = list(promotion_rows_data["rows"])
    reverse_sort = sort_dir == "desc"
    if sort_by == "avg_score":
        filtered_rows.sort(
            key=lambda row: (row["avg_score"] is None, row["avg_score"] or 0),
            reverse=reverse_sort,
        )
    elif sort_by == "adm_no":
        filtered_rows.sort(key=lambda row: (row["admission_no"] or "").lower(), reverse=reverse_sort)
    elif sort_by == "status":
        filtered_rows.sort(key=lambda row: (row["status_label"] or "").lower(), reverse=reverse_sort)
    else:
        filtered_rows.sort(key=lambda row: (row["student_name"] or "").lower(), reverse=reverse_sort)

    filter_query = _build_promotion_filter_query(
        source_year_id=source_year_id,
        source_term_id=source_term_id,
        target_year_id=target_year_id,
        target_term_id=target_term_id,
        section_id=section_id,
        source_academic_class_id=source_academic_class_id,
        target_academic_class_id=target_academic_class_id,
        search_query=search_query,
        tab=active_tab,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )
    redirect_url = reverse("student_promotion_workflow")
    if filter_query:
        redirect_url = f"{redirect_url}?{filter_query}"

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()
        selected_student_ids = _parse_selected_student_ids(request)
        row_map = {row["student_id"]: row for row in promotion_rows_data["all_rows"]}

        if action == "cancel_selection":
            return redirect(redirect_url)

        if not selected_source_class and action in {"bulk_promote", "promote_single", "mark_repeat", "export_list"}:
            messages.error(request, "Select a source class before running promotion actions.")
            return redirect(redirect_url)

        if action == "promote_single":
            single_student_id = _to_int(request.POST.get("student_id"))
            selected_student_ids = [single_student_id] if single_student_id else []

        if action == "export_list":
            export_rows = (
                [row_map[student_id] for student_id in selected_student_ids if student_id in row_map]
                if selected_student_ids
                else filtered_rows
            )
            response = HttpResponse(content_type="text/csv")
            response["Content-Disposition"] = "attachment; filename=student_promotion_preview.csv"
            writer = csv.writer(response)
            writer.writerow(
                [
                    "Student Name",
                    "Admission No",
                    "Gender",
                    "Current Class",
                    "Average Score",
                    "Attendance %",
                    "Fees Cleared",
                    "Status",
                ]
            )
            for row in export_rows:
                writer.writerow(
                    [
                        row["student_name"],
                        row["admission_no"],
                        row["gender"],
                        row["current_class_label"],
                        row["avg_score"] if row["avg_score"] is not None else "-",
                        row["attendance_percent"] if row["attendance_percent"] is not None else "-",
                        "Yes" if row["fees_ok"] else "No",
                        row["status_label"],
                    ]
                )
            return response

        if action in {"bulk_promote", "promote_single"}:
            if not selected_student_ids:
                messages.error(request, "Select at least one student for promotion.")
                return redirect(redirect_url)
            if not selected_target_class:
                messages.error(request, "Select a valid target class before promoting.")
                return redirect(redirect_url)
            if request.POST.get("confirm_transition") != "1":
                messages.error(request, "Promotion confirmation was not completed.")
                return redirect(redirect_url)

            blocked = [student_id for student_id in selected_student_ids if not row_map.get(student_id, {}).get("can_promote")]
            if blocked:
                messages.error(
                    request,
                    f"{len(blocked)} selected student(s) failed eligibility checks. Review conditional/repeat tabs.",
                )
                return redirect(redirect_url)

            outcome = promote_students_to_academic_class(
                source_academic_class=selected_source_class,
                target_academic_class=selected_target_class,
                active_students_only=False,
                student_ids=selected_student_ids,
                promoted_by=request.user,
            )
            if outcome.has_missing_streams:
                messages.error(
                    request,
                    "Promotion stopped. Target class is missing stream(s): "
                    f"{', '.join(outcome.missing_stream_names)}.",
                )
                return redirect(redirect_url)

            not_promoted_count = max(outcome.total_candidates - outcome.promoted_count, 0)
            messages.success(
                request,
                f"{outcome.promoted_count} student(s) successfully promoted to "
                f"{selected_target_class.Class.name or selected_target_class.Class.code}.",
            )
            if not_promoted_count:
                messages.warning(
                    request,
                    f"{not_promoted_count} selected student(s) were not promoted. Review exceptions in this workflow.",
                )
            return redirect(redirect_url)

        if action == "mark_repeat":
            if not selected_student_ids:
                messages.error(request, "Select at least one student to mark as repeat.")
                return redirect(redirect_url)
            if request.POST.get("confirm_transition") != "1":
                messages.error(request, "Repeat confirmation was not completed.")
                return redirect(redirect_url)
            if not (target_year_id and target_term_id):
                messages.error(request, "Choose the destination academic year and term for repeaters.")
                return redirect(redirect_url)

            repeat_target_class = scoped_academic_classes.filter(
                Class_id=selected_source_class.Class_id,
                section_id=selected_source_class.section_id,
                academic_year_id=target_year_id,
                term_id=target_term_id,
            ).first()
            if not repeat_target_class:
                messages.error(
                    request,
                    "No matching destination class found for repeaters in the selected year/term.",
                )
                return redirect(redirect_url)

            active_student_ids = [student_id for student_id in selected_student_ids if row_map.get(student_id, {}).get("is_active")]
            if not active_student_ids:
                messages.error(request, "Selected students are archived/inactive. Cannot mark repeat.")
                return redirect(redirect_url)

            outcome = promote_students_to_academic_class(
                source_academic_class=selected_source_class,
                target_academic_class=repeat_target_class,
                active_students_only=False,
                student_ids=active_student_ids,
                promoted_by=request.user,
                log_history=False,
            )
            if outcome.has_missing_streams:
                messages.error(
                    request,
                    "Repeat action stopped. Destination class is missing stream(s): "
                    f"{', '.join(outcome.missing_stream_names)}.",
                )
                return redirect(redirect_url)

            messages.success(
                request,
                f"{outcome.promoted_count} student(s) marked as repeat for "
                f"{repeat_target_class.Class.name or repeat_target_class.Class.code}.",
            )
            if outcome.already_registered_count:
                messages.info(
                    request,
                    f"{outcome.already_registered_count} student(s) already existed in the destination register.",
                )
            return redirect(redirect_url)

    paginator = Paginator(filtered_rows, 25)
    page_obj = paginator.get_page(request.GET.get("page") or 1)

    context = {
        "active_level": active_level,
        "academic_years": academic_years,
        "source_terms": source_terms,
        "target_terms": target_terms,
        "sections": sections,
        "source_class_options": source_class_options,
        "target_class_options": target_class_options,
        "selected_source_year_id": source_year_id,
        "selected_source_term_id": source_term_id,
        "selected_target_year_id": target_year_id,
        "selected_target_term_id": target_term_id,
        "selected_section_id": section_id,
        "selected_source_academic_class_id": source_academic_class_id,
        "selected_target_academic_class_id": target_academic_class_id,
        "selected_source_class": selected_source_class,
        "selected_target_class": selected_target_class,
        "suggested_next_class": next_class_obj,
        "search_query": search_query,
        "active_tab": active_tab,
        "sort_by": sort_by,
        "sort_dir": sort_dir,
        "promotion_rows": page_obj.object_list,
        "page_obj": page_obj,
        "tab_counts": promotion_rows_data["tab_counts"],
        "summary": promotion_rows_data["summary"],
        "attendance_threshold": promotion_rows_data["attendance_threshold"],
        "filter_query": filter_query,
    }
    return render(request, "classes/student_promotion_workflow.html", context)


@login_required
def promote_academic_class_students(request, id):
    if request.method != "POST":
        return redirect("academic_class_details_page", id=id)

    active_level = get_active_school_level(request)
    source_class = get_object_or_404(
        get_level_academic_classes_queryset(active_level=active_level),
        pk=id,
    )
    effective_role, _ = _get_effective_role_and_staff_account(request)
    if not _can_manage_promotions(effective_role):
        messages.error(
            request,
            "Only Admin or Director of Studies can run class promotions.",
        )
        return redirect("academic_class_details_page", id=source_class.id)

    form = ClassPromotionForm(
        request.POST,
        source_academic_class=source_class,
        target_queryset=get_level_academic_classes_queryset(active_level=active_level),
    )
    if not form.is_valid():
        for field_name, field_errors in form.errors.items():
            field_label = form.fields.get(field_name).label if field_name in form.fields else field_name
            for error in field_errors:
                messages.error(request, f"{field_label}: {error}")
        return redirect(f"{reverse('academic_class_details_page', args=[source_class.id])}#class-register-section")

    target_class = form.cleaned_data["target_academic_class"]
    source_stream = form.cleaned_data.get("source_stream")
    active_students_only = bool(form.cleaned_data.get("active_students_only"))

    try:
        outcome = promote_students_to_academic_class(
            source_academic_class=source_class,
            target_academic_class=target_class,
            source_stream=source_stream,
            active_students_only=active_students_only,
            promoted_by=request.user,
        )
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect(f"{reverse('academic_class_details_page', args=[source_class.id])}#class-register-section")

    if outcome.has_missing_streams:
        messages.error(
            request,
            "Promotion stopped. Target class is missing stream(s): "
            f"{', '.join(outcome.missing_stream_names)}. "
            "Add these streams in the target class first.",
        )
        return redirect(f"{reverse('academic_class_details_page', args=[source_class.id])}#class-register-section")

    target_label = _format_academic_class_label(target_class)
    if outcome.total_candidates == 0:
        messages.warning(request, "No matching students were found for promotion in the selected scope.")
        return redirect(f"{reverse('academic_class_details_page', args=[source_class.id])}#class-register-section")

    messages.success(
        request,
        f"Promotion completed to {target_label}: "
        f"{outcome.promoted_count} promoted, "
        f"{outcome.already_registered_count} already in target register.",
    )
    if outcome.updated_student_snapshots:
        messages.info(
            request,
            f"Updated profile class snapshot for {outcome.updated_student_snapshots} student(s).",
        )
    if outcome.skipped_inactive_count and active_students_only:
        messages.info(
            request,
            f"Skipped {outcome.skipped_inactive_count} inactive student(s).",
        )
    if outcome.skipped_duplicate_source_count:
        messages.warning(
            request,
            f"Skipped {outcome.skipped_duplicate_source_count} duplicate source register row(s).",
        )

    return redirect(f"{reverse('academic_class_details_page', args=[source_class.id])}#class-register-section")


@login_required
def edit_academic_class_details_view(request,id):
    active_level = get_active_school_level(request)
    academic_class = get_object_or_404(get_level_academic_classes_queryset(active_level=active_level), id=id)
    if request.method =="POST":
        form = AcademicClassForm(request.POST,instance=academic_class)
        bind_form_level_querysets(form, active_level=active_level)
        
        if form.is_valid():
            form.save()
            messages.success(request,SUCCESS_ADD_MESSAGE)
            return redirect(academic_class_view)
        else:
            messages.error(request, FAILURE_MESSAGE)
            
    form = AcademicClassForm(instance=academic_class)
    bind_form_level_querysets(form, active_level=active_level)
    
    context ={
        "form": form,
        "academic_class": academic_class
        
    }
    return  render(request,"classes/edit_academic_class_details.html",context)

@login_required
def add_class_stream(request, id):
    active_level = get_active_school_level(request)
    academic_class = get_object_or_404(get_level_academic_classes_queryset(active_level=active_level), pk=id)
    effective_role, _ = _get_effective_role_and_staff_account(request)
    if not _can_manage_stream_records(effective_role):
        messages.error(request, "Only Admin or Academic Head can manage class streams.")
        return HttpResponseRedirect(reverse(academic_class_details_view, args=[academic_class.id]))
    form = AcademicClassStreamForm(request.POST)
    bind_form_level_querysets(form, active_level=active_level)

    if form.is_valid():
        cs = form.save(commit=False)
        cs.academic_class = academic_class
        cs.save()
        messages.success(request, SUCCESS_ADD_MESSAGE)
    else:
        # Surface validation errors so the user knows what to fix
        messages.error(request, FAILURE_MESSAGE)
        try:
            err_txt = form.errors.as_text()
            if err_txt:
                messages.error(request, err_txt)
        except Exception:
            pass

    return HttpResponseRedirect(reverse(academic_class_details_view, args=[academic_class.id]))

@login_required
def edit_class_stream(request, id):
    effective_role, _ = _get_effective_role_and_staff_account(request)
    if not _can_manage_stream_records(effective_role):
        messages.error(request, "Only Admin or Academic Head can manage class streams.")
        return redirect("academic_class_page")

    active_level = get_active_school_level(request)
    class_stream = get_object_or_404(get_level_class_streams_queryset(active_level=active_level), id=id)
    
    if request.method == "POST":
        form = AcademicClassStreamForm(request.POST, instance=class_stream)
        bind_form_level_querysets(form, active_level=active_level)
        if form.is_valid():
            form.save()
            messages.success(request, "Class Stream updated successfully!")
            return redirect(reverse("academic_class_details_page", args=[class_stream.academic_class.id]))

        else:
            messages.error(request, FAILURE_MESSAGE)
    else:
        form = AcademicClassStreamForm(instance=class_stream)
        bind_form_level_querysets(form, active_level=active_level)
    
    return render(request, "classes/edit_class_stream.html", {"form": form, "class_stream": class_stream})


@login_required
def delete_class_stream(request, id):
    effective_role, _ = _get_effective_role_and_staff_account(request)
    if not _can_manage_stream_records(effective_role):
        messages.error(request, "Only Admin or Academic Head can manage class streams.")
        return redirect("academic_class_page")

    active_level = get_active_school_level(request)
    class_stream = get_object_or_404(get_level_class_streams_queryset(active_level=active_level), id=id)
    academic_class_id = class_stream.academic_class_id
    if request.method != "POST":
        messages.error(request, "Delete requests must be submitted via POST.")
        return redirect(reverse("academic_class_details_page", args=[academic_class_id]))

    class_stream.delete()
    
    messages.success(request,DELETE_MESSAGE)
    return redirect(reverse("academic_class_details_page", args=[academic_class_id]))


@login_required
def class_bill_list_view(request):
    active_level = get_active_school_level(request)
    academic_classes = get_level_academic_classes_queryset(active_level=active_level).select_related(
        'Class',
        'academic_year',
        'term',
        'section',
    )

    class_filter = request.GET.get('class')
    academic_year_filter = request.GET.get('academic_year')
    term_filter = request.GET.get('term')
    status_filter = request.GET.get('status', 'all')

    # Convert 'all' to None for proper filtering
    if class_filter == 'all':
        class_filter = None
    if academic_year_filter == 'all':
        academic_year_filter = None
    if term_filter == 'all':
        term_filter = None

    # Apply filters
    if class_filter:
        academic_classes = academic_classes.filter(Class__id=class_filter)
    if academic_year_filter:
        academic_classes = academic_classes.filter(academic_year__id=academic_year_filter)
    if term_filter:
        academic_classes = academic_classes.filter(term__id=term_filter)

    # Get filter options
    class_options = get_level_classes_queryset(active_level=active_level)
    academic_year_options = AcademicYear.objects.all()
    term_options = Term.objects.all()

    # Calculate bill statistics for each academic class
    academic_classes_with_stats = []
    total_billed_amount = 0
    total_collected_amount = 0
    total_outstanding_amount = 0

    for academic_class in academic_classes:
        # Get all bills for this class
        class_bills = ClassBill.objects.filter(academic_class=academic_class).select_related('bill_item')

        # Get all active students
        students_in_class = Student.objects.filter(current_class=academic_class.Class, is_active=True)
        total_students = students_in_class.count()


        # Calculate total billed amount including both ClassBills and individual StudentBillItems
        total_billed = 0

        # Add ClassBill amounts (standard class-wide bills)
        class_bill_total = sum(bill.amount for bill in class_bills)
        total_billed += class_bill_total * total_students

        # Add individual StudentBillItem amounts (custom student-specific bills)
        for student in students_in_class:
            student_bill_items = StudentBillItem.objects.filter(
                bill__student=student,
                bill__academic_class=academic_class
            ).select_related('bill_item')

            for item in student_bill_items:
                # Only add if it's not already included in the ClassBill calculation
                # (to avoid double-counting standard class bills)
                if not class_bills.filter(bill_item=item.bill_item).exists():
                    total_billed += item.amount

        # Calculate collection stats
        total_class_billed = total_billed
        total_class_collected = 0
        total_class_outstanding = 0

        for student in students_in_class:
            student_bills = StudentBill.objects.filter(
                student=student,
                academic_class=academic_class
            ).select_related('student')

            for student_bill in student_bills:
                total_class_collected += student_bill.amount_paid
                total_class_outstanding += student_bill.balance

        # Calculate collection rate
        collection_rate = (total_class_collected / total_class_billed * 100) if total_class_billed > 0 else 0

        # Add statistics to academic class
        academic_class.stats = {
            'total_bills': class_bills.count(),
            'total_billed': total_billed,
            'total_students': total_students,
            'class_billed': total_class_billed,
            'class_collected': total_class_collected,
            'class_outstanding': total_class_outstanding,
            'collection_rate': round(collection_rate, 1),
            'bills': class_bills
        }

        academic_classes_with_stats.append(academic_class)

        # Accumulate totals
        total_billed_amount += total_class_billed
        total_collected_amount += total_class_collected
        total_outstanding_amount += total_class_outstanding

    # Calculate overall collection rate
    overall_collection_rate = (total_collected_amount / total_billed_amount * 100) if total_billed_amount > 0 else 0

    # Calculate total students from all classes
    total_students = sum(academic_class.stats['total_students'] for academic_class in academic_classes_with_stats)

    # Debug total calculation
    context = {
        "academic_classes": academic_classes_with_stats,
        "class_options": class_options,
        "academic_year_options": academic_year_options,
        "term_options": term_options,
        "class_filter": class_filter if class_filter else 'all',
        "academic_year_filter": academic_year_filter if academic_year_filter else 'all',
        "term_filter": term_filter if term_filter else 'all',
        "status_filter": status_filter,
        # Summary statistics
        "total_classes": len(academic_classes_with_stats),
        "total_students": total_students,
        "total_billed_amount": total_billed_amount,
        "total_collected_amount": total_collected_amount,
        "total_outstanding_amount": total_outstanding_amount,
        "overall_collection_rate": round(overall_collection_rate, 1),
        # Current filters for URL building
        "current_filters": {
            'class': class_filter,
            'academic_year': academic_year_filter,
            'term': term_filter,
            'status': status_filter
        }
    }

    return render(request, "fees/class_bill_list.html", context)



@login_required
def add_class_bill_item_view(request, id):
    active_level = get_active_school_level(request)
    academic_class = get_object_or_404(get_level_academic_classes_queryset(active_level=active_level), id=id)
    class_bills = ClassBill.objects.filter(academic_class=academic_class)

    if request.method == "POST":
        form = ClassBillForm(request.POST)
        if form.is_valid():
            
            class_bill = form.save(commit=False)
            class_bill.academic_class = academic_class 
            class_bill.save()
            
            students_in_class = Student.objects.filter(current_class=academic_class.Class, is_active=True)
            
            for student in students_in_class:
                # Checking  if there's already an existing StudentBill for the student $ academic class
                student_bill, created = StudentBill.objects.get_or_create(
                    student=student,
                    academic_class=academic_class,
                    status="Unpaid",  
                )
                                                
                if class_bill.bill_item.item_name != "School Fees":
                    StudentBillItem.objects.create(
                        bill=student_bill,
                        bill_item=class_bill.bill_item,
                        description=class_bill.bill_item.description,  
                        amount=class_bill.amount  
                    )                                
                student_bill.save()

            messages.success(request, SUCCESS_ADD_MESSAGE)
            return redirect("class_bill_list")  
        else:
            messages.error(request, FAILURE_MESSAGE)
    else:
        
        form = ClassBillForm()

    context = {
        "academic_class": academic_class,
        "bill_item_form": form,
        "class_bills": class_bills,
        "academic_year": academic_class.academic_year,
        "term": academic_class.term,
    }
    return render(request, "fees/class_bill_items.html", context)



@login_required
def edit_class_bill_item_view(request, id):
    active_level = get_active_school_level(request)
    class_bill = get_object_or_404(
        ClassBill.objects.filter(academic_class__in=get_level_academic_classes_queryset(active_level=active_level)),
        id=id,
    )
    academic_class = class_bill.academic_class  # Retrieve related AcademicClass

    if request.method == "POST":
        form = ClassBillForm(request.POST, instance=class_bill)
        if form.is_valid():
            updated_class_bill = form.save()  

            # Update the StudentBillItems for all active students in the academic class
            students_in_class = Student.objects.filter(current_class=academic_class.Class, is_active=True)

            for student in students_in_class:
                student_bill, created = StudentBill.objects.get_or_create(
                    student=student,
                    academic_class=academic_class,
                    status="Unpaid",
                )

                
                if updated_class_bill.bill_item.item_name != "School Fees":
                    # Ensure a single StudentBillItem per (bill, bill_item); clean up duplicates if any
                    qs = StudentBillItem.objects.filter(
                        bill=student_bill,
                        bill_item=updated_class_bill.bill_item
                    ).order_by('id')
                    if qs.exists():
                        student_bill_item = qs.first()
                        # Remove duplicates if present
                        if qs.count() > 1:
                            qs.exclude(pk=student_bill_item.pk).delete()
                        # Update fields to reflect the current class bill configuration
                        student_bill_item.description = updated_class_bill.bill_item.description
                        student_bill_item.amount = updated_class_bill.amount
                        student_bill_item.save()
                    else:
                        StudentBillItem.objects.create(
                            bill=student_bill,
                            bill_item=updated_class_bill.bill_item,
                            description=updated_class_bill.bill_item.description,
                            amount=updated_class_bill.amount
                        )

                student_bill.save()

            messages.success(request, SUCCESS_EDIT_MESSAGE)
            return redirect("class_bill_list")  
        else:
            messages.error(request, FAILURE_MESSAGE)
    else:
        form = ClassBillForm(instance=class_bill)

    context = {
        "class_bill": class_bill,
        "bill_item_form": form,
    }
    return render(request, "fees/edit_class_bill_item.html", context)


@login_required
def delete_class_bill_item_view(request, id):
    if request.method != "POST":
        messages.error(request, "Delete requests must be submitted via POST.")
        return redirect("class_bill_list")

    active_level = get_active_school_level(request)
    class_bill = get_object_or_404(
        ClassBill.objects.filter(academic_class__in=get_level_academic_classes_queryset(active_level=active_level)),
        id=id,
    )
    StudentBillItem.objects.filter(
        bill__academic_class=class_bill.academic_class,
        bill_item=class_bill.bill_item
    ).delete()
    class_bill.delete()
    messages.success(request, DELETE_MESSAGE)
    return redirect("class_bill_list")

 

@login_required
def class_subject_allocation_list(request):
    # Legacy route, keep URL stable while rendering one professional page.
    return redirect("subject_allocation_page")


def _is_teaching_staff(staff):
    if not staff:
        return False
    return bool(staff.is_academic_staff or staff.department == ACADEMIC)


@login_required
def add_class_subject_allocation(request):
    active_level = get_active_school_level(request)
    staff_account = getattr(request.user, "staff_account", None)
    staff_member = getattr(staff_account, "staff", None)
    role_name = staff_account.role.name if staff_account and staff_account.role else ""
    active_role = request.session.get("active_role_name")
    effective_role = (active_role or role_name or "").strip().lower()
    is_dos = effective_role in {"director of studies", "dos", "academic head"}
    is_admin = effective_role in {"admin", "head master", "head teacher", "headteacher"}
    can_manage = is_dos or is_admin

    scoped_streams = (
        get_level_class_streams_queryset(active_level=active_level)
        .select_related(
            "academic_class__Class",
            "academic_class__academic_year",
            "academic_class__term",
            "academic_class__section",
            "stream",
            "class_teacher",
        )
        .order_by("academic_class__Class__name", "stream__stream")
    )

    if not can_manage:
        allowed_stream_ids = set()
        if staff_member:
            allowed_stream_ids.update(
                scoped_streams.filter(class_teacher=staff_member).values_list("id", flat=True)
            )
            allowed_stream_ids.update(
                get_allocation_queryset(teacher=staff_member).values_list(
                    "academic_class_stream_id", flat=True
                )
            )
        scoped_streams = (
            scoped_streams.filter(id__in=allowed_stream_ids)
            if allowed_stream_ids
            else scoped_streams.none()
        )

    year_ids = scoped_streams.values_list("academic_class__academic_year_id", flat=True).distinct()
    academic_years = AcademicYear.objects.filter(id__in=year_ids).order_by("-academic_year", "-id")

    selected_year_id = request.GET.get("academic_year") or request.POST.get("academic_year")
    if selected_year_id and not academic_years.filter(id=selected_year_id).exists():
        selected_year_id = None
    if not selected_year_id:
        selected_year = academic_years.filter(is_current=True).first() or academic_years.first()
        selected_year_id = str(selected_year.id) if selected_year else ""
    selected_year = academic_years.filter(id=selected_year_id).first() if selected_year_id else None

    term_ids = scoped_streams.values_list("academic_class__term_id", flat=True).distinct()
    terms = Term.objects.filter(id__in=term_ids)
    if selected_year_id:
        terms = terms.filter(academic_year_id=selected_year_id)
    terms = terms.order_by("term", "start_date", "id")

    selected_term_id = request.GET.get("term") or request.POST.get("term")
    if selected_term_id and not terms.filter(id=selected_term_id).exists():
        selected_term_id = None
    if not selected_term_id:
        selected_term = terms.filter(is_current=True).first() or terms.first()
        selected_term_id = str(selected_term.id) if selected_term else ""
    selected_term = terms.filter(id=selected_term_id).first() if selected_term_id else None

    filtered_streams = scoped_streams
    if selected_year_id:
        filtered_streams = filtered_streams.filter(academic_class__academic_year_id=selected_year_id)
    if selected_term_id:
        filtered_streams = filtered_streams.filter(academic_class__term_id=selected_term_id)
    filtered_streams = filtered_streams.order_by("academic_class__Class__name", "stream__stream")

    selected_stream_id = request.GET.get("class_stream") or request.POST.get("class_stream")
    if selected_stream_id and not filtered_streams.filter(id=selected_stream_id).exists():
        selected_stream_id = None
    if not selected_stream_id:
        selected_stream = filtered_streams.first()
        selected_stream_id = str(selected_stream.id) if selected_stream else ""
    selected_stream = filtered_streams.filter(id=selected_stream_id).first() if selected_stream_id else None

    def _build_redirect_url():
        params = {}
        if selected_year_id:
            params["academic_year"] = selected_year_id
        if selected_term_id:
            params["term"] = selected_term_id
        if selected_stream_id:
            params["class_stream"] = selected_stream_id
        query = urlencode(params)
        base = reverse("subject_allocation_page")
        return f"{base}?{query}" if query else base

    if request.method == "POST":
        action = request.POST.get("action")
        if action in {"add_allocation", "edit_allocation", "delete_allocation"} and not can_manage:
            messages.error(
                request,
                "You have view-only access. Only Admin or Academic Head can manage allocations.",
            )
            return redirect(_build_redirect_url())

        if action == "add_allocation":
            class_stream_id = request.POST.get("class_stream")
            subject_id = request.POST.get("subject")
            subject_teacher_id = request.POST.get("subject_teacher")

            class_stream = scoped_streams.filter(id=class_stream_id).first()
            subject = get_level_subjects_queryset(active_level=active_level).filter(id=subject_id).first()
            subject_teacher = Staff.objects.filter(id=subject_teacher_id).first()

            if not class_stream or not subject or not subject_teacher:
                messages.error(request, "Please select class stream, subject and teacher.")
                return redirect(_build_redirect_url())
            if not _is_teaching_staff(subject_teacher):
                messages.error(request, "Selected staff is not academic/teaching staff.")
                return redirect(_build_redirect_url())
            if subject.section_id != class_stream.academic_class.section_id:
                messages.error(
                    request,
                    "Selected subject does not belong to the selected class stream section.",
                )
                return redirect(_build_redirect_url())
            if get_allocation_queryset(class_streams=[class_stream]).filter(subject=subject).exists():
                messages.error(request, "This subject is already allocated to the selected class stream.")
                return redirect(_build_redirect_url())

            upsert_class_subject_allocation(
                class_stream=class_stream,
                subject=subject,
                subject_teacher=subject_teacher,
            )
            messages.success(request, SUCCESS_ADD_MESSAGE)
            return redirect(_build_redirect_url())

        if action == "edit_allocation":
            allocation_id = request.POST.get("allocation_id")
            subject_teacher_id = request.POST.get("subject_teacher")

            allocation = get_object_or_404(
                get_allocation_queryset(
                    academic_classes=get_level_academic_classes_queryset(active_level=active_level)
                ),
                id=allocation_id,
            )
            subject_teacher = Staff.objects.filter(id=subject_teacher_id).first()
            if not subject_teacher:
                messages.error(request, "Please select a teacher.")
                return redirect(_build_redirect_url())
            if not _is_teaching_staff(subject_teacher):
                messages.error(request, "Selected staff is not academic/teaching staff.")
                return redirect(_build_redirect_url())

            save_class_subject_allocation(
                allocation,
                class_stream=allocation.academic_class_stream,
                subject=allocation.subject,
                subject_teacher=subject_teacher,
            )
            messages.success(request, SUCCESS_EDIT_MESSAGE)
            return redirect(_build_redirect_url())

        if action == "delete_allocation":
            allocation_id = request.POST.get("allocation_id")
            allocation = get_object_or_404(
                get_allocation_queryset(
                    academic_classes=get_level_academic_classes_queryset(active_level=active_level)
                ),
                id=allocation_id,
            )
            delete_class_subject_allocation_record(allocation)
            messages.success(request, DELETE_MESSAGE)
            return redirect(_build_redirect_url())

    allocations = (
        get_allocation_queryset(class_streams=[selected_stream])
        if selected_stream
        else ClassSubjectAllocation.objects.none()
    )

    subjects = get_level_subjects_queryset(active_level=active_level)
    if selected_stream:
        subjects = subjects.filter(section_id=selected_stream.academic_class.section_id)
    subjects = subjects.order_by("name")
    allocated_subject_ids = set(allocations.values_list("subject_id", flat=True))

    teachers = (
        Staff.objects.filter(
            Q(is_academic_staff=True) | Q(department=ACADEMIC),
            staff_status="Active",
        )
        .order_by("first_name", "last_name", "id")
        .distinct()
    )

    teacher_stats = {
        str(teacher.id): {"name": str(teacher), "subjects_count": 0, "class_streams": []}
        for teacher in teachers
    }
    seen_streams = {str(teacher.id): set() for teacher in teachers}
    allocation_scope = get_allocation_queryset(
        current_year=selected_year,
        current_term=selected_term,
    ).select_related(
        "academic_class_stream__academic_class__Class",
        "academic_class_stream__stream",
    )
    for allocation in allocation_scope:
        teacher_key = str(allocation.subject_teacher_id)
        if teacher_key not in teacher_stats:
            continue
        teacher_stats[teacher_key]["subjects_count"] += 1
        class_code = getattr(allocation.academic_class_stream.academic_class.Class, "code", "")
        stream_code = getattr(allocation.academic_class_stream.stream, "stream", "")
        stream_label = f"{class_code}{stream_code}".strip() or str(allocation.academic_class_stream)
        if stream_label not in seen_streams[teacher_key]:
            seen_streams[teacher_key].add(stream_label)
            teacher_stats[teacher_key]["class_streams"].append(stream_label)

    class_teacher_name = str(selected_stream.class_teacher) if selected_stream and selected_stream.class_teacher else "-"
    total_students = (
        ClassRegister.objects.filter(
            academic_class_stream=selected_stream,
            student__is_active=True,
        ).count()
        if selected_stream
        else 0
    )

    context = {
        "academic_years": academic_years,
        "terms": terms,
        "class_streams": filtered_streams,
        "selected_year_id": str(selected_year_id) if selected_year_id else "",
        "selected_term_id": str(selected_term_id) if selected_term_id else "",
        "selected_stream_id": str(selected_stream_id) if selected_stream_id else "",
        "selected_stream": selected_stream,
        "allocations": allocations,
        "subjects": subjects,
        "teachers": teachers,
        "allocated_subject_ids": allocated_subject_ids,
        "teacher_stats": teacher_stats,
        "can_manage": can_manage,
        "is_dos": is_dos,
        "is_admin": is_admin,
        "class_teacher_name": class_teacher_name,
        "total_students": total_students,
        "subjects_allocated_count": allocations.count(),
    }
    return render(request, "classes/classsubjectallocation_form.html", context)

@login_required
def edit_subject_allocation_view(request,id):
    # Legacy endpoint: keep URL stable by redirecting to the unified page.
    active_level = get_active_school_level(request)
    allocation = get_object_or_404(
        get_allocation_queryset(
            academic_classes=get_level_academic_classes_queryset(active_level=active_level)
        ),
        id=id,
    )
    redirect_url = (
        f"{reverse('subject_allocation_page')}"
        f"?academic_year={allocation.academic_class_stream.academic_class.academic_year_id}"
        f"&term={allocation.academic_class_stream.academic_class.term_id}"
        f"&class_stream={allocation.academic_class_stream_id}"
    )
    messages.info(request, "Use the Edit action on the allocation page.")
    return redirect(redirect_url)

@login_required
def delete_class_subject_allocation(request, id):
    active_level = get_active_school_level(request)
    staff_account = getattr(request.user, "staff_account", None)
    role_name = staff_account.role.name if staff_account and staff_account.role else ""
    active_role = request.session.get("active_role_name")
    effective_role = (active_role or role_name or "").strip().lower()
    is_dos = effective_role in {"director of studies", "dos", "academic head"}
    is_admin = effective_role in {"admin", "head master", "head teacher", "headteacher"}

    if not (is_dos or is_admin):
        messages.error(request, "Only Admin or the Director of Studies can manage subject allocations.")
        return redirect("subject_allocation_page")
    if request.method != "POST":
        messages.error(request, "Delete requests must be submitted via POST.")
        return redirect("subject_allocation_page")

    allocation = get_object_or_404(
        get_allocation_queryset(
            academic_classes=get_level_academic_classes_queryset(active_level=active_level)
        ),
        pk=id,
    )

    delete_class_subject_allocation_record(allocation)
    messages.success(request, DELETE_MESSAGE)
    redirect_url = (
        f"{reverse('subject_allocation_page')}"
        f"?academic_year={allocation.academic_class_stream.academic_class.academic_year_id}"
        f"&term={allocation.academic_class_stream.academic_class.term_id}"
        f"&class_stream={allocation.academic_class_stream_id}"
    )
    return redirect(redirect_url)


@login_required
def copy_allocations_from_previous_term(request):
    """Copy subject allocations from the previous term to the current term."""
    active_level = get_active_school_level(request)
    staff_account = getattr(request.user, "staff_account", None)
    role_name = staff_account.role.name if staff_account and staff_account.role else None
    active_role = request.session.get("active_role_name")
    effective_role = active_role or role_name
    is_dos = effective_role in {"Director of Studies", "DOS"}
    is_admin = effective_role in {"Admin", "Head master"}

    if not (is_dos or is_admin):
        messages.error(request, "Only Admin or the Director of Studies can copy allocations.")
        return redirect("class_subject_allocation_page")

    try:
        # Get current academic year and term
        from app.selectors.school_settings import get_current_academic_year
        from app.models.classes import Term
        
        current_year = get_current_academic_year()
        current_term = Term.objects.filter(is_current=True).first()

        if not current_year or not current_term:
            messages.error(request, "No current academic year or term set.")
            return redirect("subject_allocation_page")

        # Find the previous term
        if current_term.term == "1":
            # Term 1 -> look for previous year's Term 3
            # Get previous year by subtracting 1 from the year string
            try:
                prev_year_num = int(current_year.academic_year) - 1
                previous_year = AcademicYear.objects.filter(
                    academic_year=str(prev_year_num)
                ).first()
            except:
                previous_year = None
            previous_term = Term.objects.filter(term="3").first()
        else:
            # Same year, previous term number
            previous_year = current_year
            prev_term_num = str(int(current_term.term) - 1)
            previous_term = Term.objects.filter(term=prev_term_num).first()

        if not previous_term:
            messages.error(request, "Could not determine previous term.")
            return redirect("subject_allocation_page")

        # Get all class streams for the current term
        current_class_streams = get_level_class_streams_queryset(active_level=active_level).filter(
            academic_class__academic_year=current_year,
            academic_class__term=current_term
        )

        previous_class_streams = get_level_class_streams_queryset(active_level=active_level).filter(
            academic_class__academic_year=previous_year,
            academic_class__term=previous_term
        ).select_related("academic_class__Class", "stream")
        current_class_streams = current_class_streams.select_related("academic_class__Class", "stream")

        copy_result = copy_allocations_for_term_transition(
            previous_class_streams=list(previous_class_streams),
            current_class_streams=list(current_class_streams),
        )
        messages.success(
            request,
            f"Successfully copied {copy_result['created_count']} allocations. "
            f"{copy_result['skipped_count']} already existed.",
        )
        errors = copy_result["errors"]
        if errors:
            messages.warning(request, f"Some errors occurred: {', '.join(errors[:3])}")
    except Exception as e:
        logger.error(f"Error copying allocations: {str(e)}")
        messages.error(request, f"Error copying allocations: {str(e)}")

    return redirect("subject_allocation_page")
    



@login_required
def bulk_create_class_bills(request):
    """
    Bulk create class bills for multiple classes at once
    """
    active_level = get_active_school_level(request)
    scoped_academic_classes = get_level_academic_classes_queryset(active_level=active_level)

    if request.method == "POST":
        # Get selected classes and bill item
        selected_classes = request.POST.getlist('selected_classes')
        bill_item_id = request.POST.get('bill_item')
        amount = request.POST.get('amount')

        if not selected_classes:
            messages.error(request, "Please select at least one class.")
            return redirect('bulk_create_class_bills')

        if not bill_item_id or not amount:
            messages.error(request, "Please provide bill item and amount.")
            return redirect('bulk_create_class_bills')

        try:
            bill_item = BillItem.objects.get(id=bill_item_id)
            amount = float(amount)

            # Get current academic year and term
            current_year = AcademicYear.objects.filter(is_current=True).first()
            current_term = Term.objects.filter(is_current=True).first()

            if not current_year or not current_term:
                messages.error(request, "No current academic year or term found.")
                return redirect('bulk_create_class_bills')

            bills_created = 0
            students_affected = 0
            total_amount = 0

            for class_id in selected_classes:
                try:
                    academic_class = scoped_academic_classes.get(
                        Class__id=class_id,
                        academic_year=current_year,
                        term=current_term
                    )

                    # Create class bill
                    class_bill, created = ClassBill.objects.get_or_create(
                        academic_class=academic_class,
                        bill_item=bill_item,
                        defaults={'amount': amount}
                    )

                    if created:
                        bills_created += 1

                        # Create student bill items
                        students_in_class = Student.objects.filter(current_class__id=class_id, is_active=True)
                        for student in students_in_class:
                            student_bill, _ = StudentBill.objects.get_or_create(
                                student=student,
                                academic_class=academic_class,
                                defaults={'status': 'Unpaid'}
                            )

                            if bill_item.item_name != "School Fees":
                                # Ensure a single StudentBillItem per (bill, bill_item); clean up duplicates if any
                                qs = StudentBillItem.objects.filter(
                                    bill=student_bill,
                                    bill_item=bill_item
                                ).order_by('id')
                                if qs.exists():
                                    student_bill_item = qs.first()
                                    # Remove duplicates if present
                                    if qs.count() > 1:
                                        qs.exclude(pk=student_bill_item.pk).delete()
                                    # Update to current values
                                    student_bill_item.description = bill_item.description
                                    student_bill_item.amount = amount
                                    student_bill_item.save()
                                else:
                                    StudentBillItem.objects.create(
                                        bill=student_bill,
                                        bill_item=bill_item,
                                        description=bill_item.description,
                                        amount=amount
                                    )

                            students_affected += 1

                        total_amount += amount * students_in_class.count()

                except AcademicClass.DoesNotExist:
                    messages.warning(request, f"Academic class not found for class ID {class_id}")
                    continue

            if bills_created > 0:
                success_msg = (
                    f"✅ Bulk bill creation completed!<br>"
                    f"• Bills created: {bills_created}<br>"
                    f"• Students affected: {students_affected}<br>"
                    f"• Total billing amount: UGX {total_amount:,.0f}"
                )
                messages.success(request, success_msg)
            else:
                messages.warning(request, "No new bills were created. They may already exist.")

        except BillItem.DoesNotExist:
            messages.error(request, "Selected bill item not found.")
        except ValueError:
            messages.error(request, "Invalid amount provided.")
        except Exception as e:
            messages.error(request, f"An error occurred: {str(e)}")

        return redirect('class_bill_list')

    # GET request - show form
    # Get current academic year and term
    current_year = AcademicYear.objects.filter(is_current=True).first()
    current_term = Term.objects.filter(is_current=True).first()

    available_classes = []
    if current_year and current_term:
        academic_classes = scoped_academic_classes.filter(
            academic_year=current_year,
            term=current_term
        ).select_related('Class')

        for ac in academic_classes:
            # Check if class already has bills
            existing_bills = ClassBill.objects.filter(academic_class=ac).count()

            # Get actual active student count for this class
            student_count = Student.objects.filter(current_class=ac.Class, is_active=True).count()

            available_classes.append({
                'id': ac.Class.id,
                'name': str(ac.Class),
                'existing_bills': existing_bills,
                'academic_class': ac,
                'student_count': student_count
            })

    bill_items = BillItem.objects.all()

    context = {
        'available_classes': available_classes,
        'bill_items': bill_items,
        'current_year': current_year,
        'current_term': current_term,
    }

    return render(request, 'fees/bulk_create_bills.html', context)
    
    
