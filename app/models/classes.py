from django.db import models
from django.urls import reverse
from django.conf import settings

from app.constants import TERMS

class Class(models.Model):
    
    name = models.CharField(max_length=50)
    code = models.CharField(max_length=3)
    section = models.ForeignKey("app.Section", on_delete=models.CASCADE)

    class Meta:
        verbose_name = ("Class")
        verbose_name_plural = ("Classes")

    def __str__(self):
        return self.code

    def get_absolute_url(self):
        return reverse("Class_detail", kwargs={"pk": self.pk})

class Stream(models.Model):
    
    stream = models.CharField(max_length=20, unique=True, default="-")

    class Meta:
        verbose_name = ("stream")
        verbose_name_plural = ("streams")

    def __str__(self):
        return self.stream

    def get_absolute_url(self):
        return reverse("stream_detail", kwargs={"pk": self.pk})

class Term(models.Model):
    
    academic_year = models.ForeignKey("app.AcademicYear", on_delete=models.CASCADE)
    term = models.CharField(max_length=5, choices=TERMS)
    start_date = models.DateField()
    end_date = models.DateField()
    is_current = models.BooleanField(default=True)

    def __str__(self):
        return f'Term {self.term}'

    class Meta:
        verbose_name = ("Term")
        verbose_name_plural = ("Terms")
        unique_together = ("academic_year", "term")

    def get_absolute_url(self):
        return reverse("Term_detail", kwargs={"pk": self.pk})


class AcademicClass(models.Model):
    
    section = models.ForeignKey("app.Section", on_delete=models.CASCADE)
    Class = models.ForeignKey("app.Class", on_delete=models.CASCADE)
    academic_year = models.ForeignKey("app.AcademicYear", on_delete=models.CASCADE)
    term = models.ForeignKey(Term, on_delete=models.CASCADE)
    fees_amount = models.IntegerField()

    class Meta:
        verbose_name = ("AcademicClass")
        verbose_name_plural = ("AcademicClasses")
        unique_together = ("Class", "academic_year", "term")

    def __str__(self):
        return f"{self.Class} {self.term} - {self.academic_year}"

    def get_absolute_url(self):
        return reverse("AcademicClass_detail", kwargs={"pk": self.pk})

class AcademicClassStream(models.Model):
    academic_class = models.ForeignKey("app.AcademicClass", on_delete=models.CASCADE, related_name="class_streams")
    stream = models.ForeignKey("app.Stream", on_delete=models.CASCADE)
    class_teacher = models.ForeignKey("app.Staff", on_delete=models.CASCADE)
    class_teacher_signature = models.ImageField(upload_to="signatures", blank=True ,null=True)
    is_timetable_locked = models.BooleanField(default=False)
    

    class Meta:
        verbose_name = "Class Stream"
        verbose_name_plural = "Class Streams"
        unique_together = ("academic_class", "stream")

    def __str__(self):
        return f"{self.academic_class} - {self.stream}"

    def get_absolute_url(self):
        return reverse("ClassStream_detail", kwargs={"pk": self.pk})


class ClassSubjectAllocation(models.Model):
    
    academic_class_stream = models.ForeignKey("app.AcademicClassStream",on_delete=models.CASCADE, related_name="subjects")
    subject = models.ForeignKey("app.Subject", on_delete=models.CASCADE, related_name="subjects")
    subject_teacher = models.ForeignKey("app.Staff", on_delete=models.CASCADE, related_name="subjects")

    class Meta:
        verbose_name = ("classsubjectallocation")
        verbose_name_plural = ("classsubjectallocations")
        unique_together = [('academic_class_stream', 'subject')]

    def __str__(self):
        return f"{self.academic_class_stream} - {self.subject} - {self.subject_teacher}"

    def get_absolute_url(self):
        return reverse("classsubjectallocation_detail", kwargs={"pk": self.pk})


class StudentPromotionHistory(models.Model):
    source_academic_class = models.ForeignKey(
        "app.AcademicClass",
        on_delete=models.PROTECT,
        related_name="promotion_history_as_source",
    )
    target_academic_class = models.ForeignKey(
        "app.AcademicClass",
        on_delete=models.PROTECT,
        related_name="promotion_history_as_target",
    )
    source_stream = models.ForeignKey(
        "app.AcademicClassStream",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="promotion_history_rows",
    )
    promoted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="student_promotion_history_rows",
    )
    active_students_only = models.BooleanField(default=True)
    total_candidates = models.PositiveIntegerField(default=0)
    promoted_count = models.PositiveIntegerField(default=0)
    already_registered_count = models.PositiveIntegerField(default=0)
    skipped_inactive_count = models.PositiveIntegerField(default=0)
    skipped_duplicate_source_count = models.PositiveIntegerField(default=0)
    updated_student_snapshots = models.PositiveIntegerField(default=0)
    missing_stream_names = models.JSONField(default=list, blank=True)
    promoted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Student promotion history"
        verbose_name_plural = "Student promotion history"
        ordering = ("-promoted_at", "-id")
        indexes = [
            models.Index(fields=("promoted_at",), name="sph_promoted_at_idx"),
            models.Index(fields=("source_academic_class", "promoted_at"), name="sph_src_promoted_idx"),
            models.Index(fields=("target_academic_class", "promoted_at"), name="sph_tgt_promoted_idx"),
            models.Index(fields=("promoted_by", "promoted_at"), name="sph_user_promoted_idx"),
        ]

    def __str__(self):
        return (
            f"{self.source_academic_class} -> {self.target_academic_class} "
            f"({self.promoted_count}/{self.total_candidates})"
        )
