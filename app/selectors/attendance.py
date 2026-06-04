from app.models.attendance import AttendanceSession, AttendanceRecord


def get_session_records(session):
    return AttendanceRecord.objects.filter(session=session).select_related("student")


def get_teacher_sessions(teacher, start_date=None, end_date=None):
    qs = AttendanceSession.objects.filter(teacher=teacher)
    if start_date:
        qs = qs.filter(date__gte=start_date)
    if end_date:
        qs = qs.filter(date__lte=end_date)
    return qs.select_related("class_stream", "subject", "time_slot")
