from django.db import transaction
from django.utils import timezone

from app.models.attendance import (
    AttendanceAuditLog,
    AttendanceRecord,
    AttendanceSession,
    AttendanceStatus,
)
from app.models.students import ClassRegister


def get_or_create_session(
    class_stream,
    subject,
    teacher,
    date,
    time_slot,
    academic_year,
    term,
    lesson=None,
):
    """
    AttendanceSession uniqueness is defined by (class_stream, subject, date, time_slot).
    Teacher is mutable metadata and should not be part of the get-or-create lookup.
    """
    session, _ = AttendanceSession.objects.get_or_create(
        class_stream=class_stream,
        subject=subject,
        date=date,
        time_slot=time_slot,
        defaults={
            "teacher": teacher,
            "academic_year": academic_year,
            "term": term,
            "lesson": lesson,
        },
    )
    update_fields = []
    if session.teacher_id != teacher.id:
        session.teacher = teacher
        update_fields.append("teacher")
    if session.academic_year_id != academic_year.id:
        session.academic_year = academic_year
        update_fields.append("academic_year")
    if session.term_id != term.id:
        session.term = term
        update_fields.append("term")
    if session.lesson_id != getattr(lesson, "id", None):
        session.lesson = lesson
        update_fields.append("lesson")
    if update_fields:
        session.save(update_fields=update_fields)
    return session


@transaction.atomic
def initialize_session_records(session):
    students = (
        ClassRegister.objects.filter(academic_class_stream=session.class_stream)
        .select_related("student")
        .values_list("student", flat=True)
    )
    existing = set(
        AttendanceRecord.objects.filter(session=session).values_list("student_id", flat=True)
    )
    new_records = [
        AttendanceRecord(
            session=session,
            student_id=student_id,
            status=AttendanceStatus.PRESENT,
        )
        for student_id in students
        if student_id not in existing
    ]
    if new_records:
        AttendanceRecord.objects.bulk_create(new_records)


@transaction.atomic
def save_attendance_records(session, payload, captured_by, actor_user=None):
    allowed_statuses = {value for value, _ in AttendanceStatus.choices}
    for student_id, row in payload.items():
        student_pk = int(student_id)
        status = row.get("status") or AttendanceStatus.PRESENT
        if status not in allowed_statuses:
            status = AttendanceStatus.PRESENT
        remarks = row.get("remarks") or ""
        existing_record = AttendanceRecord.objects.filter(
            session=session,
            student_id=student_pk,
        ).first()
        old_status = existing_record.status if existing_record else ""
        record, _ = AttendanceRecord.objects.update_or_create(
            session=session,
            student_id=student_pk,
            defaults={
                "status": status,
                "remarks": remarks,
                "captured_by": captured_by,
                "captured_at": timezone.now(),
            },
        )
        AttendanceAuditLog.objects.create(
            session=session,
            record=record,
            action=AttendanceAuditLog.ACTION_RECORD_UPDATED,
            actor=actor_user,
            old_status=old_status,
            new_status=status,
            reason=(remarks or "")[:255],
            details={"student_id": student_pk},
        )


def lock_session(session, *, actor_user=None, reason="Submitted by teacher"):
    if session.is_locked:
        return session
    session.is_locked = True
    session.save(update_fields=["is_locked", "updated_at"])
    AttendanceAuditLog.objects.create(
        session=session,
        action=AttendanceAuditLog.ACTION_SUBMITTED,
        actor=actor_user,
        reason=reason[:255],
        details={
            "class_stream_id": session.class_stream_id,
            "subject_id": session.subject_id,
            "time_slot_id": session.time_slot_id,
            "date": session.date.isoformat(),
        },
    )
    return session


def unlock_session(session, *, actor_user=None, reason="Admin override"):
    if not session.is_locked:
        return session
    session.is_locked = False
    session.save(update_fields=["is_locked", "updated_at"])
    AttendanceAuditLog.objects.create(
        session=session,
        action=AttendanceAuditLog.ACTION_UNLOCKED,
        actor=actor_user,
        reason=reason[:255],
        details={
            "class_stream_id": session.class_stream_id,
            "subject_id": session.subject_id,
            "time_slot_id": session.time_slot_id,
            "date": session.date.isoformat(),
        },
    )
    return session
