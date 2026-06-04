from django import forms
from django.utils import timezone

from app.models.attendance import AttendancePolicy, AttendanceStatus
from app.models.classes import AcademicClassStream, Term
from app.models.school_settings import AcademicYear
from app.models.subjects import Subject
from app.models.timetables import TimeSlot


class AttendanceSessionForm(forms.Form):
    date = forms.DateField(
        initial=timezone.now().date(),
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    time_slot = forms.ModelChoiceField(
        queryset=TimeSlot.objects.all().order_by("start_time"),
        required=False,
        empty_label="-- Select Time Slot --",
    )


class AttendanceMarkForm(forms.Form):
    status = forms.ChoiceField(choices=AttendanceStatus.choices)
    remarks = forms.CharField(required=False)


class AttendanceHistoryFilterForm(forms.Form):
    class_stream = forms.ModelChoiceField(
        queryset=AcademicClassStream.objects.select_related(
            "academic_class__Class",
            "stream",
        ).order_by("academic_class__Class__name"),
        required=False,
        empty_label="All Classes",
    )
    subject = forms.ModelChoiceField(
        queryset=Subject.objects.order_by("name"),
        required=False,
        empty_label="All Subjects",
    )
    academic_year = forms.ModelChoiceField(
        queryset=AcademicYear.objects.order_by("-academic_year"),
        required=False,
        empty_label="All Academic Years",
    )
    term = forms.ModelChoiceField(
        queryset=Term.objects.select_related("academic_year").order_by(
            "-academic_year__academic_year",
            "-start_date",
        ),
        required=False,
        empty_label="All Terms",
    )
    date_from = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    date_to = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            existing = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{existing} form-control".strip()


class AttendancePolicyForm(forms.ModelForm):
    class Meta:
        model = AttendancePolicy
        fields = ("minimum_attendance_percent", "allow_teacher_edit_locked_sessions")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if name == "allow_teacher_edit_locked_sessions":
                field.widget.attrs["class"] = "flat"
            else:
                field.widget.attrs["class"] = "form-control"


class AttendanceUnlockForm(forms.Form):
    reason = forms.CharField(
        required=True,
        max_length=255,
        label="Reason",
        widget=forms.TextInput(
            attrs={
                "placeholder": "Reason for reopening this locked session",
            }
        ),
    )
