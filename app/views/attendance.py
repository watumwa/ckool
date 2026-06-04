import csv
import json
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from app.forms.attendance import (
    AttendanceHistoryFilterForm,
    AttendancePolicyForm,
    AttendanceSessionForm,
)
from app.models.attendance import (
    AttendanceAuditLog,
    AttendancePolicy,
    AttendanceRecord,
    AttendanceSession,
    AttendanceStatus,
)
from app.models.classes import AcademicClassStream
from app.models.school_settings import AcademicYear
from app.models.students import ClassRegister, Student
from app.models.subjects import Subject
from app.models.timetables import Timetable
from app.services.attendance import (
    get_or_create_session,
    initialize_session_records,
    lock_session,
    save_attendance_records,
    unlock_session,
)
from app.services.teacher_assignments import get_teacher_assignments

WEEKDAY_CODES = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]


def _weekday_code(for_date):
    return WEEKDAY_CODES[for_date.weekday()]


def _get_staff(request):
    staff_account = getattr(request.user, "staff_account", None)
    return getattr(staff_account, "staff", None)


def _is_admin_user(request):
    if request.user.is_superuser:
        return True
    role_name = ""
    try:
        role_name = (request.user.staff_account.role.name or "").strip().lower()
    except Exception:
        role_name = ""
    active_role = (request.session.get("active_role_name") or "").strip().lower()
    effective = active_role or role_name
    return effective in {"admin", "director of studies", "dos"}


def _teacher_assignments(staff):
    return get_teacher_assignments(staff)


def _teacher_lesson_queryset(staff, *, weekday_code=None):
    timetable_filter = Q(teacher=staff) | Q(allocation__subject_teacher=staff)
    if weekday_code:
        timetable_filter &= Q(weekday=weekday_code)

    entries = Timetable.objects.filter(timetable_filter).select_related(
        "class_stream",
        "class_stream__academic_class",
        "class_stream__stream",
        "subject",
        "time_slot",
        "classroom",
    )

    if entries.exists():
        return entries

    assignment_pairs = {
        (row.academic_class_stream_id, row.subject_id)
        for row in _teacher_assignments(staff)
    }
    if not assignment_pairs:
        return Timetable.objects.none()

    inferred_filter = Q()
    for class_stream_id, subject_id in assignment_pairs:
        inferred_filter |= Q(class_stream_id=class_stream_id, subject_id=subject_id)
    if weekday_code:
        inferred_filter &= Q(weekday=weekday_code)

    return Timetable.objects.filter(inferred_filter).select_related(
        "class_stream",
        "class_stream__academic_class",
        "class_stream__stream",
        "subject",
        "time_slot",
        "classroom",
    )


def _session_status_map_for_lessons(lessons, lesson_date):
    status_map = {}
    session_lookup = {
        (s.class_stream_id, s.subject_id, s.time_slot_id): s
        for s in AttendanceSession.objects.filter(
            class_stream_id__in=[l.class_stream_id for l in lessons],
            subject_id__in=[l.subject_id for l in lessons],
            date=lesson_date,
            time_slot_id__in=[l.time_slot_id for l in lessons],
        ).select_related("time_slot")
    }

    for lesson in lessons:
        key = (lesson.class_stream_id, lesson.subject_id, lesson.time_slot_id)
        session = session_lookup.get(key)
        if session is None:
            status_map[lesson.pk] = {
                "label": "Pending",
                "icon": "⏳",
                "css": "label-warning",
                "session": None,
            }
        else:
            label = "Taken" if session.is_locked else "Draft"
            icon = "✅" if session.is_locked else "📝"
            css = "label-success" if session.is_locked else "label-info"
            status_map[lesson.pk] = {
                "label": label,
                "icon": icon,
                "css": css,
                "session": session,
            }
    return status_map


def _get_selected_lesson_context(request, class_streams, subjects):
    class_stream_id = request.GET.get("class_stream") or request.POST.get("class_stream")
    subject_id = request.GET.get("subject") or request.POST.get("subject")

    class_stream = None
    subject = None
    if class_stream_id:
        try:
            class_stream = next(
                (item for item in class_streams if item.pk == int(class_stream_id)),
                None,
            )
        except (TypeError, ValueError):
            class_stream = None
    if subject_id:
        try:
            subject = next((item for item in subjects if item.pk == int(subject_id)), None)
        except (TypeError, ValueError):
            subject = None
    return class_stream, subject


def _resolve_target_date(request):
    date_value = (
        request.GET.get("date")
        or request.POST.get("date")
        or timezone.localdate().isoformat()
    )
    parsed = parse_date(str(date_value))
    return parsed or timezone.localdate()


def _resolve_time_slot(request, *, class_stream=None, subject=None, target_date=None):
    posted_slot_id = request.GET.get("time_slot") or request.POST.get("time_slot")
    if posted_slot_id:
        try:
            slot_id = int(posted_slot_id)
            timetable_slot = (
                Timetable.objects.filter(
                    class_stream=class_stream,
                    subject=subject,
                    weekday=_weekday_code(target_date),
                    time_slot_id=slot_id,
                )
                .select_related("time_slot")
                .first()
            )
            return timetable_slot.time_slot if timetable_slot else None
        except (TypeError, ValueError):
            pass

    if not class_stream or not subject or not target_date:
        return None

    weekday = _weekday_code(target_date)
    lessons = (
        Timetable.objects.filter(
            class_stream=class_stream,
            subject=subject,
            weekday=weekday,
        )
        .select_related("time_slot")
        .order_by("time_slot__start_time")
    )
    if not lessons.exists():
        return None

    if target_date == timezone.localdate():
        now_time = timezone.localtime().time()
        current_lesson = lessons.filter(
            time_slot__start_time__lte=now_time,
            time_slot__end_time__gte=now_time,
        ).first()
        if current_lesson:
            return current_lesson.time_slot

    return lessons.first().time_slot


def _resolve_lesson(*, class_stream=None, subject=None, target_date=None, time_slot=None, teacher=None):
    if not class_stream or not subject or not target_date:
        return None

    lessons = Timetable.objects.filter(
        class_stream=class_stream,
        subject=subject,
        weekday=_weekday_code(target_date),
    ).select_related("time_slot", "teacher")
    if time_slot:
        lessons = lessons.filter(time_slot=time_slot)

    if teacher:
        preferred = lessons.filter(teacher=teacher).first()
        if preferred:
            return preferred

    return lessons.first()


def _can_unlock(request):
    return _is_admin_user(request)


def _build_attendance_summary(session):
    counts = {value: 0 for value, _ in AttendanceStatus.choices}
    if not session:
        return counts

    for row in session.records.values("status").annotate(total=Count("id")):
        counts[row["status"]] = row["total"]
    return counts


@login_required
def attendance_dashboard(request):
    staff = _get_staff(request)
    if not staff:
        messages.error(request, "Access denied.")
        return redirect("dashboard")

    today = timezone.localdate()
    weekday = _weekday_code(today)
    lessons = list(
        _teacher_lesson_queryset(staff, weekday_code=weekday).order_by("time_slot__start_time")
    )

    lesson_status = _session_status_map_for_lessons(lessons, today)
    completed = sum(1 for row in lesson_status.values() if row["label"] == "Taken")
    pending = max(len(lessons) - completed, 0)

    today_sessions = AttendanceSession.objects.filter(
        teacher=staff,
        date=today,
    ).prefetch_related("records")
    total_records = sum(session.records.count() for session in today_sessions)
    total_present = sum(
        session.records.filter(status=AttendanceStatus.PRESENT).count()
        for session in today_sessions
    )
    attendance_rate = round((total_present / total_records) * 100, 1) if total_records else 0

    lesson_rows = []
    for lesson in lessons:
        status_meta = lesson_status.get(lesson.pk, {})
        action_label = "View Attendance" if status_meta.get("session") else "Take Attendance"
        action_css = "btn-default" if status_meta.get("session") else "btn-success"
        lesson_rows.append(
            {
                "lesson": lesson,
                "status": status_meta,
                "action_label": action_label,
                "action_css": action_css,
                "action_url": (
                    f"{reverse('take_attendance')}?class_stream={lesson.class_stream_id}"
                    f"&subject={lesson.subject_id}&date={today.isoformat()}"
                    f"&time_slot={lesson.time_slot_id}"
                ),
            }
        )

    context = {
        "today": today,
        "today_lessons_count": len(lessons),
        "pending_lessons_count": pending,
        "completed_lessons_count": completed,
        "attendance_rate": attendance_rate,
        "lesson_rows": lesson_rows,
    }
    return render(request, "attendance/attendance_dashboard.html", context)


@login_required
def take_attendance(request):
    staff = _get_staff(request)
    if not staff:
        messages.error(request, "Access denied.")
        return redirect("dashboard")

    assignments = _teacher_assignments(staff)
    class_streams = sorted({a.academic_class_stream for a in assignments}, key=lambda x: str(x))
    subjects = sorted({a.subject for a in assignments}, key=lambda x: x.name)

    class_stream, subject = _get_selected_lesson_context(request, class_streams, subjects)
    target_date = _resolve_target_date(request)
    time_slot = _resolve_time_slot(
        request,
        class_stream=class_stream,
        subject=subject,
        target_date=target_date,
    )
    lesson = _resolve_lesson(
        class_stream=class_stream,
        subject=subject,
        target_date=target_date,
        time_slot=time_slot,
        teacher=staff,
    )

    session_form = AttendanceSessionForm(
        request.POST or None,
        initial={
            "date": target_date,
            "time_slot": getattr(time_slot, "pk", None),
        },
    )

    session = None
    students = []
    records = {}

    if request.method == "POST" and session_form.is_valid():
        target_date = session_form.cleaned_data["date"]
        time_slot = session_form.cleaned_data["time_slot"]
        lesson = _resolve_lesson(
            class_stream=class_stream,
            subject=subject,
            target_date=target_date,
            time_slot=time_slot,
            teacher=staff,
        )

    if class_stream and subject:
        academic_year = (
            class_stream.academic_class.academic_year
            or AcademicYear.objects.filter(is_current=True).first()
        )
        term = class_stream.academic_class.term
        if academic_year and term:
            session = get_or_create_session(
                class_stream=class_stream,
                subject=subject,
                teacher=staff,
                date=target_date,
                time_slot=time_slot,
                academic_year=academic_year,
                term=term,
                lesson=lesson,
            )
            initialize_session_records(session)
            students = list(
                ClassRegister.objects.filter(academic_class_stream=class_stream)
                .select_related("student")
                .order_by("student__student_name")
            )
            records = {
                record.student_id: record
                for record in session.records.select_related("student", "captured_by")
            }

    can_unlock = _can_unlock(request)

    if request.method == "POST" and session:
        if session.is_locked:
            if can_unlock:
                messages.warning(
                    request,
                    "This session is locked. Reopen it first using the admin override button.",
                )
            else:
                messages.warning(
                    request,
                    "This session is already locked. Contact admin to reopen it.",
                )
        else:
            payload_raw = request.POST.get("attendance_payload") or "{}"
            try:
                payload = json.loads(payload_raw)
            except json.JSONDecodeError:
                payload = {}

            valid_student_ids = {str(reg.student_id) for reg in students}
            sanitized_payload = {
                student_id: row
                for student_id, row in payload.items()
                if str(student_id) in valid_student_ids
            }

            if sanitized_payload:
                save_attendance_records(
                    session,
                    sanitized_payload,
                    captured_by=staff,
                    actor_user=request.user,
                )
            lock_session(session, actor_user=request.user)
            messages.success(request, "Attendance submitted successfully. Editing is now locked.")
            return redirect(
                f"{request.path}?class_stream={class_stream.pk}&subject={subject.pk}"
                f"&date={target_date.isoformat()}&time_slot={session.time_slot_id or ''}"
            )

    summary = _build_attendance_summary(session)

    context = {
        "class_streams": class_streams,
        "subjects": subjects,
        "selected_class_stream": class_stream,
        "selected_subject": subject,
        "session_form": session_form,
        "session": session,
        "students": students,
        "records": records,
        "status_choices": AttendanceStatus.choices,
        "is_locked": bool(session and session.is_locked),
        "can_unlock": can_unlock,
        "summary": summary,
    }
    return render(request, "attendance/take_attendance.html", context)


@login_required
@require_POST
def unlock_attendance(request, session_id):
    if not _can_unlock(request):
        messages.error(request, "Only admins can reopen locked attendance sessions.")
        return redirect("attendance_dashboard")

    session = get_object_or_404(AttendanceSession, pk=session_id)
    reason = (request.POST.get("reason") or "Admin override").strip()
    unlock_session(session, actor_user=request.user, reason=reason)
    messages.success(request, "Attendance session reopened for editing.")

    next_url = (request.POST.get("next") or "").strip()
    if next_url:
        return redirect(next_url)

    return redirect(
        f"{reverse('take_attendance')}?class_stream={session.class_stream_id}"
        f"&subject={session.subject_id}&date={session.date.isoformat()}"
        f"&time_slot={session.time_slot_id or ''}"
    )


@login_required
def attendance_history(request):
    staff = _get_staff(request)
    if not staff and not _is_admin_user(request):
        messages.error(request, "Access denied.")
        return redirect("dashboard")

    filter_form = AttendanceHistoryFilterForm(request.GET or None)
    sessions = AttendanceSession.objects.select_related(
        "class_stream",
        "class_stream__academic_class",
        "class_stream__stream",
        "subject",
        "teacher",
        "academic_year",
        "term",
        "time_slot",
    )

    if not _is_admin_user(request):
        sessions = sessions.filter(teacher=staff)

    if filter_form.is_valid():
        class_stream = filter_form.cleaned_data.get("class_stream")
        subject = filter_form.cleaned_data.get("subject")
        academic_year = filter_form.cleaned_data.get("academic_year")
        term = filter_form.cleaned_data.get("term")
        date_from = filter_form.cleaned_data.get("date_from")
        date_to = filter_form.cleaned_data.get("date_to")

        if class_stream:
            sessions = sessions.filter(class_stream=class_stream)
        if subject:
            sessions = sessions.filter(subject=subject)
        if academic_year:
            sessions = sessions.filter(academic_year=academic_year)
        if term:
            sessions = sessions.filter(term=term)
        if date_from:
            sessions = sessions.filter(date__gte=date_from)
        if date_to:
            sessions = sessions.filter(date__lte=date_to)

    sessions = sessions.annotate(
        present_count=Count("records", filter=Q(records__status=AttendanceStatus.PRESENT)),
        absent_count=Count("records", filter=Q(records__status=AttendanceStatus.ABSENT)),
        late_count=Count("records", filter=Q(records__status=AttendanceStatus.LATE)),
        excused_count=Count("records", filter=Q(records__status=AttendanceStatus.EXCUSED)),
        total_count=Count("records"),
    ).order_by("-date", "-time_slot__start_time")

    context = {
        "filter_form": filter_form,
        "sessions": sessions,
        "can_unlock": _can_unlock(request),
    }
    return render(request, "attendance/attendance_history.html", context)


@login_required
def attendance_analysis(request):
    staff = _get_staff(request)
    if not staff and not _is_admin_user(request):
        messages.error(request, "Access denied.")
        return redirect("dashboard")

    filter_form = AttendanceHistoryFilterForm(request.GET or None)
    sessions = AttendanceSession.objects.select_related(
        "class_stream",
        "subject",
        "teacher",
        "academic_year",
        "term",
    )

    if not _is_admin_user(request):
        sessions = sessions.filter(teacher=staff)

    if filter_form.is_valid():
        class_stream = filter_form.cleaned_data.get("class_stream")
        subject = filter_form.cleaned_data.get("subject")
        academic_year = filter_form.cleaned_data.get("academic_year")
        term = filter_form.cleaned_data.get("term")
        date_from = filter_form.cleaned_data.get("date_from")
        date_to = filter_form.cleaned_data.get("date_to")

        if class_stream:
            sessions = sessions.filter(class_stream=class_stream)
        if subject:
            sessions = sessions.filter(subject=subject)
        if academic_year:
            sessions = sessions.filter(academic_year=academic_year)
        if term:
            sessions = sessions.filter(term=term)
        if date_from:
            sessions = sessions.filter(date__gte=date_from)
        if date_to:
            sessions = sessions.filter(date__lte=date_to)

    sessions = sessions.order_by("date", "time_slot__start_time")

    status_aggregate = AttendanceRecord.objects.filter(session__in=sessions).values("status").annotate(
        total=Count("id")
    )
    status_map = {value: 0 for value, _ in AttendanceStatus.choices}
    for row in status_aggregate:
        status_map[row["status"]] = row["total"]

    total_marked = sum(status_map.values())
    present_total = status_map[AttendanceStatus.PRESENT]
    average_rate = round((present_total / total_marked) * 100, 1) if total_marked else 0

    policy = AttendancePolicy.load()
    minimum_threshold = policy.minimum_attendance_percent

    student_rollups = AttendanceRecord.objects.filter(session__in=sessions).values("student").annotate(
        total=Count("id"),
        present=Count("id", filter=Q(status=AttendanceStatus.PRESENT)),
    )
    students_below_threshold = 0
    for row in student_rollups:
        rate = round((row["present"] / row["total"]) * 100, 1) if row["total"] else 0
        if rate < minimum_threshold:
            students_below_threshold += 1

    daily_rollups = list(
        sessions.values("date").annotate(
            total=Count("records"),
            present=Count("records", filter=Q(records__status=AttendanceStatus.PRESENT)),
        ).order_by("date")
    )
    trend_labels = [item["date"].strftime("%Y-%m-%d") for item in daily_rollups]
    trend_values = [
        round((item["present"] / item["total"]) * 100, 1) if item["total"] else 0
        for item in daily_rollups
    ]

    term_rollups = list(
        sessions.values("academic_year__academic_year", "term__term")
        .annotate(
            total=Count("records"),
            present=Count("records", filter=Q(records__status=AttendanceStatus.PRESENT)),
        )
        .order_by("academic_year__academic_year", "term__term")
    )
    term_labels = [
        f"{item['academic_year__academic_year']} T{item['term__term']}" for item in term_rollups
    ]
    term_values = [
        round((item["present"] / item["total"]) * 100, 1) if item["total"] else 0
        for item in term_rollups
    ]

    context = {
        "filter_form": filter_form,
        "average_rate": average_rate,
        "students_below_threshold": students_below_threshold,
        "total_lessons": sessions.count(),
        "minimum_threshold": minimum_threshold,
        "distribution": status_map,
        "trend_labels_json": json.dumps(trend_labels),
        "trend_values_json": json.dumps(trend_values),
        "distribution_labels_json": json.dumps(["Present", "Absent", "Late", "Excused"]),
        "distribution_values_json": json.dumps(
            [
                status_map[AttendanceStatus.PRESENT],
                status_map[AttendanceStatus.ABSENT],
                status_map[AttendanceStatus.LATE],
                status_map[AttendanceStatus.EXCUSED],
            ]
        ),
        "term_labels_json": json.dumps(term_labels),
        "term_values_json": json.dumps(term_values),
    }
    return render(request, "attendance/attendance_analysis.html", context)


@login_required
def student_attendance_report(request):
    student_id = request.GET.get("student")
    date_from = request.GET.get("date_from")
    date_to = request.GET.get("date_to")

    today = timezone.localdate()
    parsed_from = parse_date(date_from) if date_from else today.replace(day=1)
    parsed_to = parse_date(date_to) if date_to else today

    student = None
    records = AttendanceRecord.objects.none()
    if student_id:
        try:
            student = Student.objects.get(pk=student_id)
            records = AttendanceRecord.objects.filter(
                student=student,
                session__date__gte=parsed_from,
                session__date__lte=parsed_to,
            ).select_related(
                "session",
                "session__class_stream",
                "session__subject",
                "session__time_slot",
            ).order_by("session__date", "session__time_slot__start_time")
        except (Student.DoesNotExist, ValueError):
            student = None

    total = records.count()
    present = records.filter(status=AttendanceStatus.PRESENT).count()
    absent = records.filter(status=AttendanceStatus.ABSENT).count()
    late = records.filter(status=AttendanceStatus.LATE).count()
    excused = records.filter(status=AttendanceStatus.EXCUSED).count()

    context = {
        "students": Student.objects.filter(is_active=True).order_by("student_name"),
        "selected_student": student,
        "date_from": parsed_from.strftime("%Y-%m-%d") if parsed_from else "",
        "date_to": parsed_to.strftime("%Y-%m-%d") if parsed_to else "",
        "records": records,
        "total": total,
        "present": present,
        "absent": absent,
        "late": late,
        "excused": excused,
        "attendance_percentage": round((present / total) * 100, 1) if total > 0 else 0,
    }
    return render(request, "attendance/student_attendance_report.html", context)


@login_required
def class_attendance_report(request):
    class_stream_id = request.GET.get("class_stream")
    date_from = request.GET.get("date_from")
    date_to = request.GET.get("date_to")
    subject_id = request.GET.get("subject")

    today = timezone.localdate()
    parsed_from = parse_date(date_from) if date_from else (today - timedelta(days=today.weekday()))
    parsed_to = parse_date(date_to) if date_to else today

    class_stream = None
    subject = None
    sessions = AttendanceSession.objects.none()
    student_summary = []

    if class_stream_id:
        try:
            class_stream = AcademicClassStream.objects.get(pk=class_stream_id)
            session_filter = Q(
                class_stream=class_stream,
                date__gte=parsed_from,
                date__lte=parsed_to,
            )
            if subject_id:
                try:
                    subject = Subject.objects.get(pk=subject_id)
                    session_filter &= Q(subject=subject)
                except Subject.DoesNotExist:
                    subject = None

            sessions = AttendanceSession.objects.filter(session_filter).select_related(
                "subject",
                "time_slot",
            ).order_by("date", "time_slot__start_time", "subject__name")

            class_registers = ClassRegister.objects.filter(
                academic_class_stream=class_stream
            ).select_related("student")

            for reg in class_registers:
                records = AttendanceRecord.objects.filter(
                    student=reg.student,
                    session__in=sessions,
                )
                total = records.count()
                present = records.filter(status=AttendanceStatus.PRESENT).count()
                absent = records.filter(status=AttendanceStatus.ABSENT).count()
                student_summary.append(
                    {
                        "student": reg.student,
                        "total": total,
                        "present": present,
                        "absent": absent,
                        "percentage": round((present / total) * 100, 1) if total else 0,
                    }
                )

            student_summary.sort(key=lambda row: row["percentage"])
        except (AcademicClassStream.DoesNotExist, ValueError):
            class_stream = None

    total_present = sum(row["present"] for row in student_summary)
    total_absent = sum(row["absent"] for row in student_summary)

    context = {
        "class_streams": AcademicClassStream.objects.select_related(
            "academic_class__Class",
            "stream",
        ).order_by("academic_class__Class__name"),
        "selected_class_stream": class_stream,
        "subjects": Subject.objects.order_by("name"),
        "selected_subject": subject,
        "date_from": parsed_from.strftime("%Y-%m-%d") if parsed_from else "",
        "date_to": parsed_to.strftime("%Y-%m-%d") if parsed_to else "",
        "sessions": sessions,
        "student_summary": student_summary,
        "total_present": total_present,
        "total_absent": total_absent,
    }
    return render(request, "attendance/class_attendance_report.html", context)


@login_required
def attendance_admin_control(request):
    if not _is_admin_user(request):
        messages.error(request, "Only admins can access attendance control.")
        return redirect("attendance_dashboard")

    policy = AttendancePolicy.load()
    policy_form = AttendancePolicyForm(request.POST or None, instance=policy)

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()

        if action == "update_policy" and policy_form.is_valid():
            policy_form.save()
            AttendanceAuditLog.objects.create(
                action=AttendanceAuditLog.ACTION_POLICY_UPDATED,
                actor=request.user,
                reason="Attendance policy updated",
                details={
                    "minimum_attendance_percent": policy.minimum_attendance_percent,
                    "allow_teacher_edit_locked_sessions": policy.allow_teacher_edit_locked_sessions,
                },
            )
            messages.success(request, "Attendance policy updated.")
            return redirect("attendance_admin_control")

        if action == "unlock_session":
            session_id = request.POST.get("session_id")
            reason = (request.POST.get("reason") or "Admin override").strip()
            if session_id:
                session = get_object_or_404(AttendanceSession, pk=session_id)
                unlock_session(session, actor_user=request.user, reason=reason)
                messages.success(request, "Session reopened successfully.")
                return redirect("attendance_admin_control")

        if action == "relock_session":
            session_id = request.POST.get("session_id")
            reason = (request.POST.get("reason") or "Relocked by admin").strip()
            if session_id:
                session = get_object_or_404(AttendanceSession, pk=session_id)
                lock_session(session, actor_user=request.user, reason=reason)
                AttendanceAuditLog.objects.create(
                    session=session,
                    action=AttendanceAuditLog.ACTION_RELOCKED,
                    actor=request.user,
                    reason=reason[:255],
                )
                messages.success(request, "Session locked successfully.")
                return redirect("attendance_admin_control")

    locked_sessions = AttendanceSession.objects.filter(is_locked=True).select_related(
        "class_stream",
        "class_stream__academic_class",
        "class_stream__stream",
        "subject",
        "teacher",
        "time_slot",
    ).order_by("-date", "-time_slot__start_time")[:40]

    audit_logs = AttendanceAuditLog.objects.select_related(
        "session",
        "record",
        "record__student",
        "actor",
    ).order_by("-created_at")[:120]

    context = {
        "policy_form": policy_form,
        "locked_sessions": locked_sessions,
        "audit_logs": audit_logs,
    }
    return render(request, "attendance/admin_attendance_control.html", context)


@login_required
def export_attendance_csv(request):
    if not _is_admin_user(request):
        messages.error(request, "Only admins can export attendance data.")
        return redirect("attendance_dashboard")

    date_from = parse_date(request.GET.get("date_from") or "")
    date_to = parse_date(request.GET.get("date_to") or "")

    records = AttendanceRecord.objects.select_related(
        "session",
        "session__class_stream",
        "session__subject",
        "session__teacher",
        "session__time_slot",
        "student",
        "captured_by",
    )
    if date_from:
        records = records.filter(session__date__gte=date_from)
    if date_to:
        records = records.filter(session__date__lte=date_to)

    records = records.order_by("session__date", "session__time_slot__start_time", "student__student_name")

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="attendance_export.csv"'

    writer = csv.writer(response)
    writer.writerow(
        [
            "Date",
            "Lesson Period",
            "Class",
            "Subject",
            "Teacher",
            "Student",
            "Reg No",
            "Status",
            "Remarks",
            "Session Locked",
            "Captured By",
            "Captured At",
        ]
    )

    for record in records:
        session = record.session
        writer.writerow(
            [
                session.date.isoformat(),
                session.lesson_period,
                str(session.class_stream),
                session.subject.name,
                str(session.teacher),
                record.student.student_name,
                record.student.reg_no,
                record.get_status_display(),
                record.remarks,
                "Yes" if session.is_locked else "No",
                str(record.captured_by or ""),
                timezone.localtime(record.captured_at).strftime("%Y-%m-%d %H:%M"),
            ]
        )

    return response
