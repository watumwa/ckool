from django import forms
from django.forms import ModelForm, HiddenInput
from django.db.models import Q
from crispy_forms.helper import FormHelper

from app.models.classes import Class, AcademicClass, Stream, AcademicClassStream,ClassSubjectAllocation
from app.models.staffs import Staff

class ClassForm(ModelForm):
    
    class Meta:
        model = Class
        fields = ("__all__")

class AcademicClassForm(ModelForm):
    
    class Meta:
        model = AcademicClass
        fields = ("__all__")

class StreamForm(ModelForm):
    
    class Meta:
        model = Stream
        fields = ("__all__")

class AcademicClassStreamForm(ModelForm):
    
    class Meta:
        model = AcademicClassStream
        fields = ("__all__")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.Helper = FormHelper()
        self.fields["academic_class"].widget = HiddenInput()
        self.fields["class_teacher"].queryset = Staff.objects.filter(
            staff_status="Active"
        ).filter(
            Q(is_academic_staff=True) | Q(department="Academic")
        ).order_by("first_name", "last_name")

    def clean_class_teacher(self):
        teacher = self.cleaned_data.get("class_teacher")
        if not teacher:
            return teacher
        if teacher.staff_status != "Active":
            raise forms.ValidationError("Selected class teacher must be active.")
        if not (teacher.is_academic_staff or teacher.department == "Academic"):
            raise forms.ValidationError("Selected class teacher is not academic/teaching staff.")
        return teacher
        

class ClassSubjectAllocationForm(ModelForm):
    class Meta:
        model = ClassSubjectAllocation
        fields =("__all__")
        
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.Helper = FormHelper()
        self.fields["subject_teacher"].queryset = Staff.objects.filter(
            staff_status="Active"
        ).filter(
            Q(is_academic_staff=True) | Q(department="Academic")
        )

    def clean_subject_teacher(self):
        teacher = self.cleaned_data.get("subject_teacher")
        if not teacher:
            return teacher
        if not (teacher.is_academic_staff or teacher.department == "Academic"):
            raise forms.ValidationError("Selected staff is not academic/teaching staff.")
        return teacher


class ClassPromotionForm(forms.Form):
    target_academic_class = forms.ModelChoiceField(
        queryset=AcademicClass.objects.none(),
        label="Target Academic Class",
        help_text="Students will be moved into the selected class stream(s) by matching stream.",
    )
    source_stream = forms.ModelChoiceField(
        queryset=AcademicClassStream.objects.none(),
        required=False,
        empty_label="All streams",
        label="Source Stream Filter",
    )
    active_students_only = forms.BooleanField(
        required=False,
        initial=True,
        label="Promote active students only",
    )

    def __init__(self, *args, source_academic_class=None, target_queryset=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.source_academic_class = source_academic_class

        if source_academic_class:
            self.fields["source_stream"].queryset = AcademicClassStream.objects.filter(
                academic_class=source_academic_class
            ).select_related("stream").order_by("stream__stream")
        else:
            self.fields["source_stream"].queryset = AcademicClassStream.objects.none()

        if target_queryset is None:
            queryset = AcademicClass.objects.all()
        else:
            queryset = target_queryset
        if source_academic_class:
            queryset = queryset.exclude(id=source_academic_class.id)
            queryset = queryset.filter(section_id=source_academic_class.section_id)
        self.fields["target_academic_class"].queryset = queryset.select_related(
            "Class",
            "term",
            "academic_year",
        )

    def clean_target_academic_class(self):
        target = self.cleaned_data.get("target_academic_class")
        if target and self.source_academic_class and target.id == self.source_academic_class.id:
            raise forms.ValidationError("Target academic class must be different from source class.")
        return target
