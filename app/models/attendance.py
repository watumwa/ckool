from django.db import models
from django.utils import timezone

from AbstractModels.singleton import SingletonModel
from app.models.classes import AcademicClassStream, Term
from app.models.school_settings import AcademicYear
from app.models.students import Student
from app.models.subjects import Subject
from app.models.staffs import Staff
from app.models.timetables import TimeSlot, Timetable


class AttendanceStatus(models.TextChoices):
    PRESENT = "present", "Present"
    LATE = "late", "Late"
    ABSENT = "absent", "Absent"
    EXCUSED = "excused", "Excused"


class AttendanceSession(models.Model):
    lesson = models.ForeignKey(
        Timetable,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="attendance_sessions",
    )
    class_stream = models.ForeignKey(
        AcademicClassStream, on_delete=models.CASCADE, related_name="attendance_sessions"
    )
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name="attendance_sessions")
    teacher = models.ForeignKey(Staff, on_delete=models.CASCADE, related_name="attendance_sessions")
    academic_year = models.ForeignKey(AcademicYear, on_delete=models.CASCADE)
    term = models.ForeignKey(Term, on_delete=models.CASCADE)
    date = models.DateField(default=timezone.now)
    time_slot = models.ForeignKey(TimeSlot, on_delete=models.SET_NULL, null=True, blank=True)
    is_locked = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("class_stream", "subject", "date", "time_slot")
        ordering = ("-date", "class_stream")
        indexes = [
            models.Index(fields=["date", "time_slot"]),
            models.Index(fields=["teacher", "date"]),
            models.Index(fields=["academic_year", "term"]),
        ]

    def __str__(self):
        return f"{self.class_stream} - {self.subject} - {self.date}"

    @property
    def lesson_period(self):
        if not self.time_slot:
            return "N/A"
        return (
            f"{self.time_slot.start_time.strftime('%H:%M')} - "
            f"{self.time_slot.end_time.strftime('%H:%M')}"
        )

    def status_counts(self):
        counts = {value: 0 for value, _ in AttendanceStatus.choices}
        for row in self.records.values("status").annotate(total=models.Count("id")):
            counts[row["status"]] = row["total"]
        return counts


class AttendancePolicy(SingletonModel):
    minimum_attendance_percent = models.PositiveSmallIntegerField(default=75)
    allow_teacher_edit_locked_sessions = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Attendance Policy"
        verbose_name_plural = "Attendance Policy"

    def clean(self):
        if self.minimum_attendance_percent < 1 or self.minimum_attendance_percent > 100:
            from django.core.exceptions import ValidationError

            raise ValidationError(
                {"minimum_attendance_percent": "Minimum attendance must be between 1 and 100."}
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Attendance Policy ({self.minimum_attendance_percent}%)"


class AttendanceRecord(models.Model):
    session = models.ForeignKey(
        AttendanceSession, on_delete=models.CASCADE, related_name="records"
    )
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="attendance_records")
    status = models.CharField(
        max_length=20, choices=AttendanceStatus.choices, default=AttendanceStatus.PRESENT
    )
    remarks = models.CharField(max_length=255, blank=True)
    captured_by = models.ForeignKey(Staff, on_delete=models.SET_NULL, null=True, blank=True)
    captured_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("session", "student")
        ordering = ("student",)
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["student", "session"]),
        ]

    def __str__(self):
        return f"{self.student} - {self.session} - {self.status}"


class AttendanceAuditLog(models.Model):
    ACTION_SUBMITTED = "submitted"
    ACTION_UNLOCKED = "unlocked"
    ACTION_RELOCKED = "relocked"
    ACTION_RECORD_UPDATED = "record_updated"
    ACTION_POLICY_UPDATED = "policy_updated"

    ACTION_CHOICES = (
        (ACTION_SUBMITTED, "Submitted"),
        (ACTION_UNLOCKED, "Unlocked"),
        (ACTION_RELOCKED, "Relocked"),
        (ACTION_RECORD_UPDATED, "Record Updated"),
        (ACTION_POLICY_UPDATED, "Policy Updated"),
    )

    session = models.ForeignKey(
        AttendanceSession,
        on_delete=models.CASCADE,
        related_name="audit_logs",
        null=True,
        blank=True,
    )
    record = models.ForeignKey(
        AttendanceRecord,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
    )
    action = models.CharField(max_length=40, choices=ACTION_CHOICES)
    actor = models.ForeignKey(
        "auth.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="attendance_audit_logs",
    )
    old_status = models.CharField(max_length=20, blank=True, default="")
    new_status = models.CharField(max_length=20, blank=True, default="")
    reason = models.CharField(max_length=255, blank=True, default="")
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["action", "created_at"]),
            models.Index(fields=["session", "created_at"]),
        ]

    def __str__(self):
        when = self.created_at.strftime("%Y-%m-%d %H:%M")
        return f"{self.get_action_display()} @ {when}"
