from django.db import models
from django.urls import reverse
from django.core.exceptions import ValidationError
from app.constants import *
from app.constants import GENDERS, EMPLOYEE_STATUS, TYPE_CHOICES, MARITAL_STATUS, ROLE_CHOICES,DOCUMENT_TYPES


def validate_nin(value):
    """Validate NIN format only if a value is provided"""
    if value:  
        import re
        if not re.match(r'^[A-Z0-9]{14}$', value):
            raise ValidationError("NIN must be 14 characters long, uppercase letters and numbers only.")

class Role(models.Model):
    name = models.CharField(max_length=50, choices=ROLE_CHOICES, unique=True)
    
    class Meta:
        verbose_name = ("Role")
        verbose_name_plural = ("Roles")
        
    def __str__(self):
        return self.name


class Staff(models.Model):
    first_name = models.CharField(max_length=20)
    last_name = models.CharField(max_length=20)
    birth_date = models.DateField()
    gender = models.CharField(max_length=1, choices=GENDERS)
    address = models.TextField()
    marital_status = models.CharField(max_length=1, choices=MARITAL_STATUS)
    contacts = models.CharField(max_length=20)
    email = models.EmailField(max_length=254)
    qualification = models.CharField(max_length=100)
    nin_no = models.CharField(max_length=14, blank=True, null=True, validators=[validate_nin], verbose_name="NIN")
    hire_date = models.DateField()
    department = models.CharField(max_length=30,choices=TYPE_CHOICES)
    salary = models.DecimalField(max_digits=10, decimal_places=2)
    is_academic_staff = models.BooleanField(default=False)
    is_administrator_staff = models.BooleanField(default=False)
    is_support_staff = models.BooleanField(default=False)
    staff_status = models.CharField(max_length=20, choices=EMPLOYEE_STATUS, default="Active")
    staff_photo = models.ImageField(upload_to="Staff/Profile_pics", height_field=None, width_field=None, max_length=None)
    roles = models.ManyToManyField(Role, related_name='staff_members')

    def __str__(self):
        return f"{self.first_name} {self.last_name}"

    class Meta:
        verbose_name = ("Staff")
        verbose_name_plural = ("Staffs")
        ordering = ("-id",)

    def get_absolute_url(self):
        return reverse("Staff_detail", kwargs={"pk": self.pk})




class BankDetail(models.Model):
    
    staff = models.OneToOneField("app.Staff", on_delete=models.CASCADE)
    bank_name = models.CharField(max_length=50)
    branch_name = models.CharField(max_length=50)
    account_no = models.CharField(max_length=50)
    account_name = models.CharField(max_length=50)

    class Meta:
        verbose_name = ("bankdetail")
        verbose_name_plural = ("bankdetails")

    def __str__(self):
        return f"{self.staff} - {self.bank_name}"

    def get_absolute_url(self):
        return reverse("bankdetail_detail", kwargs={"pk": self.pk})

class StaffDocument(models.Model):

    staff = models.ForeignKey("app.Staff", on_delete=models.CASCADE)
    document_type = models.CharField(max_length=50,choices=DOCUMENT_TYPES)
    file = models.FileField(upload_to="Staff/Documents", max_length=100)

    class Meta:
        verbose_name = ("StaffDocument")
        verbose_name_plural = ("StaffDocuments")

    def __str__(self):
        return f"{self.staff} - {self.document_type}"

    def get_absolute_url(self):
        return reverse("StaffDocument_detail", kwargs={"pk": self.pk})
