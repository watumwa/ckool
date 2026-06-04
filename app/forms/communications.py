from django import forms
from app.models.communications import Announcement, Event, MessageThread, Message
from app.models.accounts import StaffAccount
from app.models.classes import AcademicClassStream, ClassSubjectAllocation
from django.db.models import Q


class AnnouncementForm(forms.ModelForm):
    class Meta:
        model = Announcement
        fields = [
            "title",
            "body",
            "audience",
            "priority",
            "starts_at",
            "ends_at",
            "is_active",
        ]
        widgets = {
            "starts_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "ends_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }

    def __init__(self, *args, **kwargs):
        can_target_head = kwargs.pop("can_target_head", True)
        effective_role = kwargs.pop("effective_role", None)
        super().__init__(*args, **kwargs)
        if not can_target_head:
            self.fields["audience"].choices = [
                (value, label)
                for value, label in self.fields["audience"].choices
                if value != "head"
            ]
        if effective_role != "Class Teacher":
            self.fields["audience"].choices = [
                (value, label)
                for value, label in self.fields["audience"].choices
                if value != "class_stream"
            ]


class EventForm(forms.ModelForm):
    class Meta:
        model = Event
        fields = [
            "title",
            "description",
            "audience",
            "location",
            "start_datetime",
            "end_datetime",
            "is_active",
        ]
        widgets = {
            "start_datetime": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "end_datetime": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }

    def __init__(self, *args, **kwargs):
        can_target_head = kwargs.pop("can_target_head", True)
        effective_role = kwargs.pop("effective_role", None)
        super().__init__(*args, **kwargs)
        if not can_target_head:
            self.fields["audience"].choices = [
                (value, label)
                for value, label in self.fields["audience"].choices
                if value != "head"
            ]
        if effective_role != "Class Teacher":
            self.fields["audience"].choices = [
                (value, label)
                for value, label in self.fields["audience"].choices
                if value != "class_stream"
            ]


class MessageThreadForm(forms.ModelForm):
    recipients = forms.ModelMultipleChoiceField(
        queryset=StaffAccount.objects.none(),
        required=True,
        widget=forms.SelectMultiple(attrs={"class": "form-control"}),
        help_text="Select one or more recipients",
    )

    class Meta:
        model = MessageThread
        fields = ["subject"]

    def __init__(self, *args, **kwargs):
        sender = kwargs.pop("sender", None)
        effective_role = kwargs.pop("effective_role", None)
        super().__init__(*args, **kwargs)
        if sender and hasattr(sender, "staff_account"):
            role = sender.staff_account.role.name if sender.staff_account.role else None
            effective_role = effective_role or role

            staff_qs = StaffAccount.objects.select_related("staff")

            if effective_role == "Class Teacher":
                class_streams = AcademicClassStream.objects.filter(class_teacher=sender.staff_account.staff)
                teacher_ids = ClassSubjectAllocation.objects.filter(
                    academic_class_stream__in=class_streams
                ).values_list("subject_teacher_id", flat=True)
                staff_qs = staff_qs.filter(staff_id__in=teacher_ids)
            elif effective_role == "Teacher":
                staff_qs = staff_qs.exclude(role__name__in=["Head Teacher", "Head master"])

            self.fields["recipients"].queryset = staff_qs.exclude(user=sender)


class MessageForm(forms.ModelForm):
    class Meta:
        model = Message
        fields = ["body"]
