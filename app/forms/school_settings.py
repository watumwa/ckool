from django import forms
from django.forms import ModelForm

from app.models.school_settings import *


class SchoolSettingForm(ModelForm):
    class Meta:
        model = SchoolSetting
        fields = (
            "country",
            "city",
            "address",
            "postal",
            "website",
            "school_name",
            "school_motto",
            "mobile",
            "office_phone_number1",
            "office_phone_number2",
            "school_logo",
            "app_name",
            "offers_primary",
            "offers_secondary_lower",
            "education_level",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["offers_primary"].label = "Offers primary"
        self.fields["offers_primary"].help_text = "Enable primary school workflows."
        self.fields["offers_secondary_lower"].label = "Offers secondary"
        self.fields["offers_secondary_lower"].help_text = (
            "Enable secondary workflows (O-Level + A-Level)."
        )
        self.fields["education_level"].label = "Default Active Level"
        self.fields["education_level"].choices = (
            (SchoolSetting.EducationLevel.PRIMARY, "Primary"),
            (SchoolSetting.EducationLevel.SECONDARY_LOWER, "Secondary"),
        )
        self.fields["education_level"].help_text = (
            "Default active school level used when no session level is selected."
        )

        secondary_enabled = bool(
            getattr(self.instance, "offers_secondary_lower", False)
            or getattr(self.instance, "offers_secondary_upper", False)
        )
        self.initial.setdefault("offers_secondary_lower", secondary_enabled)

        if not self.is_bound and self.initial.get("education_level") == SchoolSetting.EducationLevel.SECONDARY_UPPER:
            self.initial["education_level"] = SchoolSetting.EducationLevel.SECONDARY_LOWER

    def clean(self):
        cleaned_data = super().clean()
        secondary_enabled = bool(cleaned_data.get("offers_secondary_lower"))
        cleaned_data["offers_secondary_upper"] = secondary_enabled

        selected_default = cleaned_data.get("education_level")
        if selected_default == SchoolSetting.EducationLevel.SECONDARY_UPPER:
            selected_default = SchoolSetting.EducationLevel.SECONDARY_LOWER
        cleaned_data["education_level"] = selected_default

        level_flags = {
            SchoolSetting.EducationLevel.PRIMARY: cleaned_data.get("offers_primary"),
            SchoolSetting.EducationLevel.SECONDARY_LOWER: secondary_enabled,
        }

        if not any(level_flags.values()):
            raise forms.ValidationError("Select at least one school level to enable.")

        if selected_default and not level_flags.get(selected_default):
            self.add_error(
                "education_level",
                "Default active level must be one of the enabled school levels.",
            )

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)

        secondary_enabled = bool(self.cleaned_data.get("offers_secondary_lower"))
        instance.offers_secondary_lower = secondary_enabled
        instance.offers_secondary_upper = secondary_enabled
        if instance.education_level == SchoolSetting.EducationLevel.SECONDARY_UPPER:
            instance.education_level = SchoolSetting.EducationLevel.SECONDARY_LOWER

        if commit:
            instance.save()
            self.save_m2m()
        return instance


class SectionForm(ModelForm):
    
    class Meta:
        model = Section
        fields = ("__all__")

class SignatureForm(ModelForm):
    
    class Meta:
        model = Signature
        fields = ("__all__")

class DepartmentForm(ModelForm):
    
    class Meta:
        model = Department
        fields = ("__all__")
