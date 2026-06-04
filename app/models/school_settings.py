from django.core.exceptions import ValidationError
from django.core.validators import EmailValidator
from django.db import models
from django.urls import reverse

from AbstractModels.singleton import SingletonModel
from app.constants import *


class Currency(models.Model):
    code = models.CharField(max_length=10, unique=True, default="UGX")
    desc = models.CharField(max_length=20, default="Ugandan Shillings")
    cost = models.CharField(max_length=20, default="1")

    def __str__(self):
        return self.code

class SchoolSetting(SingletonModel):
    class EducationLevel(models.TextChoices):
        PRIMARY = "PRIMARY", "Primary"
        SECONDARY_LOWER = "SECONDARY_LOWER", "Secondary (O-Level)"
        SECONDARY_UPPER = "SECONDARY_UPPER", "Secondary (A-Level)"

    COUNTRIES = (
        ("UG", "Uganda"),
        ("KE", "Kenya"),
        ("TZ", "Tanzania"),
        ("RD", "Rwanda"),
        ("BD", "Burundi"),
        ("SD", "South Sudan")
    )
    country = models.CharField(max_length=40, choices=COUNTRIES, default="Uganda")
    city = models.CharField(max_length=40, default="Kampala")
    address = models.CharField(max_length=50, default="None")
    postal = models.CharField(max_length=50, default="None")
    website = models.CharField(max_length=50, default="None")
    school_name = models.CharField(max_length=50, default="None")
    school_motto = models.CharField(max_length=150, default="None")
    mobile = models.CharField(max_length=20, blank=True, null=True)
    office_phone_number1 = models.CharField(max_length=20, blank=True, null=True)
    office_phone_number2 = models.CharField(max_length=40, blank=True, null=True)
    email = models.EmailField(
        max_length=254,
        blank=True,
        null=True,
        validators=[EmailValidator()],
        help_text="Official school email address"
    )
    school_logo = models.ImageField(upload_to="logo", height_field=None, width_field=None, max_length=None)
    app_name = models.CharField(max_length=20, default="E-School")
    offers_primary = models.BooleanField(default=True, help_text="Enable primary school workflows (P1-P7).")
    offers_secondary_lower = models.BooleanField(
        default=False,
        help_text="Enable lower-secondary workflows (S1-S4).",
    )
    offers_secondary_upper = models.BooleanField(
        default=False,
        help_text="Enable A-Level workflows (S5-S6).",
    )
    education_level = models.CharField(
        max_length=30,
        choices=EducationLevel.choices,
        default="PRIMARY",
        help_text="Default active school level used when no session level is selected.",
    )
    division_critical_subjects = models.ManyToManyField(
        "Subject",
        blank=True,
        related_name="division_critical_for",
        help_text="Subjects that can lower a student's division if grade is F9."
    )
    division_f9_cap = models.CharField(
        max_length=12,
        default="Division 3",
        help_text="Maximum division allowed when a critical subject has F9 (e.g., Division 2 or Division 3)."
    )

    def get_enabled_levels(self):
        levels = []
        if self.offers_primary:
            levels.append(self.EducationLevel.PRIMARY)
        if self.offers_secondary_lower:
            levels.append(self.EducationLevel.SECONDARY_LOWER)
        if self.offers_secondary_upper:
            levels.append(self.EducationLevel.SECONDARY_UPPER)
        if not levels:
            levels = [self.EducationLevel.PRIMARY]
        return levels

    def clean(self):
        enabled_levels = self.get_enabled_levels()
        if not enabled_levels:
            raise ValidationError("At least one school level must be enabled.")

        if self.education_level not in enabled_levels:
            self.education_level = enabled_levels[0]

    
   


class AcademicYear(models.Model):
    
    academic_year = models.CharField(max_length=10, unique=True)
    is_current = models.BooleanField(default=True)

    class Meta:
        verbose_name = ("AcademicYear")
        verbose_name_plural = ("AcademicYears")

    def __str__(self):
        return self.academic_year

    def get_absolute_url(self):
        return reverse("AcademicYear_detail", kwargs={"pk": self.pk})


class Section(models.Model):
    
    section_name = models.CharField(max_length=50, unique=True)
    LOWER_SECONDARY_HINTS = ("o-level", "o level", "olevel", "lower secondary")
    UPPER_SECONDARY_HINTS = ("a-level", "a level", "alevel", "upper secondary")
    GENERIC_SECONDARY_HINTS = ("secondary",)

    class Meta:
        verbose_name = ("section")
        verbose_name_plural = ("sections")

    def __str__(self):
        return self.section_name

    def get_absolute_url(self):
        return reverse("section_detail", kwargs={"pk": self.pk})

    @classmethod
    def _name_filter(cls, name_hints):
        query = models.Q()
        for hint in name_hints:
            query |= models.Q(section_name__icontains=hint)
        return query

    @classmethod
    def lower_secondary_filter(cls):
        return cls._name_filter(cls.LOWER_SECONDARY_HINTS)

    @classmethod
    def upper_secondary_filter(cls):
        return cls._name_filter(cls.UPPER_SECONDARY_HINTS)

    @classmethod
    def generic_secondary_filter(cls):
        return cls._name_filter(cls.GENERIC_SECONDARY_HINTS)

    @classmethod
    def secondary_filter(cls):
        return cls._name_filter(
            cls.GENERIC_SECONDARY_HINTS + cls.LOWER_SECONDARY_HINTS + cls.UPPER_SECONDARY_HINTS
        )

class Signature(models.Model):
    
    position = models.CharField(max_length=25,choices=POSITION_SIGNATURE_CHOICES)
    signature = models.ImageField(upload_to="signatures", height_field=None, width_field=None, max_length=None)

    class Meta:
        verbose_name = ("Signature")
        verbose_name_plural = ("Signatures")

    def __str__(self):
        return self.get_position_display()

    def get_absolute_url(self):
        return reverse("Signature_detail", kwargs={"pk": self.pk})

class Department(models.Model):
    name = models.CharField(max_length=100,choices=TYPE_CHOICES)
    description = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.name
