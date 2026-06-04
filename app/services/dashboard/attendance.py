"""Attendance service for the admin control-tower dashboard."""

from __future__ import annotations

from datetime import timedelta

from django.db.models import Count, Q
from django.utils import timezone

from app.models.attendance import AttendanceRecord, AttendanceSession, AttendanceStatus
from app.models.timetables import Timetable
from app.services.level_scope import (
    get_level_academic_classes_queryset,
    get_level_class_streams_queryset,
)
from app.services.school_level import get_active_school_level

PRESENT_LIKE_STATUSES = [AttendanceStatus.PRESENT, AttendanceStatus.LATE]
WEEKDAY_CODES = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]


def _weekday_code(for_date):
    return WEEKDAY_CODES[for_date.weekday()]


def _attendance_rate(queryset) -> float:
    total = queryset.count()
    if not total:
        return 0
    present_like = queryset.filter(status__in=PRESENT_LIKE_STATUSES).count()
    return round((present_like / total) * 100, 1)


def get_attendance_context(request, scope):
    """Attendance health, submission gaps, and chronic absenteeism."""
    current_year = scope.get("current_year")
    current_term = scope.get("current_term")
    active_level = get_active_school_level(request)
    today = timezone.localdate()
    week_start = today - timedelta(days=6)

    attendance_today_rate = 0
    attendance_week_rate = 0
    class_submission_rows = []
    class_attendance_rows = []
    chronic_absentee_rows = []
    weekly_trend_rows = []
    teachers_absent_today = 0
    classes_not_submitted_count = 0
    class_pending_rate = 0
    teacher_pending_rate = 0
    total_teachers = 0
    total_class_streams = 0

    if current_year and current_term:
        term_scoped_academic_classes = get_level_academic_classes_queryset(
            active_level=active_level
        ).filter(
            academic_year=current_year,
            term=current_term,
        )
        attendance_scope = AttendanceRecord.objects.filter(
            session__academic_year=current_year,
            session__term=current_term,
            session__class_stream__academic_class__in=term_scoped_academic_classes,
        )
        attendance_today_rate = _attendance_rate(attendance_scope.filter(session__date=today))
        attendance_week_rate = _attendance_rate(
            attendance_scope.filter(session__date__range=(week_start, today))
        )

        class_stream_scope = get_level_class_streams_queryset(
            active_level=active_level
        ).filter(
            academic_class__in=term_scoped_academic_classes
        ).select_related("academic_class__Class", "stream")

        submitted_stream_ids = set(
            AttendanceSession.objects.filter(
                academic_year=current_year,
                term=current_term,
                date=today,
                class_stream__academic_class__in=term_scoped_academic_classes,
            )
            .values_list("class_stream_id", flat=True)
            .distinct()
        )

        scheduled_lessons_today = Timetable.objects.filter(
            class_stream__academic_class__in=term_scoped_academic_classes,
            weekday=_weekday_code(today),
        )
        scheduled_stream_ids = set(
            scheduled_lessons_today.values_list("class_stream_id", flat=True).distinct()
        )
        if scheduled_stream_ids:
            # Include streams that submitted today even if timetable setup is incomplete.
            expected_stream_ids = scheduled_stream_ids | submitted_stream_ids
            expected_class_streams_qs = class_stream_scope.filter(id__in=expected_stream_ids)
        else:
            # Fallback for schools that have not configured timetable entries.
            expected_class_streams_qs = class_stream_scope

        expected_stream_ids = set(expected_class_streams_qs.values_list("id", flat=True))
        if expected_stream_ids:
            submitted_stream_ids = submitted_stream_ids & expected_stream_ids

        for class_stream in expected_class_streams_qs:
            submitted = class_stream.id in submitted_stream_ids
            class_submission_rows.append(
                {
                    "class_name": class_stream.academic_class.Class.name,
                    "stream_name": class_stream.stream.stream,
                    "submitted": submitted,
                }
            )
        class_submission_rows = sorted(
            class_submission_rows,
            key=lambda row: (
                row["class_name"],
                row["stream_name"],
            ),
        )
        classes_not_submitted_count = len(
            [row for row in class_submission_rows if not row["submitted"]]
        )

        total_class_streams = len(expected_stream_ids)
        submitted_teacher_ids = set(
            AttendanceSession.objects.filter(
                academic_year=current_year,
                term=current_term,
                date=today,
                class_stream__academic_class__in=term_scoped_academic_classes,
            )
            .values_list("teacher_id", flat=True)
            .distinct()
        )
        submitted_teacher_ids.discard(None)

        scheduled_teacher_ids = set()
        for teacher_id, allocation_teacher_id, class_teacher_id in scheduled_lessons_today.values_list(
            "teacher_id",
            "allocation__subject_teacher_id",
            "class_stream__class_teacher_id",
        ).distinct():
            selected_teacher_id = teacher_id or allocation_teacher_id or class_teacher_id
            if selected_teacher_id:
                scheduled_teacher_ids.add(selected_teacher_id)
        if scheduled_teacher_ids:
            expected_teacher_ids = scheduled_teacher_ids | submitted_teacher_ids
        else:
            expected_teacher_ids = set(
                expected_class_streams_qs.values_list("class_teacher_id", flat=True).distinct()
            )
            expected_teacher_ids.discard(None)
            expected_teacher_ids |= submitted_teacher_ids

        total_teachers = len(expected_teacher_ids)
        teachers_absent_today = len(expected_teacher_ids - submitted_teacher_ids)
        class_pending_rate = round((classes_not_submitted_count / total_class_streams) * 100, 1) if total_class_streams else 0
        teacher_pending_rate = round((teachers_absent_today / total_teachers) * 100, 1) if total_teachers else 0

        class_attendance_agg = list(
            attendance_scope.values(
                "session__class_stream__academic_class__Class__name",
                "session__class_stream__stream__stream",
            )
            .annotate(
                total=Count("id"),
                present_like=Count("id", filter=Q(status__in=PRESENT_LIKE_STATUSES)),
            )
            .order_by("session__class_stream__academic_class__Class__name")
        )
        for row in class_attendance_agg:
            total = row["total"] or 0
            present_like = row["present_like"] or 0
            class_attendance_rows.append(
                {
                    "class_name": row["session__class_stream__academic_class__Class__name"]
                    or "Unknown",
                    "stream_name": row["session__class_stream__stream__stream"] or "-",
                    "total": total,
                    "present_like": present_like,
                    "rate": round((present_like / total) * 100, 1) if total else 0,
                }
            )

        student_attendance = (
            attendance_scope.values(
                "student_id",
                "student__student_name",
                "student__student_number",
                "student__reg_no",
                "student__current_class__name",
            )
            .annotate(
                total_sessions=Count("id"),
                present_sessions=Count("id", filter=Q(status__in=PRESENT_LIKE_STATUSES)),
            )
            .order_by("student__student_name")
        )
        for row in student_attendance:
            total_sessions = row["total_sessions"] or 0
            present_sessions = row["present_sessions"] or 0
            if not total_sessions:
                continue
            rate = round((present_sessions / total_sessions) * 100, 1)
            if total_sessions >= 5 and rate < 75:
                chronic_absentee_rows.append(
                    {
                        "student_name": row["student__student_name"] or "Unknown",
                        "reg_no": row.get("student__student_number") or row.get("student__reg_no") or "-",
                        "class_name": row["student__current_class__name"] or "-",
                        "rate": rate,
                        "total_sessions": total_sessions,
                    }
                )
        chronic_absentee_rows = sorted(chronic_absentee_rows, key=lambda row: row["rate"])[:10]

        raw_weekly = list(
            attendance_scope.filter(session__date__range=(week_start, today))
            .values("session__date")
            .annotate(
                total=Count("id"),
                present_like=Count("id", filter=Q(status__in=PRESENT_LIKE_STATUSES)),
            )
            .order_by("session__date")
        )
        weekly_map = {
            row["session__date"]: {
                "total": row["total"] or 0,
                "present_like": row["present_like"] or 0,
            }
            for row in raw_weekly
        }
        cursor = week_start
        while cursor <= today:
            item = weekly_map.get(cursor, {"total": 0, "present_like": 0})
            total = item["total"]
            present_like = item["present_like"]
            weekly_trend_rows.append(
                {
                    "label": cursor.strftime("%a"),
                    "date": cursor,
                    "rate": round((present_like / total) * 100, 1) if total else 0,
                }
            )
            cursor = cursor + timedelta(days=1)

    return {
        "attendance_today_rate": attendance_today_rate,
        "attendance_week_rate": attendance_week_rate,
        "attendance_teachers_absent_today": teachers_absent_today,
        "attendance_total_teachers": total_teachers,
        "attendance_classes_not_submitted_count": classes_not_submitted_count,
        "attendance_total_class_streams": total_class_streams,
        "attendance_class_pending_rate": class_pending_rate,
        "attendance_teacher_pending_rate": teacher_pending_rate,
        "attendance_class_submission_rows": class_submission_rows,
        "attendance_class_rows": class_attendance_rows,
        "attendance_chronic_absentee_rows": chronic_absentee_rows,
        "attendance_weekly_trend_rows": weekly_trend_rows,
    }
