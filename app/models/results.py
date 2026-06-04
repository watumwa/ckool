from django.db import models
from django.contrib.auth.models import User
from decimal import Decimal
from app.models.school_settings import SchoolSetting
from app.models.students import Student
from app.models.classes import AcademicClass, Term
from app.models.subjects import Subject


class GradingSystem(models.Model):
    min_score = models.DecimalField(max_digits=5, decimal_places=2)
    max_score = models.DecimalField(max_digits=5, decimal_places=2)
    grade = models.CharField(max_length=10)
    points = models.DecimalField(max_digits=4, decimal_places=2)

    def __str__(self):
        return f'{self.grade} ({self.min_score} - {self.max_score})'


class AssessmentType(models.Model):
    name = models.CharField(max_length=50, unique=True)
    weight = models.DecimalField(max_digits=5, decimal_places=2)

    def __str__(self):
        return self.name


class Assessment(models.Model):
    academic_class = models.ForeignKey("app.AcademicClass", on_delete=models.CASCADE, related_name='assessments')
    assessment_type = models.ForeignKey("app.AssessmentType", on_delete=models.CASCADE, related_name='assessments')
    subject = models.ForeignKey("app.Subject", on_delete=models.CASCADE, related_name='assessments')
    date = models.DateField()
    out_of = models.IntegerField(default=100)
    is_done = models.BooleanField(default=False)

    class Meta:
        unique_together = ("academic_class", "assessment_type", "subject")

    def __str__(self):
        return f'{self.assessment_type} - {self.subject} {self.academic_class}'



class ResultModeSetting(models.Model):
    MODE_CHOICES = [
        ("CUMULATIVE", "Cumulative"),
        ("NON_CUMULATIVE", "Non-Cumulative"),
    ]

    mode = models.CharField(max_length=20, choices=MODE_CHOICES, default="CUMULATIVE")

    def __str__(self):
        return f"Current Mode: {self.mode}"

    @classmethod
    def get_mode(cls):
        setting = cls.objects.first()
        return setting.mode if setting else "CUMULATIVE"


class ResultVerificationSetting(models.Model):
    """Global settings for result verification rules."""
    sample_percent = models.DecimalField(max_digits=5, decimal_places=2, default=5.00)
    tolerance_marks = models.DecimalField(max_digits=5, decimal_places=2, default=1.00)

    def __str__(self):
        return "Result Verification Settings"

    @classmethod
    def get_settings(cls):
        setting = cls.objects.first()
        return setting if setting else cls.objects.create()


class ResultBatch(models.Model):
    STATUS_CHOICES = [
        ("DRAFT", "Draft"),
        ("PENDING", "Pending Verification"),
        ("VERIFIED", "Verified"),
        ("FLAGGED", "Flagged"),
    ]
    assessment = models.OneToOneField("app.Assessment", on_delete=models.CASCADE, related_name="result_batch")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="DRAFT")
    submitted_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="submitted_batches")
    submitted_at = models.DateTimeField(null=True, blank=True)
    verified_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="verified_batches")
    verified_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.assessment} - {self.status}"


class VerificationSample(models.Model):
    result = models.OneToOneField("app.Result", on_delete=models.CASCADE, related_name="verification_sample")
    dos_mark = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    matched = models.BooleanField(null=True)
    checked_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="checked_samples")
    checked_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Sample - {self.result.student} - {self.result.assessment}"


class ResultVerificationReport(models.Model):
    STATUS_CHOICES = [
        ("APPROVED", "Approved"),
        ("REJECTED", "Rejected"),
        ("RECHECK", "Re-check Required"),
    ]

    batch = models.OneToOneField("app.ResultBatch", on_delete=models.CASCADE, related_name="verification_report")
    total_scripts = models.PositiveIntegerField(default=0)
    sampled_count = models.PositiveIntegerField(default=0)
    reentered_count = models.PositiveIntegerField(default=0)
    matches_count = models.PositiveIntegerField(default=0)
    mismatches_count = models.PositiveIntegerField(default=0)
    corrections_count = models.PositiveIntegerField(default=0)
    accuracy_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="RECHECK")
    verified_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="verification_reports")
    verified_at = models.DateTimeField(null=True, blank=True)
    sampling_method = models.CharField(max_length=255, default="Random (system)")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Verification Report - {self.batch.assessment}"


class VerificationDiscrepancy(models.Model):
    sample = models.OneToOneField("app.VerificationSample", on_delete=models.CASCADE, related_name="discrepancy")
    batch = models.ForeignKey("app.ResultBatch", on_delete=models.CASCADE, related_name="discrepancies")
    result = models.ForeignKey("app.Result", on_delete=models.CASCADE, related_name="discrepancies")
    teacher_mark = models.DecimalField(max_digits=5, decimal_places=2)
    verifier_mark = models.DecimalField(max_digits=5, decimal_places=2)
    difference = models.DecimalField(max_digits=6, decimal_places=2)
    corrected_mark = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    action_taken = models.CharField(max_length=255, default="Flagged")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Discrepancy - {self.result.student} - {self.result.assessment}"


class VerificationCorrectionLog(models.Model):
    batch = models.ForeignKey("app.ResultBatch", on_delete=models.CASCADE, related_name="correction_logs")
    result = models.ForeignKey("app.Result", on_delete=models.CASCADE, related_name="correction_logs")
    old_mark = models.DecimalField(max_digits=5, decimal_places=2)
    new_mark = models.DecimalField(max_digits=5, decimal_places=2)
    reason = models.TextField()
    corrected_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="verification_corrections")
    corrected_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Correction - {self.result.student} - {self.result.assessment}"


class ResultVerificationNotification(models.Model):
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name="result_verification_notifications")
    batch = models.ForeignKey(ResultBatch, on_delete=models.CASCADE, related_name="notifications")
    title = models.CharField(max_length=255)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)
    read = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.title} - {self.recipient}"

class Result(models.Model):
    STATUS_CHOICES = [
        ("DRAFT", "Draft"),
        ("PENDING", "Pending Verification"),
        ("VERIFIED", "Verified"),
        ("FLAGGED", "Flagged"),
    ]
    assessment = models.ForeignKey("app.Assessment", on_delete=models.CASCADE, related_name='results')
    student = models.ForeignKey("app.Student", on_delete=models.CASCADE, related_name='results')
    score = models.DecimalField(max_digits=5, decimal_places=2)
    batch = models.ForeignKey(ResultBatch, on_delete=models.SET_NULL, null=True, blank=True, related_name="results")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="DRAFT")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["assessment", "student"],
                name="uniq_result_assessment_student",
            )
        ]
   
    def __str__(self):
        return f'{self.student} - {self.assessment} - {self.score}'

    def mark_verified(self):
        self.status = "VERIFIED"
        self.save(update_fields=["status"])

    @property
    def grade(self):
        grading = GradingSystem.objects.filter(min_score__lte=self.score, max_score__gte=self.score).first()
        return grading.grade if grading else "N/A"

    @property
    def points(self):
        grading = GradingSystem.objects.filter(min_score__lte=self.score, max_score__gte=self.score).first()
        return grading.points if grading else Decimal('0.00')

    @property
    def actual_score(self):
        weight = self.assessment.assessment_type.weight
        mode = ResultModeSetting.get_mode()

        if mode == "CUMULATIVE":
            if weight > 0:
                return round((self.score / self.assessment.out_of) * weight, 0)
        elif mode == "NON_CUMULATIVE":
            return self.score

        return self.score


class ReportResults(models.Model):
    student = models.ForeignKey("app.Student", on_delete=models.CASCADE)
    subject = models.ForeignKey("app.Subject", on_delete=models.CASCADE)
    academic_class = models.ForeignKey("app.AcademicClass", on_delete=models.CASCADE, related_name='report_results')
    term = models.ForeignKey("app.Term", on_delete=models.CASCADE)

    def __str__(self):
        return f"{self.student} - {self.subject} - {self.academic_class}"

    def calculate_term_result(self):
    

        mode = ResultModeSetting.get_mode()
        details = self.details.all()

        if mode == "CUMULATIVE":
            total_score = sum(d.score for d in details)
            total_points = sum(d.points for d in details)
            return total_score, total_points

        elif mode == "NON_CUMULATIVE":
            return [(d.assessment_type.name, d.score) for d in details]


class ReportResultDetail(models.Model):
    report = models.ForeignKey(ReportResults, on_delete=models.CASCADE, related_name='details')
    assessment_type = models.ForeignKey("app.AssessmentType", on_delete=models.CASCADE)
    score = models.DecimalField(max_digits=5, decimal_places=2)
    points = models.DecimalField(max_digits=4, decimal_places=2)

    def __str__(self):
        return f"{self.report.student} - {self.assessment_type.name}: {self.score}"
    

class ReportRemark(models.Model):
    student = models.ForeignKey("app.Student", on_delete=models.CASCADE, related_name='remarks')
    term = models.ForeignKey("app.Term", on_delete=models.CASCADE, related_name='remarks')
    class_teacher_remark = models.TextField(blank=True, null=True)
    head_teacher_remark = models.TextField(blank=True, null=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('student', 'term')

    def __str__(self):
        return f"Remarks for {self.student.student_name} - {self.term.term}"

class TermResult(models.Model):
    student = models.ForeignKey("app.Student", on_delete=models.CASCADE, related_name='term_results')
    academic_class = models.ForeignKey("app.AcademicClass", on_delete=models.CASCADE, related_name='term_results')
    total_score = models.DecimalField(max_digits=6, decimal_places=2, default=0.00)
    average_score = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    total_points = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    rank_in_class = models.IntegerField(null=True, blank=True)

    def __str__(self):
        return f'{self.academic_class} - {self.student}'

    def calculate_term_result(self):
        """Calculate total and average scores, and total GPA points."""
        exam_results = self.student.results.filter(assessment__academic_class__term=self.term)
        total_score = sum(result.actual_score for result in exam_results)
        total_points = sum(result.points for result in exam_results)
        subjects_count = exam_results.count()
        self.total_score = total_score
        self.average_score = total_score / subjects_count if subjects_count > 0 else 0
        self.total_points = total_points
        self.save()

class AnnualResult(models.Model):
    student = models.ForeignKey("app.Student", on_delete=models.CASCADE, related_name='annual_results')
    academic_class = models.ForeignKey("app.AcademicClass", on_delete=models.CASCADE, related_name='annual_results')
    total_score = models.DecimalField(max_digits=6, decimal_places=2, default=0.00)
    average_score = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    total_points = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    rank_in_class = models.IntegerField(null=True, blank=True)

    def __str__(self):
        return f'Annual Result - {self.student} - {self.academic_class.academic_year}'

    def calculate_annual_result(self):
        """Calculate total and average scores, and total GPA points for the academic year."""
        term_results = self.student.term_results.filter(term__academic_year=self.academic_year)
        total_score = sum(term_result.total_score for term_result in term_results)
        total_points = sum(term_result.total_points for term_result in term_results)
        term_count = term_results.count()

        self.total_score = total_score
        self.average_score = total_score / term_count if term_count > 0 else 0
        self.total_points = total_points
        self.save()

    def calculate_rank(self):
        """Optional: Calculate rank within the class based on total score."""
        all_results = AnnualResult.objects.filter(academic_year=self.academic_year, student__class_level=self.student.class_level)
        sorted_results = sorted(all_results, key=lambda x: x.total_score, reverse=True)
        for index, result in enumerate(sorted_results):
            if result.student == self.student:
                self.rank_in_class = index + 1
                self.save()
                break
