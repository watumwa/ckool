from django.forms import ModelForm, DateInput
from crispy_forms.helper import FormHelper
from app.models.results import *
from app.models.results import Result,Assessment,AssessmentType,GradingSystem
from django import forms
from app.models.subjects import *
from app.models.classes import AcademicClass

class ResultForm(forms.ModelForm):
    class Meta:
        model = Result
        fields = ('score',)
 
class AssesmentTypeForm(ModelForm):
    
    class Meta:
        model = AssessmentType
        fields =("__all__")
        
        
        
class AssessmentForm(forms.ModelForm):
    class Meta:
        model = Assessment
        fields = '__all__'
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'})
        }


class BulkAssessmentForm(forms.Form):
    academic_class = forms.ModelChoiceField(
        queryset=AcademicClass.objects.all(),
        widget=forms.Select(attrs={'class': 'form-control'}),
        required=True,
        label="Academic class",
    )
    assessment_type = forms.ModelChoiceField(
        queryset=AssessmentType.objects.all(),
        widget=forms.Select(attrs={'class': 'form-control'}),
        required=True,
        label="Assessment type",
    )
    subjects = forms.ModelMultipleChoiceField(
        queryset=Subject.objects.all(),
        widget=forms.CheckboxSelectMultiple(),
        required=True,
        label="Subjects",
    )
    date = forms.DateField(
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        required=True,
        label="Date",
    )
    out_of = forms.IntegerField(
        initial=100,
        widget=forms.NumberInput(attrs={'class': 'form-control'}),
        required=True,
        label="Out of",
    )
    is_done = forms.BooleanField(required=False, label="Is done")
        
class GradingSystemForm(ModelForm):
    
    class Meta:
        model = GradingSystem
        fields =("__all__")


class ReportRemarkForm(forms.ModelForm):
    class Meta:
        model = ReportRemark
        fields = ['class_teacher_remark', 'head_teacher_remark']
        widgets = {
            'class_teacher_remark': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
            'head_teacher_remark': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
        }
