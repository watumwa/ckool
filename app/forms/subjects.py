from django.forms import ModelForm, DateInput
from crispy_forms.helper import FormHelper

from app.models.subjects import Subject

class SubjectForm(ModelForm):
    
    class Meta:
        model = Subject
        fields = ("__all__")
