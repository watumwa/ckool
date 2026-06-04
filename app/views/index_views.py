from django.shortcuts import render, redirect, HttpResponseRedirect
from django.http import HttpResponse
from django.urls import reverse
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db.models import Count, Sum, Q, F, ExpressionWrapper, DecimalField, Avg
from django.db.models.functions import TruncMonth
from django.core.cache import cache
from django.conf import settings
from django.utils import timezone
from django.contrib import messages
from datetime import date
from pathlib import Path
import logging
from app.models.classes import Class, AcademicClass, Term, AcademicClassStream, Stream
from app.models.school_settings import AcademicYear
from app.models.staffs import Staff, Role
from app.models.students import Student, ClassRegister
from app.models.fees_payment import StudentBill, Payment, StudentBillItem
from app.models.finance import Budget, Expenditure, ExpenditureItem, IncomeSource, ApprovalWorkflow
from app.models.results import Assessment, Result, GradingSystem, ResultBatch, VerificationCorrectionLog
from app.models.subjects import Subject
from app.models.communications import Announcement, Event
from app.models.attendance import AttendanceRecord, AttendanceStatus
from app.models.audit import AuditLog
from app.models.accounts import StaffAccount
from app.models.timetables import Timetable
from app.selectors.school_settings import get_current_academic_year
from app.services.level_scope import (
    get_level_academic_classes_queryset,
    get_level_classes_queryset,
    get_level_class_streams_queryset,
    get_level_students_queryset,
    get_level_subjects_queryset,
)
from app.services.school_level import get_active_school_level
from app.services.teacher_assignments import (
    get_class_stream_assignments,
    get_teacher_assignments,
)


logger = logging.getLogger(__name__)


def _iter_template_roots():
    roots = set()
    base_dir = getattr(settings, "BASE_DIR", None)
    if base_dir:
        base_path = Path(base_dir)
        roots.add(base_path / "templates")
        roots.add(base_path / "app" / "templates")
    for config in getattr(settings, "TEMPLATES", []):
        for directory in config.get("DIRS", []):
            roots.add(Path(directory))
    return [root for root in roots if root.exists() and root.is_dir()]


def _guess_template_path_from_bytes(payload):
    if not isinstance(payload, (bytes, bytearray)):
        return None

    for root in _iter_template_roots():
        for candidate in root.rglob("*.html"):
            try:
                if candidate.read_bytes() == payload:
                    return str(candidate)
            except OSError:
                continue
    return None


def _find_invalid_template_files(limit=20):
    invalid = []
    for root in _iter_template_roots():
        for candidate in root.rglob("*.html"):
            try:
                candidate.read_text(encoding="utf-8")
            except UnicodeDecodeError as exc:
                invalid.append(f"{candidate}:{exc.start}")
            except OSError:
                continue
            if len(invalid) >= limit:
                return invalid
    return invalid


def _safe_dashboard_fallback_response():
    html = (
        "<!doctype html>"
        "<html lang='en'>"
        "<head>"
        "<meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>Dashboard Temporarily Unavailable</title>"
        "<style>"
        "body{font-family:Arial,sans-serif;background:#f8fafc;color:#1f2937;margin:0;padding:24px;}"
        ".card{max-width:720px;margin:40px auto;background:#fff;border:1px solid #d1d5db;border-radius:8px;padding:24px;}"
        "h1{font-size:24px;margin:0 0 12px;}"
        "p{line-height:1.5;margin:8px 0;}"
        "code{background:#f3f4f6;padding:2px 6px;border-radius:4px;}"
        "</style>"
        "</head>"
        "<body>"
        "<div class='card'>"
        "<h1>Dashboard is temporarily unavailable</h1>"
        "<p>A template encoding issue was detected while loading <code>/index/</code>.</p>"
        "<p>The issue has been logged. Replace the corrupted deployed template file with a UTF-8 version and restart the app service.</p>"
        "</div>"
        "</body>"
        "</html>"
    )
    return HttpResponse(html)


def _render_index_template(request, context):
    try:
        return render(request, "index.html", context)
    except UnicodeDecodeError as exc:
        template_path = _guess_template_path_from_bytes(exc.object)
        snippet = b""
        if isinstance(exc.object, (bytes, bytearray)):
            start = max(exc.start - 24, 0)
            end = min(exc.start + 24, len(exc.object))
            snippet = bytes(exc.object[start:end])
        logger.exception(
            "Unicode decode failure while rendering index.html. "
            "template_path=%s position=%s snippet=%r",
            template_path,
            getattr(exc, "start", None),
            snippet,
        )
        invalid_files = _find_invalid_template_files()
        if invalid_files:
            logger.error("Invalid UTF-8 template files detected: %s", invalid_files)
        messages.error(
            request,
            "Dashboard template encoding issue detected. A fallback page is being shown.",
        )
        return _safe_dashboard_fallback_response()


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

    if action == AuditLog.ACTION_LOGIN:
        return "Successful login"
    if action == AuditLog.ACTION_LOGOUT:
        return "Successful logout"

    if action == AuditLog.ACTION_UPDATE:
        changed_fields = [str(field) for field in changes.keys() if field not in {"old", "new"}]
        if changed_fields:
            preview = ", ".join(changed_fields[:3])
            if len(changed_fields) > 3:
                preview = f"{preview} (+{len(changed_fields) - 3} more)"
            return f"Fields changed: {preview}"
        return "Updated record"

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


def under_construction_view(request):
    """Under construction / Coming soon page"""
    return render(request, "under_construction.html")


@login_required
def global_search_view(request):
    query = (request.GET.get("q") or "").strip()
    has_query = bool(query)
    active_level = get_active_school_level(request)

    students = []
    staff_members = []
    classes = []
    streams = []
    academic_classes = []
    subjects = []
    users = []

    result_counts = {
        "students": 0,
        "staff": 0,
        "classes": 0,
        "streams": 0,
        "academic_classes": 0,
        "subjects": 0,
        "users": 0,
    }

    if has_query:
        level_academic_class_ids = get_level_academic_classes_queryset(active_level=active_level).values_list("id", flat=True)
        student_scope = get_level_students_queryset(active_level=active_level).select_related("current_class", "stream")
        student_scope = student_scope.filter(
            Q(student_name__icontains=query)
            | Q(reg_no__icontains=query)
            | Q(student_number__icontains=query)
            | Q(guardian__icontains=query)
            | Q(contact__icontains=query)
        ).order_by("student_name")
        result_counts["students"] = student_scope.count()
        students = list(student_scope[:10])

        staff_scope = Staff.objects.prefetch_related("roles").filter(
            Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(email__icontains=query)
            | Q(contacts__icontains=query)
            | Q(department__icontains=query)
            | Q(roles__name__icontains=query)
        ).distinct().order_by("first_name", "last_name")
        result_counts["staff"] = staff_scope.count()
        staff_members = list(staff_scope[:10])

        class_scope = get_level_classes_queryset(active_level=active_level).select_related("section").filter(
            Q(name__icontains=query)
            | Q(code__icontains=query)
            | Q(section__section_name__icontains=query)
        ).order_by("name")
        result_counts["classes"] = class_scope.count()
        classes = list(class_scope[:10])

        academic_class_scope = get_level_academic_classes_queryset(active_level=active_level).filter(
            Q(Class__name__icontains=query)
            | Q(Class__code__icontains=query)
            | Q(section__section_name__icontains=query)
            | Q(academic_year__academic_year__icontains=query)
            | Q(term__term__icontains=query)
        ).order_by("-academic_year__academic_year", "-term__start_date", "Class__name")
        result_counts["academic_classes"] = academic_class_scope.count()
        academic_classes = list(academic_class_scope[:10])

        stream_scope = Stream.objects.filter(
            academicclassstream__academic_class_id__in=level_academic_class_ids,
            stream__icontains=query,
        ).distinct().order_by("stream")
        result_counts["streams"] = stream_scope.count()
        streams = list(stream_scope[:10])

        subject_scope = get_level_subjects_queryset(active_level=active_level).select_related("section").filter(
            Q(name__icontains=query)
            | Q(section__section_name__icontains=query)
        ).order_by("name")
        result_counts["subjects"] = subject_scope.count()
        subjects = list(subject_scope[:10])

        user_scope = User.objects.select_related("staff_account__role", "staff_account__staff").filter(
            Q(username__icontains=query)
            | Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(email__icontains=query)
            | Q(staff_account__role__name__icontains=query)
        ).distinct().order_by("username")
        result_counts["users"] = user_scope.count()
        for user_obj in user_scope[:10]:
            role_name = "Unassigned"
            try:
                role_name = user_obj.staff_account.role.name
            except Exception:
                role_name = "Unassigned"
            users.append({
                "id": user_obj.id,
                "username": user_obj.username,
                "role_name": role_name,
                "is_active": user_obj.is_active,
            })

    total_results = sum(result_counts.values())
    context = {
        "query": query,
        "has_query": has_query,
        "total_results": total_results,
        "result_counts": result_counts,
        "students": students,
        "staff_members": staff_members,
        "classes": classes,
        "streams": streams,
        "academic_classes": academic_classes,
        "subjects": subjects,
        "users": users,
    }
    return render(request, "search/global_search.html", context)


@login_required
def index_view(request):
    try:
        staff_account = request.user.staff_account
        session_role = request.session.get('active_role_name')
        if session_role:
            user_role = session_role
        else:
            user_role = staff_account.role.name
    except Exception:
        user_role = 'Support Staff'

    # Define role permissions
    head_roles = ['Head Teacher', 'Head master']
    admin_roles = ['Admin'] + head_roles
    finance_roles = ['Admin', 'Head Teacher', 'Head master', 'Bursar']
    academic_roles = ['Admin', 'Head Teacher', 'Head master', 'Director of Studies', 'Teacher', 'Class Teacher']
    teacher_roles = ['Admin', 'Head Teacher', 'Head master', 'Director of Studies', 'Teacher', 'Class Teacher']
    is_teacher_dashboard = user_role == "Teacher"
    is_class_teacher_dashboard = user_role == "Class Teacher"
    is_teacher_or_class_dashboard = user_role in ["Teacher", "Class Teacher"]
    is_head_dashboard = user_role in head_roles
    is_dos_dashboard = user_role in {"Director of Studies", "DOS"}
    is_bursar_dashboard = user_role == "Bursar"
    is_admin_dashboard = user_role in admin_roles
    can_add_student = user_role in academic_roles and user_role not in ['Teacher']

    selected_term_param = (request.GET.get("term") or "").strip()
    term_options = []
    selected_term = None
    selected_term_label = ""
    active_level = get_active_school_level(request)
    scoped_classes = get_level_classes_queryset(active_level=active_level)
    scoped_academic_classes = get_level_academic_classes_queryset(active_level=active_level)
    scoped_class_streams = get_level_class_streams_queryset(active_level=active_level)
    scoped_students = get_level_students_queryset(active_level=active_level)
    scoped_subjects = get_level_subjects_queryset(active_level=active_level)

    # Basic staff statistics (visible to all except support staff)
    if user_role not in ['Support Staff']:
        total_staff = Staff.objects.count()
        total_males = Staff.objects.filter(gender='M').count()
        total_females = Staff.objects.filter(gender='F').count()
        male_percentage = (total_males / total_staff * 100) if total_staff > 0 else 0
        female_percentage = (total_females / total_staff * 100) if total_staff > 0 else 0
    else:
        total_staff = total_males = total_females = male_percentage = female_percentage = 0

    # Basic student statistics (visible to academic and admin roles)
    if user_role in academic_roles:
        total_students = scoped_students.filter(is_active=True).count()
        total_male_students = scoped_students.filter(gender='M', is_active=True).count()
        total_female_students = scoped_students.filter(gender='F', is_active=True).count()
        male_students_percentage = (total_male_students / total_students * 100) if total_students > 0 else 0
        female_students_percentage = (total_female_students / total_students * 100) if total_students > 0 else 0
    else:
        total_students = total_male_students = total_female_students = male_students_percentage = female_students_percentage = 0

    # Academic information (visible to academic and admin roles)
    # Also get current_year and current_term for finance roles since financial calculations depend on them
    if user_role in academic_roles or user_role in finance_roles:
        current_year = get_current_academic_year()
        current_term = Term.objects.filter(is_current=True).first()
        
        # Show a user-friendly message if no academic year is set
        if current_year is None:
            messages.error(request, "No academic year has been set. Please set an academic year to view this page.")
            return _render_index_template(request, {
                'user_role': user_role,
                'is_admin': user_role in admin_roles,
                'is_finance': user_role in finance_roles,
                'is_academic': user_role in academic_roles,
                'is_teacher': user_role in teacher_roles,
                'is_support': user_role == 'Support Staff',
                'is_teacher_dashboard': is_teacher_dashboard,
                'is_class_teacher_dashboard': is_class_teacher_dashboard,
                'is_head_dashboard': is_head_dashboard,
                'is_dos_dashboard': is_dos_dashboard,
                'is_bursar_dashboard': is_bursar_dashboard,
                'is_admin_dashboard': is_admin_dashboard,
                'dashboard_chart_data': {},
            })
        term_options = list(Term.objects.filter(academic_year=current_year).order_by("term"))
        selected_term_ids = {str(term.id) for term in term_options}
        if selected_term_param in selected_term_ids:
            selected_term = next((term for term in term_options if str(term.id) == selected_term_param), None)
        elif current_term and current_term.academic_year_id == current_year.id:
            selected_term = current_term
        elif term_options:
            selected_term = term_options[0]
        else:
            selected_term = current_term

        if selected_term:
            selected_term_label = f"Term {selected_term.term} {selected_term.academic_year.academic_year}"
        current_term = selected_term
    else:
        current_year = current_term = None

    # Teacher-focused data (assigned classes/subjects + pending assessments)
    teacher_assignments = []
    teacher_subjects = []
    pending_assessments = []
    teacher_class_count = 0
    teacher_subject_count = 0
    pending_assessments_count = 0
    class_teacher_progress = []
    class_teacher_tasks = []
    class_teacher_birthdays = []
    class_streams = []
    teacher_today_timetable = []
    teacher_today_lessons_count = 0
    teacher_present_today_count = 0
    teacher_absent_today_count = 0
    teacher_total_students_count = 0
    pending_marks_entry_count = 0
    teacher_recent_student_performance = []
    teacher_risk_students = []
    class_teacher_fee_alert_count = 0
    class_teacher_fee_alert_amount = 0
    class_teacher_at_risk_count = 0
    class_teacher_recent_activity = []
    teacher_alerts = []
    class_teacher_alerts = []
    if is_teacher_or_class_dashboard:
        staff_account = StaffAccount.objects.filter(user=request.user).select_related("staff").first()
        if staff_account and staff_account.staff:
            teacher_assignments = list(
                get_teacher_assignments(
                    staff_account.staff,
                    academic_classes=scoped_academic_classes,
                )
            )
            teacher_subjects = sorted({a.subject for a in teacher_assignments}, key=lambda s: s.name)
            teacher_class_count = len({a.academic_class_stream.academic_class_id for a in teacher_assignments})
            teacher_subject_count = len(teacher_subjects)

            class_ids = []
            class_stream_ids = []
            subject_ids = [s.id for s in teacher_subjects]
            if current_year and current_term:
                if is_class_teacher_dashboard:
                    class_streams = list(
                        scoped_class_streams.filter(class_teacher=staff_account.staff)
                        .select_related("academic_class__Class", "stream")
                    )
                    class_ids = [cs.academic_class_id for cs in class_streams]
                    class_stream_ids = [cs.id for cs in class_streams]
                else:
                    class_ids = list({a.academic_class_stream.academic_class_id for a in teacher_assignments})
                    class_stream_ids = list({a.academic_class_stream_id for a in teacher_assignments})

                assessment_qs = Assessment.objects.filter(
                    academic_class__academic_year=current_year,
                    academic_class__term=current_term,
                    academic_class_id__in=class_ids,
                )
                if is_teacher_dashboard and subject_ids:
                    assessment_qs = assessment_qs.filter(subject_id__in=subject_ids)
                pending_assessments = list(
                    assessment_qs.select_related("academic_class", "assessment_type", "subject").order_by("-date")[:5]
                )
                pending_assessments_count = len(pending_assessments)
                pending_marks_entry_count = assessment_qs.filter(
                    Q(result_batch__status="DRAFT") | Q(result_batch__isnull=True)
                ).count()

                today = timezone.localdate()
                weekday_codes = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
                today_code = weekday_codes[today.weekday()]
                teacher_today_timetable = list(
                    Timetable.objects.filter(teacher=staff_account.staff, weekday=today_code)
                    .select_related(
                        "subject",
                        "time_slot",
                        "class_stream",
                        "class_stream__academic_class__Class",
                        "class_stream__stream",
                    )
                    .order_by("time_slot__start_time")
                )
                teacher_today_lessons_count = len(teacher_today_timetable)

                if class_stream_ids:
                    teacher_total_students_count = ClassRegister.objects.filter(
                        academic_class_stream_id__in=class_stream_ids
                    ).values("student_id").distinct().count()
                elif class_ids:
                    teacher_total_students_count = ClassRegister.objects.filter(
                        academic_class_stream__academic_class_id__in=class_ids
                    ).values("student_id").distinct().count()

                if class_ids:
                    today_attendance_qs = AttendanceRecord.objects.filter(
                        session__date=today,
                        session__class_stream__academic_class_id__in=class_ids,
                    )
                    teacher_present_today_count = today_attendance_qs.filter(
                        status__in=[AttendanceStatus.PRESENT, AttendanceStatus.LATE]
                    ).count()
                    teacher_absent_today_count = today_attendance_qs.filter(
                        status=AttendanceStatus.ABSENT
                    ).count()

                    class_teacher_birthdays = list(
                        scoped_students.filter(
                            is_active=True,
                            current_class_id__in=class_ids,
                            birthdate__month=today.month,
                            birthdate__day=today.day,
                        ).order_by("student_name")
                    )

                    performance_qs = Result.objects.filter(
                        assessment__academic_class__academic_year=current_year,
                        assessment__academic_class__term=current_term,
                        assessment__academic_class_id__in=class_ids,
                    )
                    if is_teacher_dashboard and subject_ids:
                        performance_qs = performance_qs.filter(assessment__subject_id__in=subject_ids)
                    performance_rows = list(
                        performance_qs.values("student_id", "student__student_name")
                        .annotate(avg_score=Avg("score"), total_results=Count("id"))
                    )
                    sorted_performance_rows = sorted(
                        performance_rows, key=lambda row: row.get("avg_score") or 0, reverse=True
                    )
                    teacher_recent_student_performance = sorted_performance_rows[:8]
                    risk_rows = [row for row in sorted_performance_rows if (row.get("avg_score") or 0) < 50]
                    teacher_risk_students = risk_rows[:8]
                    class_teacher_at_risk_count = len(risk_rows)

                if is_class_teacher_dashboard and class_streams:
                    allocations = list(
                        get_class_stream_assignments(
                            class_streams=class_streams,
                            academic_classes=scoped_academic_classes,
                            current_year=current_year,
                            current_term=current_term,
                        )
                    )
                    for allocation in allocations:
                        if not allocation.subject_teacher:
                            continue
                        academic_class = allocation.academic_class_stream.academic_class
                        assessments = Assessment.objects.filter(
                            academic_class=academic_class,
                            subject=allocation.subject,
                            academic_class__academic_year=current_year,
                            academic_class__term=current_term,
                        ).select_related("result_batch")
                        results_qs = Result.objects.filter(assessment__in=assessments)
                        total_results = results_qs.count()
                        marked_results = results_qs.filter(status__in=["PENDING", "VERIFIED"]).count()
                        progress = round((marked_results / total_results) * 100, 1) if total_results else 0
                        batch_status = (
                            assessments.filter(result_batch__isnull=False)
                            .values_list("result_batch__status", flat=True)
                            .first()
                            or "DRAFT"
                        )
                        submitted = batch_status in ["PENDING", "VERIFIED"]
                        pending_results = total_results - marked_results
                        if pending_results > 0 and batch_status == "VERIFIED":
                            batch_status = "PENDING"
                        class_teacher_progress.append({
                            "teacher": allocation.subject_teacher,
                            "subject": allocation.subject,
                            "class_name": academic_class.Class.name,
                            "stream": allocation.academic_class_stream.stream.stream,
                            "progress": progress,
                            "submitted": submitted,
                            "total": total_results,
                            "marked": marked_results,
                            "pending": pending_results,
                            "batch_status": batch_status,
                        })

                    unsubmitted_assessments = Assessment.objects.filter(
                        academic_class__academic_year=current_year,
                        academic_class__term=current_term,
                        academic_class_id__in=class_ids,
                    ).filter(Q(result_batch__status="DRAFT") | Q(result_batch__isnull=True)).count()
                    flagged_results_count = Result.objects.filter(
                        assessment__academic_class__academic_year=current_year,
                        assessment__academic_class__term=current_term,
                        assessment__academic_class_id__in=class_ids,
                        status="FLAGGED",
                    ).count()

                    class_id_for_links = class_ids[0] if class_ids else None
                    if pending_assessments_count and class_id_for_links:
                        class_teacher_tasks.append({
                            "label": f"{pending_assessments_count} assessments pending results",
                            "status": "Pending",
                            "url": reverse("list_assessments", args=[class_id_for_links]),
                        })
                    if unsubmitted_assessments and class_id_for_links:
                        class_teacher_tasks.append({
                            "label": f"{unsubmitted_assessments} assessments not submitted for verification",
                            "status": "Action",
                            "url": f"{reverse('list_assessments', args=[class_id_for_links])}?status=draft",
                        })
                    if flagged_results_count:
                        class_teacher_tasks.append({
                            "label": f"{flagged_results_count} results flagged - need correction",
                            "status": "Alert",
                            "url": reverse("class_assessment_list"),
                        })

                    class_student_ids = list(
                        ClassRegister.objects.filter(academic_class_stream_id__in=class_stream_ids)
                        .values_list("student_id", flat=True)
                        .distinct()
                    )
                    fee_alert_qs = StudentBill.objects.filter(
                        student_id__in=class_student_ids,
                        academic_class__in=scoped_academic_classes,
                        academic_class__academic_year=current_year,
                        academic_class__term=current_term,
                        status__in=["Unpaid", "Overdue"],
                    )
                    class_teacher_fee_alert_count = fee_alert_qs.count()
                    class_teacher_fee_alert_amount = fee_alert_qs.aggregate(total=Sum("items__amount"))["total"] or 0

                    class_teacher_recent_activity = list(
                        Result.objects.filter(
                            assessment__academic_class__academic_year=current_year,
                            assessment__academic_class__term=current_term,
                            assessment__academic_class_id__in=class_ids,
                        )
                        .select_related("student", "assessment__subject", "assessment__assessment_type")
                        .order_by("-assessment__date")[:8]
                    )

                if pending_marks_entry_count:
                    teacher_alerts.append({
                        "label": "Assessments with missing marks",
                        "count": pending_marks_entry_count,
                        "severity": "warning",
                    })
                if teacher_absent_today_count:
                    teacher_alerts.append({
                        "label": "Students absent today",
                        "count": teacher_absent_today_count,
                        "severity": "danger",
                    })
                if pending_assessments_count:
                    teacher_alerts.append({
                        "label": "Assessments awaiting update",
                        "count": pending_assessments_count,
                        "severity": "info",
                    })

                if is_class_teacher_dashboard:
                    if class_teacher_fee_alert_count:
                        class_teacher_alerts.append({
                            "label": "Students with unpaid/overdue bills",
                            "count": class_teacher_fee_alert_count,
                            "severity": "danger",
                        })
                    if class_teacher_at_risk_count:
                        class_teacher_alerts.append({
                            "label": "At-risk students (<50 average)",
                            "count": class_teacher_at_risk_count,
                            "severity": "warning",
                        })
                    if teacher_absent_today_count:
                        class_teacher_alerts.append({
                            "label": "Students absent today",
                            "count": teacher_absent_today_count,
                            "severity": "info",
                        })

    if user_role in academic_roles:
        # Class distribution (all academic roles)
        class_distribution = scoped_students.filter(is_active=True).values('current_class__name').annotate(
            count=Count('id')
        ).order_by('-count')[:15]
    else:
        class_distribution = []

    # Override class distribution for teacher/class teacher dashboard (assigned classes only + gender counts)
    if is_teacher_or_class_dashboard and teacher_assignments:
        teacher_class_ids = list(
            {a.academic_class_stream.academic_class.Class_id for a in teacher_assignments}
        )
        class_distribution = scoped_students.filter(
            is_active=True,
            current_class_id__in=teacher_class_ids
        ).values('current_class__name').annotate(
            count=Count('id'),
            male_count=Count('id', filter=Q(gender='M')),
            female_count=Count('id', filter=Q(gender='F'))
        ).order_by('-count')[:15]
    elif is_teacher_or_class_dashboard:
        class_distribution = []

    term_start_date = selected_term.start_date if selected_term else None
    term_end_date = selected_term.end_date if selected_term else None

    # Financial overview (visible to finance and admin roles)
    fees_collected_today = 0
    payment_method_labels = []
    payment_method_values = []
    top_debtors = []
    if user_role in finance_roles and current_year and current_term:
        total_fees_collected = Payment.objects.filter(
            bill__academic_class__in=scoped_academic_classes,
            bill__academic_class__academic_year=current_year,
            bill__academic_class__term=current_term,
            payment_date__range=(term_start_date, term_end_date),
        ).aggregate(total=Sum('amount'))['total'] or 0

        fees_collected_today = Payment.objects.filter(
            bill__academic_class__in=scoped_academic_classes,
            bill__academic_class__academic_year=current_year,
            bill__academic_class__term=current_term,
            payment_date=timezone.localdate(),
        ).aggregate(total=Sum("amount"))["total"] or 0

        total_fees_outstanding = StudentBill.objects.filter(
            academic_class__in=scoped_academic_classes,
            academic_class__academic_year=current_year,
            academic_class__term=current_term,
            status='Unpaid',
        ).aggregate(total=Sum('items__amount'))['total'] or 0

        # Budget information
        current_budget = Budget.objects.filter(
            academic_year=current_year,
            term=current_term
        ).first() if current_year and current_term else None

        budget_allocated = current_budget.budget_total if current_budget else 0

        # Calculate budget spent including VAT by summing ExpenditureItem amounts and VAT
        if current_budget:
            expenditures = Expenditure.objects.filter(
                budget_item__budget=current_budget
            ).prefetch_related('items')
            budget_spent = 0
            for exp in expenditures:
                items_total = sum(item.amount for item in exp.items.all())
                budget_spent += items_total + exp.vat
        else:
            budget_spent = 0

        payment_method_breakdown = (
            Payment.objects.filter(
                bill__academic_class__in=scoped_academic_classes,
                bill__academic_class__academic_year=current_year,
                bill__academic_class__term=current_term,
                payment_date__range=(term_start_date, term_end_date),
            )
            .values("payment_method")
            .annotate(total=Sum("amount"))
            .order_by("-total")
        )
        payment_method_labels = [row["payment_method"] for row in payment_method_breakdown]
        payment_method_values = [float(row["total"] or 0) for row in payment_method_breakdown]

        billed_by_student = (
            StudentBillItem.objects.filter(
                bill__academic_class__in=scoped_academic_classes,
                bill__academic_class__academic_year=current_year,
                bill__academic_class__term=current_term,
            )
            .values("bill__student_id", "bill__student__student_name")
            .annotate(total_billed=Sum("amount"))
        )
        paid_by_student = (
            Payment.objects.filter(
                bill__academic_class__in=scoped_academic_classes,
                bill__academic_class__academic_year=current_year,
                bill__academic_class__term=current_term,
            )
            .values("bill__student_id")
            .annotate(total_paid=Sum("amount"))
        )
        paid_map = {row["bill__student_id"]: row["total_paid"] or 0 for row in paid_by_student}
        top_debtors = []
        for row in billed_by_student:
            balance = (row["total_billed"] or 0) - (paid_map.get(row["bill__student_id"]) or 0)
            if balance > 0:
                top_debtors.append({
                    "student_id": row["bill__student_id"],
                    "student_name": row["bill__student__student_name"],
                    "balance": balance,
                })
        top_debtors = sorted(top_debtors, key=lambda item: item["balance"], reverse=True)[:6]
    else:
        total_fees_collected = total_fees_outstanding = budget_allocated = budget_spent = 0
        current_budget = None

    if user_role in finance_roles and term_start_date and term_end_date:
        recent_payments = Payment.objects.filter(
            bill__academic_class__in=scoped_academic_classes,
            payment_date__range=(term_start_date, term_end_date),
        ).select_related('bill__student').order_by('-payment_date')[:5]
        recent_expenditures = Expenditure.objects.filter(
            date_incurred__range=(term_start_date, term_end_date)
        ).order_by('-date_incurred')[:5]
        pending_approvals = ApprovalWorkflow.objects.filter(status='pending').select_related('expenditure')[:5]
    else:
        recent_payments = []
        recent_expenditures = []
        pending_approvals = []

    if user_role in academic_roles:
        recent_registrations = scoped_students.filter(
            academic_year=current_year
        ).order_by('-id')[:5] if current_year else []
    else:
        recent_registrations = []

    # Dashboard communications
    now = timezone.now()
    if user_role in {"Admin", "Head Teacher", "Head master"}:
        audience = None
    elif user_role == "Director of Studies":
        audience = ["all", "dos"]
    elif user_role == "Bursar":
        audience = ["all", "bursar"]
    elif user_role == "Class Teacher":
        audience = ["all", "class_teacher", "teachers"]
    elif user_role == "Teacher":
        audience = ["all", "teachers"]
    else:
        audience = ["all"]

    dashboard_announcements = Announcement.objects.filter(
        is_active=True,
        starts_at__lte=now,
    ).filter(Q(ends_at__isnull=True) | Q(ends_at__gte=now))
    dashboard_events = Event.objects.filter(
        is_active=True,
        start_datetime__gte=now
    ).order_by("start_datetime")

    if audience is not None:
        dashboard_announcements = dashboard_announcements.filter(audience__in=audience)
        dashboard_events = dashboard_events.filter(audience__in=audience)

    dashboard_announcements = dashboard_announcements[:5]
    dashboard_events = dashboard_events[:5]

    # Performance metrics - visible to academic and admin roles
    total_assessments = 0
    completed_assessments = 0
    if user_role in academic_roles and current_year:
        # Scope assessment metrics to the current term
        total_assessments = Assessment.objects.filter(
            academic_class__in=scoped_academic_classes,
            academic_class__academic_year=current_year,
            academic_class__term=current_term
        ).count()

        completed_assessments = Result.objects.filter(
            assessment__academic_class__in=scoped_academic_classes,
            assessment__academic_class__academic_year=current_year,
            assessment__academic_class__term=current_term
        ).values('assessment').distinct().count()

        assessment_completion_rate = (completed_assessments / total_assessments * 100) if total_assessments > 0 else 0
    else:
        assessment_completion_rate = 0

    # Quick stats for charts - only for roles that can see the data
    monthly_enrollment = [
        {'month': 1, 'count': 0},
        {'month': 2, 'count': 0},
        {'month': 3, 'count': 0},
        {'month': 4, 'count': 0},
        {'month': 5, 'count': 0},
        {'month': 6, 'count': 0},
        {'month': 7, 'count': 0},
        {'month': 8, 'count': 0},
        {'month': 9, 'count': 0},
        {'month': 10, 'count': 0},
        {'month': 11, 'count': 0},
        {'month': 12, 'count': 0}
    ]

    # Gender distribution data for charts - role-based
    if user_role not in ['Support Staff']:
        staff_gender_data = [
            {'label': 'Male Staff', 'value': total_males, 'color': '#3498db'},
            {'label': 'Female Staff', 'value': total_females, 'color': '#e74c3c'}
        ]
    else:
        staff_gender_data = []

    if user_role in academic_roles:
        student_gender_data = [
            {'label': 'Male Students', 'value': total_male_students, 'color': '#f39c12'},
            {'label': 'Female Students', 'value': total_female_students, 'color': '#9b59b6'}
        ]
    else:
        student_gender_data = []

    # Fee collection status - only for finance roles
    if user_role in finance_roles and current_year and current_term:
        paid_bills = StudentBill.objects.filter(
            academic_class__in=scoped_academic_classes,
            academic_class__academic_year=current_year,
            academic_class__term=current_term,
            status='Paid',
        ).count()

        unpaid_bills = StudentBill.objects.filter(
            academic_class__in=scoped_academic_classes,
            academic_class__academic_year=current_year,
            academic_class__term=current_term,
            status='Unpaid',
        ).count()

        overdue_bills = StudentBill.objects.filter(
            academic_class__in=scoped_academic_classes,
            academic_class__academic_year=current_year,
            academic_class__term=current_term,
            status='Overdue',
        ).count()

        total_bills = paid_bills + unpaid_bills + overdue_bills

        # Calculate fee collection rate based on amount collected vs amount billed
        total_billed = StudentBill.objects.filter(
            academic_class__in=scoped_academic_classes,
            academic_class__academic_year=current_year,
            academic_class__term=current_term,
        ).aggregate(total=Sum('items__amount'))['total'] or 0

        fee_collection_rate = (total_fees_collected / total_billed * 100) if total_billed > 0 else 0
    else:
        paid_bills = unpaid_bills = overdue_bills = total_bills = fee_collection_rate = 0

    # Calculate role-aware metrics
    if user_role in academic_roles and current_year:
        # Count only classes in the current term to avoid double-counting across terms
        active_classes = scoped_academic_classes.filter(
            academic_year=current_year,
            term=current_term
        ).count()
    else:
        active_classes = 0

    total_subjects = scoped_subjects.count() if user_role in academic_roles else 0
    pending_tasks = unpaid_bills + overdue_bills if user_role in finance_roles else 0

    # Chart data
    class_performance_labels = []
    class_performance_values = []
    class_readiness_labels = []
    class_readiness_values = []
    class_assessment_totals = []
    class_assessment_completed = []
    subject_performance_labels = []
    subject_performance_values = []
    top_classes = []
    bottom_classes = []
    top_subjects = []
    bottom_subjects = []
    performance_trend_labels = []
    performance_trend_values = []
    grade_distribution_labels = []
    grade_distribution_values = []
    grade_distribution_colors = []
    enrollment_trend_labels = []
    enrollment_trend_active_values = []
    enrollment_trend_inactive_values = []
    attendance_heatmap_series = []
    class_results_distribution_labels = []
    class_results_distribution_series = []
    fees_collection_labels = []
    fees_collection_expected = []
    fees_collection_collected = []
    fees_trend_labels = []
    fees_trend_values = []
    expenses_trend_values = []
    expenses_labels = []
    expenses_values = []
    revenue_expense_labels = []
    result_status_percent = 0

    total_results = 0
    verified_results = 0
    if user_role in academic_roles and current_year and current_term:
        analytics_cache_key = (
            f"dashboard:analytics:v2:{active_level}:{current_year.id}:{current_term.id}"
        )
        cached_analytics = cache.get(analytics_cache_key)
        if cached_analytics:
            class_performance_labels = cached_analytics["class_performance_labels"]
            class_performance_values = cached_analytics["class_performance_values"]
            class_readiness_labels = cached_analytics["class_readiness_labels"]
            class_readiness_values = cached_analytics["class_readiness_values"]
            class_assessment_totals = cached_analytics["class_assessment_totals"]
            class_assessment_completed = cached_analytics["class_assessment_completed"]
            subject_performance_labels = cached_analytics["subject_performance_labels"]
            subject_performance_values = cached_analytics["subject_performance_values"]
            top_classes = cached_analytics["top_classes"]
            bottom_classes = cached_analytics["bottom_classes"]
            top_subjects = cached_analytics["top_subjects"]
            bottom_subjects = cached_analytics["bottom_subjects"]
            performance_trend_labels = cached_analytics["performance_trend_labels"]
            performance_trend_values = cached_analytics["performance_trend_values"]
            grade_distribution_labels = cached_analytics["grade_distribution_labels"]
            grade_distribution_values = cached_analytics["grade_distribution_values"]
            grade_distribution_colors = cached_analytics["grade_distribution_colors"]
            enrollment_trend_labels = cached_analytics["enrollment_trend_labels"]
            enrollment_trend_active_values = cached_analytics["enrollment_trend_active_values"]
            enrollment_trend_inactive_values = cached_analytics["enrollment_trend_inactive_values"]
            attendance_heatmap_series = cached_analytics["attendance_heatmap_series"]
            class_results_distribution_labels = cached_analytics["class_results_distribution_labels"]
            class_results_distribution_series = cached_analytics["class_results_distribution_series"]
            total_results = cached_analytics["total_results"]
            verified_results = cached_analytics["verified_results"]
            result_status_percent = cached_analytics["result_status_percent"]
        else:
            term_academic_classes = list(
                scoped_academic_classes.filter(
                    academic_year=current_year,
                    term=current_term,
                ).select_related("Class")
            )
            for academic_class in term_academic_classes:
                total_class_assessments = Assessment.objects.filter(academic_class=academic_class).count()
                completed_class_assessments = (
                    Result.objects.filter(assessment__academic_class=academic_class)
                    .values("assessment")
                    .distinct()
                    .count()
                )
                readiness_percent = round(
                    (completed_class_assessments / total_class_assessments) * 100, 1
                ) if total_class_assessments else 0
                class_readiness_labels.append(academic_class.Class.name)
                class_readiness_values.append(readiness_percent)
                class_assessment_totals.append(total_class_assessments)
                class_assessment_completed.append(completed_class_assessments)

            class_perf = (
                Result.objects.filter(
                    assessment__academic_class__in=scoped_academic_classes,
                    assessment__academic_class__academic_year=current_year,
                    assessment__academic_class__term=current_term,
                )
                .values("assessment__academic_class__Class__name")
                .annotate(avg_score=Avg("score"))
                .order_by("assessment__academic_class__Class__name")
            )
            class_perf_list = list(class_perf)
            class_performance_labels = [c["assessment__academic_class__Class__name"] for c in class_perf_list]
            class_performance_values = [round(c["avg_score"] or 0, 1) for c in class_perf_list]
            class_perf_sorted = sorted(class_perf_list, key=lambda x: (x["avg_score"] or 0), reverse=True)
            top_classes = class_perf_sorted[:5]
            bottom_classes = list(reversed(class_perf_sorted[-5:])) if class_perf_sorted else []

            subject_perf = (
                Result.objects.filter(
                    assessment__academic_class__in=scoped_academic_classes,
                    assessment__academic_class__academic_year=current_year,
                    assessment__academic_class__term=current_term,
                )
                .values("assessment__subject__name")
                .annotate(avg_score=Avg("score"))
                .order_by("assessment__subject__name")
            )
            subject_perf_list = list(subject_perf)
            subject_performance_labels = [s["assessment__subject__name"] for s in subject_perf_list]
            subject_performance_values = [round(s["avg_score"] or 0, 1) for s in subject_perf_list]
            subject_perf_sorted = sorted(subject_perf_list, key=lambda x: (x["avg_score"] or 0), reverse=True)
            top_subjects = subject_perf_sorted[:5]
            bottom_subjects = list(reversed(subject_perf_sorted[-5:])) if subject_perf_sorted else []

            trend_perf = (
                Result.objects.filter(
                    assessment__academic_class__in=scoped_academic_classes,
                    assessment__academic_class__academic_year=current_year,
                )
                .values("assessment__academic_class__term__term")
                .annotate(avg_score=Avg("score"))
                .order_by("assessment__academic_class__term__term")
            )
            performance_trend_labels = [t["assessment__academic_class__term__term"] for t in trend_perf]
            performance_trend_values = [round(t["avg_score"] or 0, 1) for t in trend_perf]

            grading = list(GradingSystem.objects.all().order_by("min_score"))
            grade_distribution_labels = [g.grade for g in grading]
            if not grade_distribution_labels:
                grade_distribution_labels = ["Ungraded"]
            grade_counts = {grade: 0 for grade in grade_distribution_labels}
            for row in Result.objects.filter(assessment__academic_class__academic_year=current_year,
                                             assessment__academic_class__term=current_term,
                                             assessment__academic_class__in=scoped_academic_classes).values("score"):
                score = row["score"]
                grade = None
                for g in grading:
                    if g.min_score <= score <= g.max_score:
                        grade = g.grade
                        break
                if grade is None:
                    grade = "Ungraded"
                if grade not in grade_counts:
                    grade_counts[grade] = 0
                    grade_distribution_labels.append(grade)
                grade_counts[grade] += 1
            grade_distribution_values = [grade_counts.get(k, 0) for k in grade_distribution_labels]
            color_palette = ["#d9534f", "#f0ad4e", "#ffd45a", "#5cb85c", "#337ab7", "#6f42c1", "#d63384", "#8b5a2b", "#2c3e50"]
            grade_distribution_colors = [color_palette[i % len(color_palette)] for i in range(len(grade_distribution_labels))]

            enrollment_stats = (
                scoped_students.filter(academic_year=current_year)
                .values("term__term")
                .annotate(
                    active_count=Count("id", filter=Q(is_active=True)),
                    inactive_count=Count("id", filter=Q(is_active=False)),
                )
                .order_by("term__term")
            )
            enrollment_trend_labels = [f"Term {row['term__term']}" for row in enrollment_stats]
            enrollment_trend_active_values = [row["active_count"] for row in enrollment_stats]
            enrollment_trend_inactive_values = [row["inactive_count"] for row in enrollment_stats]

            attendance_daily = (
                AttendanceRecord.objects.filter(
                    session__academic_year=current_year,
                    session__term=current_term,
                    session__class_stream__academic_class__in=scoped_academic_classes,
                )
                .values("session__date")
                .annotate(
                    total=Count("id"),
                    present_like=Count("id", filter=Q(status__in=[AttendanceStatus.PRESENT, AttendanceStatus.LATE])),
                )
                .order_by("session__date")
            )
            heatmap_points = []
            for row in attendance_daily:
                total = row["total"] or 0
                present_like = row["present_like"] or 0
                rate = round((present_like / total) * 100, 1) if total else 0
                heatmap_points.append({
                    "x": row["session__date"].strftime("%b %d"),
                    "y": rate,
                })
            attendance_heatmap_series = [{"name": "Attendance %", "data": heatmap_points}]

            class_names = []
            class_grade_totals = {}
            grade_order = list(grade_distribution_labels)
            result_rows = Result.objects.filter(
                assessment__academic_class__in=scoped_academic_classes,
                assessment__academic_class__academic_year=current_year,
                assessment__academic_class__term=current_term,
            ).values("assessment__academic_class__Class__name", "score")
            for row in result_rows:
                class_name = row["assessment__academic_class__Class__name"] or "Unknown"
                if class_name not in class_grade_totals:
                    class_grade_totals[class_name] = {grade: 0 for grade in grade_order}
                    class_names.append(class_name)
                score = row["score"]
                assigned_grade = "Ungraded"
                for g in grading:
                    if g.min_score <= score <= g.max_score:
                        assigned_grade = g.grade
                        break
                if assigned_grade not in class_grade_totals[class_name]:
                    class_grade_totals[class_name][assigned_grade] = 0
                    if assigned_grade not in grade_order:
                        grade_order.append(assigned_grade)
                class_grade_totals[class_name][assigned_grade] += 1

            class_results_distribution_labels = class_names
            class_results_distribution_series = [
                {
                    "name": grade,
                    "data": [class_grade_totals[class_name].get(grade, 0) for class_name in class_names],
                }
                for grade in grade_order
            ]

            total_results = Result.objects.filter(
                assessment__academic_class__in=scoped_academic_classes,
                assessment__academic_class__academic_year=current_year,
                assessment__academic_class__term=current_term,
            ).count()
            verified_results = Result.objects.filter(
                assessment__academic_class__in=scoped_academic_classes,
                assessment__academic_class__academic_year=current_year,
                assessment__academic_class__term=current_term,
                status="VERIFIED",
            ).count()
            result_status_percent = round((verified_results / total_results) * 100, 1) if total_results else 0

            cache.set(analytics_cache_key, {
                "class_performance_labels": class_performance_labels,
                "class_performance_values": class_performance_values,
                "class_readiness_labels": class_readiness_labels,
                "class_readiness_values": class_readiness_values,
                "class_assessment_totals": class_assessment_totals,
                "class_assessment_completed": class_assessment_completed,
                "subject_performance_labels": subject_performance_labels,
                "subject_performance_values": subject_performance_values,
                "top_classes": top_classes,
                "bottom_classes": bottom_classes,
                "top_subjects": top_subjects,
                "bottom_subjects": bottom_subjects,
                "performance_trend_labels": performance_trend_labels,
                "performance_trend_values": performance_trend_values,
                "grade_distribution_labels": grade_distribution_labels,
                "grade_distribution_values": grade_distribution_values,
                "grade_distribution_colors": grade_distribution_colors,
                "enrollment_trend_labels": enrollment_trend_labels,
                "enrollment_trend_active_values": enrollment_trend_active_values,
                "enrollment_trend_inactive_values": enrollment_trend_inactive_values,
                "attendance_heatmap_series": attendance_heatmap_series,
                "class_results_distribution_labels": class_results_distribution_labels,
                "class_results_distribution_series": class_results_distribution_series,
                "total_results": total_results,
                "verified_results": verified_results,
                "result_status_percent": result_status_percent,
            }, 300)

    # Action queue for admin/head roles
    action_queue = []
    if user_role in admin_roles:
        classes_without_streams = 0
        if current_year and current_term:
            classes_without_streams = scoped_academic_classes.filter(
                academic_year=current_year,
                term=current_term,
            ).annotate(stream_count=Count("class_streams")).filter(stream_count=0).count()

        pending_results_count = max(total_assessments - completed_assessments, 0)
        unverified_results_count = max(total_results - verified_results, 0)

        action_queue = [
            {
                "label": "Academic classes missing streams",
                "count": classes_without_streams,
                "severity": "high" if classes_without_streams else "ok",
                "url": reverse("academic_class_page"),
            },
            {
                "label": "Assessments pending results",
                "count": pending_results_count,
                "severity": "medium" if pending_results_count else "ok",
                "url": reverse("class_assessment_list"),
            },
            {
                "label": "Unverified results",
                "count": unverified_results_count,
                "severity": "medium" if unverified_results_count else "ok",
                "url": reverse("verification_overview"),
            },
            {
                "label": "Overdue fee bills",
                "count": overdue_bills if user_role in finance_roles else 0,
                "severity": "high" if (overdue_bills if user_role in finance_roles else 0) else "ok",
                "url": reverse("fees_status"),
            },
        ]
        action_queue = [item for item in action_queue if item["count"] > 0]
    action_queue_total = sum(item["count"] for item in action_queue)

    if user_role in finance_roles and current_year and current_term and term_start_date and term_end_date:
        expected_fees = StudentBill.objects.filter(
            academic_class__in=scoped_academic_classes,
            academic_class__academic_year=current_year,
            academic_class__term=current_term,
        ).aggregate(total=Sum("items__amount"))["total"] or 0
        collected_fees = total_fees_collected
        fees_collection_labels = [selected_term_label]
        fees_collection_expected = [float(expected_fees)]
        fees_collection_collected = [float(collected_fees)]

        daily_collections = (
            Payment.objects.filter(
                bill__academic_class__in=scoped_academic_classes,
                bill__academic_class__academic_year=current_year,
                bill__academic_class__term=current_term,
                payment_date__range=(term_start_date, term_end_date),
            )
            .annotate(bucket=TruncMonth("payment_date"))
            .values("bucket")
            .annotate(total=Sum("amount"))
            .order_by("bucket")
        )
        collections_by_month = {
            date(item["bucket"].year, item["bucket"].month, 1): float(item["total"] or 0)
            for item in daily_collections if item["bucket"]
        }
        term_expenditures = list(
            Expenditure.objects.filter(
                date_incurred__range=(term_start_date, term_end_date)
            ).prefetch_related("items")
        )
        expenses_by_month = {}
        for expenditure in term_expenditures:
            bucket = date(expenditure.date_incurred.year, expenditure.date_incurred.month, 1)
            expenses_by_month[bucket] = expenses_by_month.get(bucket, 0) + float(expenditure.amount or 0)

        month_cursor = date(term_start_date.year, term_start_date.month, 1)
        month_end = date(term_end_date.year, term_end_date.month, 1)
        while month_cursor <= month_end:
            fees_trend_labels.append(month_cursor.strftime("%b"))
            fees_trend_values.append(collections_by_month.get(month_cursor, 0))
            expenses_trend_values.append(expenses_by_month.get(month_cursor, 0))
            if month_cursor.month == 12:
                month_cursor = date(month_cursor.year + 1, 1, 1)
            else:
                month_cursor = date(month_cursor.year, month_cursor.month + 1, 1)

        revenue_expense_labels = list(fees_trend_labels)

        expense_breakdown = (
            ExpenditureItem.objects.filter(
                expenditure__date_incurred__range=(term_start_date, term_end_date),
            ).values("item_name")
            .annotate(total=Sum(ExpressionWrapper(F("quantity") * F("unit_cost"), output_field=DecimalField())))
            .order_by("-total")[:5]
        )
        expenses_labels = [e["item_name"] for e in expense_breakdown]
        expenses_values = [float(e["total"] or 0) for e in expense_breakdown]

    total_teachers = Staff.objects.filter(
        Q(roles__name__in=["Teacher", "Class Teacher"]) | Q(is_academic_staff=True)
    ).distinct().count()
    active_users_count = User.objects.filter(is_active=True).count()
    total_roles_count = Role.objects.count()
    recent_activity_scope = (
        AuditLog.objects.select_related("user", "content_type")
        .filter(
            Q(action__in=[AuditLog.ACTION_LOGIN, AuditLog.ACTION_LOGOUT])
            | (
                Q(action__in=[AuditLog.ACTION_CREATE, AuditLog.ACTION_UPDATE, AuditLog.ACTION_DELETE])
                & Q(content_type__app_label__in=["app", "secondary"])
            )
        )
        .exclude(content_type__app_label__in=["sessions", "admin", "contenttypes"])
        .exclude(content_type__model__in=["session", "logentry"])
        .order_by("-timestamp")[:20]
    )
    recent_activity_logs = []
    for log in recent_activity_scope:
        username = (log.username or (log.user.username if log.user_id else "")).strip() or "System"
        recent_activity_logs.append({
            "timestamp": log.timestamp,
            "username": username,
            "action": log.get_action_display(),
            "target": _audit_target_label(log),
            "details": _audit_change_summary(log),
        })
        if len(recent_activity_logs) >= 8:
            break
    verification_pending_count = 0
    verification_flagged_count = 0
    admin_verification_queue = []
    if current_year and current_term:
        verification_pending_count = ResultBatch.objects.filter(
            status="PENDING",
            assessment__academic_class__in=scoped_academic_classes,
            assessment__academic_class__academic_year=current_year,
            assessment__academic_class__term=current_term,
        ).count()
        verification_flagged_count = ResultBatch.objects.filter(
            status="FLAGGED",
            assessment__academic_class__in=scoped_academic_classes,
            assessment__academic_class__academic_year=current_year,
            assessment__academic_class__term=current_term,
        ).count()
        admin_verification_queue = list(
            ResultBatch.objects.filter(
                status__in=["PENDING", "FLAGGED"],
                assessment__academic_class__in=scoped_academic_classes,
                assessment__academic_class__academic_year=current_year,
                assessment__academic_class__term=current_term,
            )
            .select_related("assessment__academic_class__Class", "assessment__subject", "submitted_by")
            .order_by("-submitted_at")[:6]
        )
    admin_system_alerts = list(action_queue)
    if verification_pending_count:
        admin_system_alerts.append({
            "label": "Verification queue pending",
            "count": verification_pending_count,
            "severity": "medium",
            "url": reverse("verification_overview"),
        })
    if verification_flagged_count:
        admin_system_alerts.append({
            "label": "Flagged result batches",
            "count": verification_flagged_count,
            "severity": "high",
            "url": reverse("verification_overview"),
        })
    license_status = "Active"

    dos_pending_verification_count = verification_pending_count
    dos_missing_assessments_count = 0
    dos_flagged_results_count = 0
    dos_verification_queue = []
    dos_recent_corrections = []
    dos_alerts = []
    if current_year and current_term:
        dos_missing_assessments_count = Assessment.objects.filter(
            academic_class__in=scoped_academic_classes,
            academic_class__academic_year=current_year,
            academic_class__term=current_term,
        ).filter(Q(result_batch__isnull=True) | Q(result_batch__status="DRAFT")).count()
        dos_flagged_results_count = Result.objects.filter(
            assessment__academic_class__in=scoped_academic_classes,
            assessment__academic_class__academic_year=current_year,
            assessment__academic_class__term=current_term,
            status="FLAGGED",
        ).count()
        dos_verification_queue = list(
            ResultBatch.objects.filter(
                status="PENDING",
                assessment__academic_class__in=scoped_academic_classes,
                assessment__academic_class__academic_year=current_year,
                assessment__academic_class__term=current_term,
            )
            .select_related("assessment__academic_class__Class", "assessment__subject", "submitted_by")
            .order_by("-submitted_at")[:8]
        )
        dos_recent_corrections = list(
            VerificationCorrectionLog.objects.filter(
                batch__assessment__academic_class__in=scoped_academic_classes,
                batch__assessment__academic_class__academic_year=current_year,
                batch__assessment__academic_class__term=current_term,
            )
            .select_related("result__student", "batch__assessment__subject", "corrected_by")
            .order_by("-corrected_at")[:6]
        )
    if dos_pending_verification_count:
        dos_alerts.append({
            "label": "Pending verification queue",
            "count": dos_pending_verification_count,
            "severity": "danger",
        })
    if dos_missing_assessments_count:
        dos_alerts.append({
            "label": "Assessments missing submissions",
            "count": dos_missing_assessments_count,
            "severity": "warning",
        })
    if dos_flagged_results_count:
        dos_alerts.append({
            "label": "Flagged result records",
            "count": dos_flagged_results_count,
            "severity": "info",
        })

    student_attendance_rate = 0
    staff_attendance_rate = 0
    teacher_submission_rows = []
    head_alerts = []
    if current_year and current_term:
        attendance_scope = AttendanceRecord.objects.filter(
            session__academic_year=current_year,
            session__term=current_term,
            session__class_stream__academic_class__in=scoped_academic_classes,
        )
        attendance_total = attendance_scope.count()
        attendance_present = attendance_scope.filter(
            status__in=[AttendanceStatus.PRESENT, AttendanceStatus.LATE]
        ).count()
        student_attendance_rate = round((attendance_present / attendance_total) * 100, 1) if attendance_total else 0
        active_teachers_on_attendance = attendance_scope.values("session__teacher_id").distinct().count()
        staff_attendance_rate = round((active_teachers_on_attendance / total_teachers) * 100, 1) if total_teachers else 0
        teacher_submission_rows = list(
            ResultBatch.objects.filter(
                assessment__academic_class__in=scoped_academic_classes,
                assessment__academic_class__academic_year=current_year,
                assessment__academic_class__term=current_term,
                submitted_by__isnull=False,
            )
            .values(
                "submitted_by__id",
                "submitted_by__first_name",
                "submitted_by__last_name",
                "submitted_by__username",
            )
            .annotate(
                submitted=Count("id"),
                verified=Count("id", filter=Q(status="VERIFIED")),
                pending=Count("id", filter=Q(status="PENDING")),
            )
            .order_by("-submitted")[:8]
        )
    if student_attendance_rate and student_attendance_rate < 85:
        head_alerts.append({
            "label": "Student attendance below target",
            "count": student_attendance_rate,
            "severity": "warning",
        })
    if dos_pending_verification_count:
        head_alerts.append({
            "label": "Verification queue waiting",
            "count": dos_pending_verification_count,
            "severity": "danger",
        })
    if overdue_bills:
        head_alerts.append({
            "label": "Overdue fee bills",
            "count": overdue_bills,
            "severity": "warning",
        })

    bursar_alerts = []
    if overdue_bills:
        bursar_alerts.append({
            "label": "Overdue fee bills",
            "count": overdue_bills,
            "severity": "danger",
        })
    if top_debtors:
        bursar_alerts.append({
            "label": "Students with outstanding balances",
            "count": len(top_debtors),
            "severity": "warning",
        })
    if pending_approvals:
        bursar_alerts.append({
            "label": "Pending finance approvals",
            "count": len(pending_approvals),
            "severity": "info",
        })

    quick_actions = []
    if is_admin_dashboard:
        quick_actions = [
            {"label": "Add Student", "icon": "fa-user-plus", "url": reverse("add_student"), "style": "primary"},
            {"label": "Add Class", "icon": "fa-university", "url": reverse("class_page"), "style": "info"},
            {"label": "Add Stream", "icon": "fa-sitemap", "url": reverse("stream_page"), "style": "info"},
            {"label": "Create Exam", "icon": "fa-calendar", "url": reverse("assessment_create"), "style": "warning"},
            {"label": "Record Payment", "icon": "fa-money", "url": reverse("student_bill_page"), "style": "primary"},
            {"label": "Assign Teacher", "icon": "fa-random", "url": reverse("subject_allocation_page"), "style": "warning"},
            {"label": "Import CSV", "icon": "fa-upload", "url": reverse("bulk_register_students"), "style": "info"},
            {"label": "Users & Roles", "icon": "fa-users", "url": reverse("user_list"), "style": "primary"},
        ]
    elif is_head_dashboard:
        quick_actions = [
            {"label": "School Performance", "icon": "fa-chart-line", "url": reverse("school_results_dashboard"), "style": "primary"},
            {"label": "Attendance Overview", "icon": "fa-calendar-check-o", "url": reverse("attendance_dashboard"), "style": "info"},
            {"label": "Announcements", "icon": "fa-bullhorn", "url": reverse("announcement_list"), "style": "warning"},
        ]
    elif is_dos_dashboard:
        quick_actions = [
            {"label": "Verification Queue", "icon": "fa-check-square-o", "url": reverse("verification_overview"), "style": "danger"},
            {"label": "Enter Results", "icon": "fa-edit", "url": reverse("add_results_page"), "style": "primary"},
            {"label": "Exam Management", "icon": "fa-calendar", "url": reverse("assessment_create"), "style": "info"},
        ]
    elif is_bursar_dashboard:
        quick_actions = [
            {"label": "Record Payment", "icon": "fa-money", "url": reverse("student_bill_page"), "style": "primary"},
            {"label": "Outstanding Balances", "icon": "fa-exclamation-circle", "url": reverse("fees_status"), "style": "warning"},
            {"label": "Financial Reports", "icon": "fa-file-text-o", "url": reverse("financial_summary_report"), "style": "info"},
        ]
    elif is_class_teacher_dashboard:
        quick_actions = [
            {"label": "My Class", "icon": "fa-users", "url": reverse("academic_class_page"), "style": "primary"},
            {"label": "Report Cards", "icon": "fa-file-text", "url": reverse("class_bulk_reports"), "style": "info"},
            {"label": "At-Risk Students", "icon": "fa-flag", "url": reverse("class_stream_filter"), "style": "warning"},
        ]
    elif is_teacher_dashboard:
        quick_actions = [
            {"label": "Enter Marks", "icon": "fa-edit", "url": reverse("add_results_page"), "style": "primary"},
            {"label": "Attendance", "icon": "fa-calendar-check-o", "url": reverse("take_attendance"), "style": "info"},
            {"label": "Student Performance", "icon": "fa-line-chart", "url": reverse("class_stream_filter"), "style": "warning"},
        ]

    context = {
        # User role for template conditionals
        'user_role': user_role,
        'is_admin': user_role in admin_roles,
        'is_finance': user_role in finance_roles,
        'is_academic': user_role in academic_roles,
        'is_teacher': user_role in teacher_roles,
        'is_support': user_role == 'Support Staff',
        'is_teacher_dashboard': is_teacher_dashboard,
        'is_class_teacher_dashboard': is_class_teacher_dashboard,
        'is_head_dashboard': is_head_dashboard,
        'is_dos_dashboard': is_dos_dashboard,
        'is_bursar_dashboard': is_bursar_dashboard,
        'is_admin_dashboard': is_admin_dashboard,
        'can_add_student': can_add_student,
        'recent_expenditures': recent_expenditures,
        'pending_approvals': pending_approvals,
        'dashboard_announcements': dashboard_announcements,
        'dashboard_events': dashboard_events,

        # Basic statistics
        'total_staff': total_staff,
        'total_males': total_males,
        'total_females': total_females,
        'total_students': total_students,
        'total_male_students': total_male_students,
        'total_female_students': total_female_students,
        'male_percentage': round(male_percentage, 2),
        'female_percentage': round(female_percentage, 2),
        'male_students_percentage': round(male_students_percentage, 2),
        'female_students_percentage': round(female_students_percentage, 2),

        # Academic information
        'current_year': current_year,
        'current_term': current_term,
        'class_distribution': class_distribution,

        # Teacher dashboard data
        'teacher_assignments': teacher_assignments,
        'teacher_subjects': teacher_subjects,
        'teacher_class_count': teacher_class_count,
        'teacher_subject_count': teacher_subject_count,
        'pending_assessments': pending_assessments,
        'pending_assessments_count': pending_assessments_count,
        'pending_marks_entry_count': pending_marks_entry_count,
        'teacher_today_timetable': teacher_today_timetable,
        'teacher_today_lessons_count': teacher_today_lessons_count,
        'teacher_present_today_count': teacher_present_today_count,
        'teacher_absent_today_count': teacher_absent_today_count,
        'teacher_total_students_count': teacher_total_students_count,
        'teacher_recent_student_performance': teacher_recent_student_performance,
        'teacher_risk_students': teacher_risk_students,
        'teacher_alerts': teacher_alerts,
        'class_teacher_progress': class_teacher_progress,
        'class_teacher_tasks': class_teacher_tasks,
        'class_teacher_birthdays': class_teacher_birthdays,
        'class_streams': class_streams,
        'class_teacher_fee_alert_count': class_teacher_fee_alert_count,
        'class_teacher_fee_alert_amount': class_teacher_fee_alert_amount,
        'class_teacher_at_risk_count': class_teacher_at_risk_count,
        'class_teacher_recent_activity': class_teacher_recent_activity,
        'class_teacher_alerts': class_teacher_alerts,

        # Financial data
        'total_fees_collected': total_fees_collected,
        'fees_collected_today': fees_collected_today,
        'total_fees_outstanding': total_fees_outstanding,
        'budget_allocated': budget_allocated,
        'budget_spent': budget_spent,
        'budget_remaining': budget_allocated - budget_spent,
        'top_debtors': top_debtors,
        'selected_term': str(current_term.id) if current_term else "",
        'selected_term_label': selected_term_label,
        'term_options': term_options,

        # Recent activities
        'recent_payments': recent_payments,
        'recent_registrations': recent_registrations,
        'recent_activity_logs': recent_activity_logs,

        # Performance metrics
        'assessment_completion_rate': round(assessment_completion_rate, 1),
        'fee_collection_rate': round(fee_collection_rate, 1),
        'student_attendance_rate': student_attendance_rate,
        'staff_attendance_rate': staff_attendance_rate,

        # Chart data
        'staff_gender_data': staff_gender_data,
        'student_gender_data': student_gender_data,
        'monthly_enrollment': list(monthly_enrollment),

        # Additional metrics
        'paid_bills': paid_bills,
        'unpaid_bills': unpaid_bills,
        'overdue_bills': overdue_bills,
        'total_bills': total_bills,

        # Charts
        'class_performance_labels': class_performance_labels,
        'class_performance_values': class_performance_values,
        'class_readiness_labels': class_readiness_labels,
        'class_readiness_values': class_readiness_values,
        'class_assessment_totals': class_assessment_totals,
        'class_assessment_completed': class_assessment_completed,
        'subject_performance_labels': subject_performance_labels,
        'subject_performance_values': subject_performance_values,
        'top_classes': top_classes,
        'bottom_classes': bottom_classes,
        'top_subjects': top_subjects,
        'bottom_subjects': bottom_subjects,
        'performance_trend_labels': performance_trend_labels,
        'performance_trend_values': performance_trend_values,
        'grade_distribution_labels': grade_distribution_labels,
        'grade_distribution_values': grade_distribution_values,
        'grade_distribution_colors': grade_distribution_colors,
        'enrollment_trend_labels': enrollment_trend_labels,
        'enrollment_trend_active_values': enrollment_trend_active_values,
        'enrollment_trend_inactive_values': enrollment_trend_inactive_values,
        'attendance_heatmap_series': attendance_heatmap_series,
        'class_results_distribution_labels': class_results_distribution_labels,
        'class_results_distribution_series': class_results_distribution_series,
        'fees_collection_labels': fees_collection_labels,
        'fees_collection_expected': fees_collection_expected,
        'fees_collection_collected': fees_collection_collected,
        'fees_trend_labels': fees_trend_labels,
        'fees_trend_values': fees_trend_values,
        'expenses_trend_values': expenses_trend_values,
        'revenue_expense_labels': revenue_expense_labels,
        'payment_method_labels': payment_method_labels,
        'payment_method_values': payment_method_values,
        'expenses_labels': expenses_labels,
        'expenses_values': expenses_values,
        'result_status_percent': result_status_percent,
        'dashboard_chart_data': {
            'class_performance_labels': class_performance_labels,
            'class_performance_values': class_performance_values,
            'class_readiness_labels': class_readiness_labels,
            'class_readiness_values': class_readiness_values,
            'class_assessment_totals': class_assessment_totals,
            'class_assessment_completed': class_assessment_completed,
            'subject_performance_labels': subject_performance_labels,
            'subject_performance_values': subject_performance_values,
            'top_classes': top_classes,
            'bottom_classes': bottom_classes,
            'top_subjects': top_subjects,
            'bottom_subjects': bottom_subjects,
            'performance_trend_labels': performance_trend_labels,
            'performance_trend_values': performance_trend_values,
            'grade_distribution_labels': grade_distribution_labels,
            'grade_distribution_values': grade_distribution_values,
            'grade_distribution_colors': grade_distribution_colors,
            'enrollment_trend_labels': enrollment_trend_labels,
            'enrollment_trend_active_values': enrollment_trend_active_values,
            'enrollment_trend_inactive_values': enrollment_trend_inactive_values,
            'attendance_heatmap_series': attendance_heatmap_series,
            'class_results_distribution_labels': class_results_distribution_labels,
            'class_results_distribution_series': class_results_distribution_series,
            'fees_collection_labels': fees_collection_labels,
            'fees_collection_expected': fees_collection_expected,
            'fees_collection_collected': fees_collection_collected,
            'fees_trend_labels': fees_trend_labels,
            'fees_trend_values': fees_trend_values,
            'expenses_trend_values': expenses_trend_values,
            'revenue_expense_labels': revenue_expense_labels,
            'payment_method_labels': payment_method_labels,
            'payment_method_values': payment_method_values,
            'expenses_labels': expenses_labels,
            'expenses_values': expenses_values,
            'result_status_percent': result_status_percent,
        },

        # Quick actions data
        'pending_tasks': pending_tasks,
        'quick_actions': quick_actions,
        'active_classes': active_classes,
        'total_subjects': total_subjects,
        'total_teachers': total_teachers,
        'active_users_count': active_users_count,
        'total_roles_count': total_roles_count,
        'verification_pending_count': verification_pending_count,
        'verification_flagged_count': verification_flagged_count,
        'admin_verification_queue': admin_verification_queue,
        'admin_system_alerts': admin_system_alerts,
        'license_status': license_status,
        'head_alerts': head_alerts,
        'teacher_submission_rows': teacher_submission_rows,
        'dos_pending_verification_count': dos_pending_verification_count,
        'dos_missing_assessments_count': dos_missing_assessments_count,
        'dos_flagged_results_count': dos_flagged_results_count,
        'dos_verification_queue': dos_verification_queue,
        'dos_recent_corrections': dos_recent_corrections,
        'dos_alerts': dos_alerts,
        'bursar_alerts': bursar_alerts,
        'action_queue': action_queue,
        'action_queue_total': action_queue_total,
        'has_performance_data': bool(top_classes or bottom_classes or top_subjects or bottom_subjects),
        'has_class_readiness_data': bool(class_readiness_labels),
        'has_enrollment_trend_data': bool(enrollment_trend_labels),
        'has_attendance_heatmap_data': bool(attendance_heatmap_series and attendance_heatmap_series[0].get("data")),
        'has_class_results_distribution_data': bool(class_results_distribution_labels and class_results_distribution_series),
        'has_finance_chart_data': bool(
            fees_collection_expected
            or fees_trend_values
            or expenses_values
            or payment_method_values
            or expenses_trend_values
        ),
    }

    return _render_index_template(request, context)
