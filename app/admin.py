from django import forms
from django.contrib import admin  
from app.models.accounts import StaffAccount
from app.models.classes import *
from app.models.staffs import *
from app.models.results import *
from app.models.school_settings import *
from app.models.students import *
from app.models.fees_payment import (
    BillItem,
    StudentBill,
    StudentBillItem,
    Payment,
    ClassBill,
    StudentCredit,
    infer_ledger_category,
)
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.urls import reverse
import json
from .models import Classroom, TimeSlot, BreakPeriod, Timetable
from app.models.attendance import (
    AttendanceAuditLog,
    AttendancePolicy,
    AttendanceRecord,
    AttendanceSession,
)

# admin.site.register(Staff)
admin.site.register(Role)

@admin.register(Result)
class ResultAdmin(admin.ModelAdmin):
    list_display = (
        'student', 'assessment', 'score',
        'status', 'batch'
    )
    list_filter = (
        'status', 'assessment__academic_class', 'assessment__assessment_type'
    )
    search_fields = (
        'student__student_name', 'student__reg_no',
        'assessment__subject__name', 'assessment__assessment_type__name'
    )
admin.site.register(Assessment)
admin.site.register(AssessmentType)
# admin.site.register(Student)
# admin.site.register(Section)
# admin.site.register(Class)
admin.site.register(Stream)


@admin.register(ClassRegister)
class ClassRegisterAdmin(admin.ModelAdmin):
    list_display = (
        "student_name",
        "reg_no",
        "class_name",
        "stream_name",
        "term_name",
        "academic_year_name",
        "section_name",
        "payment_status",
    )
    list_filter = (
        "payment_status",
        "student__is_active",
        "academic_class_stream__academic_class__academic_year",
        "academic_class_stream__academic_class__term",
        "academic_class_stream__academic_class__Class",
        "academic_class_stream__academic_class__section",
        "academic_class_stream__stream",
    )
    search_fields = (
        "student__student_name",
        "student__student_number",
        "student__reg_no",
        "academic_class_stream__academic_class__Class__name",
        "academic_class_stream__academic_class__Class__code",
        "academic_class_stream__stream__stream",
    )
    autocomplete_fields = ("student", "academic_class_stream")
    list_per_page = 50
    ordering = (
        "-academic_class_stream__academic_class__academic_year__academic_year",
        "academic_class_stream__academic_class__term__term",
        "academic_class_stream__academic_class__Class__name",
        "student__student_name",
    )

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset.select_related(
            "student",
            "academic_class_stream__stream",
            "academic_class_stream__academic_class__Class",
            "academic_class_stream__academic_class__term",
            "academic_class_stream__academic_class__academic_year",
            "academic_class_stream__academic_class__section",
        )

    @admin.display(description="Student", ordering="student__student_name")
    def student_name(self, obj):
        return obj.student.student_name

    @admin.display(description="Student ID", ordering="student__student_number")
    def reg_no(self, obj):
        return obj.student.student_number or obj.student.reg_no

    @admin.display(description="Class", ordering="academic_class_stream__academic_class__Class__name")
    def class_name(self, obj):
        academic_class = obj.academic_class_stream.academic_class
        return academic_class.Class.code or academic_class.Class.name

    @admin.display(description="Stream", ordering="academic_class_stream__stream__stream")
    def stream_name(self, obj):
        return obj.academic_class_stream.stream.stream

    @admin.display(description="Term", ordering="academic_class_stream__academic_class__term__term")
    def term_name(self, obj):
        return f"Term {obj.academic_class_stream.academic_class.term.term}"

    @admin.display(description="Year", ordering="academic_class_stream__academic_class__academic_year__academic_year")
    def academic_year_name(self, obj):
        return obj.academic_class_stream.academic_class.academic_year.academic_year

    @admin.display(description="Section", ordering="academic_class_stream__academic_class__section__section_name")
    def section_name(self, obj):
        return obj.academic_class_stream.academic_class.section.section_name

@admin.register(SchoolSetting)
class SchoolSettingAdmin(admin.ModelAdmin):
    filter_horizontal = ("division_critical_subjects",)


admin.site.register(Department)



@admin.register(AcademicYear)
class AcademicYearAdmin(admin.ModelAdmin):
    list_display = ('academic_year', 'is_current')
    list_filter = ('is_current',)
    search_fields = ('academic_year',)

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset  

@admin.register(Class)
class ClassAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'section')
    list_filter = ('section',)
    search_fields = ('name', 'code', 'section__section_name')  

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset.select_related('section')  
    
    
    #
@admin.register(Section)
class SectionAdmin(admin.ModelAdmin):
    list_display = ('section_name',)
    search_fields = ('section_name',)

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset  


@admin.register(Staff)
class StaffAdmin(admin.ModelAdmin):
    list_display = (
        'staff_photo_preview', 'first_name', 'last_name', 'email',
        'contacts', 'department', 'display_roles'
    )
    list_filter = ('department', 'gender')
    search_fields = ('first_name', 'last_name', 'email', 'contacts')
    readonly_fields = ('staff_photo_preview',)

    def staff_photo_preview(self, obj):
        if obj.staff_photo:
            return format_html('<img src="{}" style="height: 40px; border-radius: 5px;" />', obj.staff_photo.url)
        return "No Photo"
    staff_photo_preview.short_description = 'Photo'

    def display_roles(self, obj):
        return ", ".join([role.name for role in obj.roles.all()])
    display_roles.short_description = 'Roles'

class StudentBillInline(admin.TabularInline):
    model = StudentBill
    extra = 0
    fields = ('academic_class', 'bill_date', 'status', 'total_amount', 'amount_paid', 'balance', 'manage_payments')
    readonly_fields = ('bill_date', 'total_amount', 'amount_paid', 'balance', 'manage_payments')

    def manage_payments(self, obj):
        url = reverse('admin:app_studentbill_change', args=[obj.pk])
        return format_html('<a class="button" href="{}">Open bill</a>', url)
    manage_payments.short_description = 'Payments'

@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = (
        'photo_preview', 'student_number', 'reg_no', 'student_name', 'gender',
        'current_class', 'is_active', 'contact', 'guardian'
    )
    list_filter = ('gender', 'current_class', 'academic_year', 'is_active')
    search_fields = ('student_number', 'reg_no', 'student_name', 'guardian', 'contact')
    readonly_fields = ('photo_preview',)
    inlines = [StudentBillInline]
    actions = None

    def photo_preview(self, obj):
        if obj.photo:
            return format_html('<img src="{}" style="height: 40px; border-radius: 5px;" />', obj.photo.url)
        return "No Photo"
    photo_preview.short_description = 'Photo'

    def has_delete_permission(self, request, obj=None):
        return False

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)
        return actions


@admin.register(Term)
class TermAdmin(admin.ModelAdmin):
    list_display = ('term', 'academic_year', 'start_date', 'end_date', 'is_current')
    list_filter = ('academic_year', 'term', 'is_current')
    search_fields = ('term', 'academic_year__name')  
    # readonly_fields = ('start_date', 'end_date')

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset.select_related('academic_year')  

@admin.register(AcademicClass)
class AcademicClassAdmin(admin.ModelAdmin):
    list_display = ('Class', 'term', 'academic_year', 'fees_amount')
    list_filter = ('Class', 'academic_year', 'term')
    search_fields = ('Class__name', 'academic_year__name', 'term__term')  
    def get_readonly_fields(self, request, obj=None):
        # Allow editing fees_amount when adding a new AcademicClass
        # Keep it read-only on change to prevent accidental edits
        return ('fees_amount',) if obj else ()

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset.select_related('Class', 'academic_year', 'term')  

@admin.register(AcademicClassStream)
class AcademicClassStreamAdmin(admin.ModelAdmin):
    list_display = ('academic_class', 'stream', 'class_teacher')
    list_filter = ('academic_class', 'stream', 'class_teacher')
    search_fields = ('academic_class__Class__name', 'stream__name', 'class_teacher__first_name', 'class_teacher__last_name')  

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset.select_related('academic_class', 'stream', 'class_teacher')


@admin.register(StudentPromotionHistory)
class StudentPromotionHistoryAdmin(admin.ModelAdmin):
    list_display = (
        "promoted_at",
        "promoted_by",
        "source_academic_class",
        "target_academic_class",
        "total_candidates",
        "promoted_count",
        "already_registered_count",
    )
    list_filter = (
        "promoted_at",
        "active_students_only",
        "source_academic_class",
        "target_academic_class",
    )
    search_fields = (
        "promoted_by__username",
        "source_academic_class__Class__name",
        "target_academic_class__Class__name",
    )
    readonly_fields = ("promoted_at",)
    
    

@admin.register(StaffAccount)
class StaffAccountAdmin(admin.ModelAdmin):
    list_display = ('staff', 'user', 'role')
    list_filter = ('role',)
    search_fields = ('staff__first_name', 'staff__last_name', 'user__username', 'user__email')

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset.select_related('staff', 'user', 'role')  

    def save_model(self, request, obj, form, change):
    
        super().save_model(request, obj, form, change)  


# Register Classroom model
@admin.register(Classroom)
class ClassroomAdmin(admin.ModelAdmin):
    list_display = ('name', 'location', 'capacity')
    list_filter = ('location',)
    search_fields = ('name', 'location')

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset

# Register TimeSlot model
@admin.register(TimeSlot)
class TimeSlotAdmin(admin.ModelAdmin):
    list_display = ('start_time', 'end_time')
    list_filter = ('start_time', 'end_time')
    search_fields = ('start_time', 'end_time')

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset


@admin.register(AttendanceSession)
class AttendanceSessionAdmin(admin.ModelAdmin):
    list_display = ("class_stream", "subject", "teacher", "date", "time_slot", "is_locked")
    list_filter = ("date", "class_stream", "subject", "teacher", "is_locked")
    search_fields = (
        "class_stream__academic_class__Class__name",
        "class_stream__stream__stream",
        "subject__name",
        "teacher__first_name",
        "teacher__last_name",
    )


@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(admin.ModelAdmin):
    list_display = ("session", "student", "status", "captured_by", "captured_at")
    list_filter = ("status", "captured_at")
    search_fields = ("student__student_name", "session__class_stream__academic_class__Class__name")


@admin.register(AttendancePolicy)
class AttendancePolicyAdmin(admin.ModelAdmin):
    list_display = (
        "minimum_attendance_percent",
        "allow_teacher_edit_locked_sessions",
        "updated_at",
    )

    def has_add_permission(self, request):
        return not AttendancePolicy.objects.exists()


@admin.register(AttendanceAuditLog)
class AttendanceAuditLogAdmin(admin.ModelAdmin):
    list_display = (
        "action",
        "session",
        "record",
        "actor",
        "old_status",
        "new_status",
        "reason",
        "created_at",
    )
    list_filter = ("action", "created_at")
    search_fields = (
        "session__class_stream__academic_class__Class__name",
        "session__subject__name",
        "record__student__student_name",
        "actor__username",
        "reason",
    )
    readonly_fields = (
        "session",
        "record",
        "action",
        "actor",
        "old_status",
        "new_status",
        "reason",
        "details",
        "created_at",
    )


# Register BreakPeriod model
@admin.register(BreakPeriod)
class BreakPeriodAdmin(admin.ModelAdmin):
    list_display = ('weekday', 'name', 'time_slot')
    list_filter = ('weekday',)
    search_fields = ('name', 'time_slot__start_time', 'time_slot__end_time')

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset.select_related('time_slot')

# Register Timetable model
@admin.register(Timetable)
class TimetableAdmin(admin.ModelAdmin):
    list_display = ('class_stream', 'subject', 'teacher', 'weekday', 'time_slot', 'classroom')
    list_filter = ('class_stream', 'weekday', 'time_slot', 'teacher', 'classroom')
    search_fields = ('class_stream__academic_class__Class__name', 'subject__name', 'teacher__first_name', 'teacher__last_name', 'classroom__name')

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset.select_related('class_stream', 'subject', 'teacher', 'classroom')

    def save_model(self, request, obj, form, change):
        # Additional actions before saving the object (if any)
        super().save_model(request, obj, form, change)




@admin.register(ResultModeSetting)
class ResultModeSettingAdmin(admin.ModelAdmin):
    list_display = ('mode',)
    actions = None 

    def has_add_permission(self, request):
        
        return not ResultModeSetting.objects.exists()

    def has_delete_permission(self, request, obj=None):

        return False

    def get_queryset(self, request):

        return ResultModeSetting.objects.all()


@admin.register(ResultVerificationSetting)
class ResultVerificationSettingAdmin(admin.ModelAdmin):
    list_display = (
        'sample_percent', 'tolerance_marks'
    )
    actions = None

    def has_add_permission(self, request):
        return not ResultVerificationSetting.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        return ResultVerificationSetting.objects.all()


@admin.register(ResultBatch)
class ResultBatchAdmin(admin.ModelAdmin):
    list_display = ('assessment', 'status', 'submitted_by', 'submitted_at', 'verified_by', 'verified_at')
    list_filter = ('status', 'assessment__academic_class', 'assessment__assessment_type')
    search_fields = ('assessment__subject__name', 'assessment__academic_class__Class__name')


@admin.register(VerificationSample)
class VerificationSampleAdmin(admin.ModelAdmin):
    list_display = ('result', 'dos_mark', 'matched', 'checked_by', 'checked_at')
    list_filter = ('matched',)
    search_fields = ('result__student__student_name', 'result__student__reg_no')


@admin.register(ResultVerificationNotification)
class ResultVerificationNotificationAdmin(admin.ModelAdmin):
    list_display = ('recipient', 'batch', 'title', 'created_at', 'read')
    list_filter = ('read',)
    search_fields = ('recipient__username', 'title', 'message')




















class ReportResultDetailInline(admin.TabularInline):
    model = ReportResultDetail
    extra = 1 
@admin.register(ReportResults)
class ReportResultsAdmin(admin.ModelAdmin):
    list_display = ('student', 'subject', 'academic_class', 'term', 'term_scores')
    list_filter = ('academic_class', 'term')
    search_fields = ('student__student_name', 'subject__name', 'academic_class__Class__name')
    inlines = [ReportResultDetailInline] 

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset.select_related('student', 'subject', 'academic_class', 'term')

    def term_scores(self, obj):
        total_score, total_points = obj.calculate_term_result()
        return f"{total_score} / {total_points}"
    
    term_scores.short_description = "Total Scores"

# AuditLog Admin (read-only)
from app.models.audit import AuditLog


class SystemEntriesFilter(admin.SimpleListFilter):
    title = "System entries"
    parameter_name = "show_system"

    def lookups(self, request, model_admin):
        return (
            ("hide", "Hide system entries (default)"),
            ("show", "Show system entries"),
        )

    def queryset(self, request, queryset):
        return queryset


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    # Enhanced columns
    list_display = (
        "timestamp",
        "action_badge",
        "actor",
        "model_name",
        "object_short",
        "path_short",
        "changed_fields_summary",
        "ip_address",
        "method",
    )
    list_filter = ("action", "content_type", "user", "method", "ip_address", SystemEntriesFilter)
    search_fields = ("username", "object_repr", "object_id", "path", "ip_address", "user_agent")
    readonly_fields = (
        "timestamp",
        "action",
        "actor",
        "content_type",
        "object_id",
        "object_repr",
        "ip_address",
        "method",
        "path",
        "user",
        "username",
        "user_agent",
        "formatted_changes",
        "formatted_extra",
    )
    date_hierarchy = "timestamp"
    ordering = ("-timestamp",)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        show = request.GET.get("show_system")
        if show != "show":
            qs = qs.exclude(content_type__app_label__in=["sessions", "admin"])
        return qs

    def action_badge(self, obj):
        action = (obj.action or "").lower()
        color = {
            "create": "success",
            "update": "warning",
            "delete": "danger",
            "login": "primary",
            "logout": "secondary",
        }.get(action, "info")
        label = (action or "-").capitalize()
        return format_html('<span class="badge badge-{}">{}</span>', color, label)
    action_badge.short_description = "Action"
    action_badge.admin_order_field = "action"


    def actor(self, obj):
        if obj.user_id and obj.user:
            if obj.username and obj.username != getattr(obj.user, "username", ""):
                return f"{obj.user} ({obj.username})"
            return str(obj.user)
        return obj.username or "-"
    actor.short_description = "Actor"

    # Column: Model (App | Model)
    def model_name(self, obj):
        if obj.content_type_id and obj.content_type:
            return f"{obj.content_type.app_label} | {obj.content_type.name}"
        return "-"
    model_name.short_description = "Content type"
    model_name.admin_order_field = "content_type"

    # Column: Object (short)
    def object_short(self, obj):
        text = obj.object_repr or obj.object_id or "-"
        if text and len(text) > 60:
            return f"{text[:57]}..."
        return text
    object_short.short_description = "Object"

    # Column: Path (short)
    def path_short(self, obj):
        p = obj.path or "-"
        if p != "-" and len(p) > 60:
            return f"{p[:57]}..."
        return p
    path_short.short_description = "Path"
    path_short.admin_order_field = "path"

    # Column: Changed fields summary
    def changed_fields_summary(self, obj):
        data = obj.changes or {}
        try:
            if isinstance(data, dict):
                if "new" in data or "old" in data:
                    # create/delete style payload
                    count = len(data.get("new") or data.get("old") or {})
                    if (obj.action or "").lower() == "create":
                        return f"Created: {count} fields"
                    if (obj.action or "").lower() == "delete":
                        return f"Deleted: {count} fields"
                    return f"{count} fields"
                # update style payload: { field: {old:..., new:...} }
                keys = list(data.keys())
                if not keys:
                    return "-"
                shown = ", ".join(keys[:5])
                more = len(keys) - 5
                return f"{shown}" + (f" +{more} more" if more > 0 else "")
        except Exception:
            pass
        return "-"
    changed_fields_summary.short_description = "Changed fields"

    # Detail: formatted JSON for changes
    def formatted_changes(self, obj):
        try:
            pretty = json.dumps(obj.changes, indent=2, ensure_ascii=False)
        except Exception:
            pretty = str(obj.changes)
        return format_html(
            '<pre style="white-space:pre-wrap;max-width:100%;overflow:auto;margin:0">{}</pre>',
            pretty,
        )
    formatted_changes.short_description = "Changes"

    # Detail: formatted JSON for extra
    def formatted_extra(self, obj):
        try:
            pretty = json.dumps(obj.extra, indent=2, ensure_ascii=False)
        except Exception:
            pretty = str(obj.extra)
        return format_html(
            '<pre style="white-space:pre-wrap;max-width:100%;overflow:auto;margin:0">{}</pre>',
            pretty,
        )
    formatted_extra.short_description = "Extra"

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        # Fully read-only in admin
        return False

    def has_view_permission(self, request, obj=None):
        # Allow staff to view logs
        return request.user.is_active and request.user.is_staff


# Fees and Billing admin registrations

@admin.register(BillItem)
class BillItemAdmin(admin.ModelAdmin):
    list_display = ('item_name', 'category', 'bill_duration')
    search_fields = ('item_name', 'description')
    list_filter = ('category', 'bill_duration')


class StudentBillItemAdminForm(forms.ModelForm):
    class Meta:
        model = StudentBillItem
        fields = ("bill_item", "description", "amount", "charge_date", "fee_category", "notes")
        widgets = {
            "charge_date": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["charge_date"].required = False
        self.fields["fee_category"].required = False
        self.fields["notes"].required = False

    def clean_bill_item(self):
        bill_item = self.cleaned_data.get("bill_item")
        if bill_item:
            return bill_item
        if self.instance and self.instance.pk:
            return self.instance.bill_item
        return bill_item

    def clean_charge_date(self):
        charge_date = self.cleaned_data.get("charge_date")
        if charge_date:
            return charge_date
        if self.instance and self.instance.pk and self.instance.charge_date:
            return self.instance.charge_date
        if self.instance and self.instance.bill_id:
            return self.instance.bill.bill_date
        return charge_date

    def clean_fee_category(self):
        fee_category = self.cleaned_data.get("fee_category")
        if fee_category:
            return fee_category

        bill_item = self.cleaned_data.get("bill_item") or getattr(self.instance, "bill_item", None)
        description = self.cleaned_data.get("description") or getattr(self.instance, "description", "")
        return infer_ledger_category(
            getattr(bill_item, "category", ""),
            getattr(bill_item, "item_name", ""),
            description,
        )

    def clean_notes(self):
        notes = (self.cleaned_data.get("notes") or "").strip()
        if notes:
            return notes
        return self.cleaned_data.get("description") or getattr(self.instance, "description", "")


class StudentBillItemInline(admin.TabularInline):
    model = StudentBillItem
    form = StudentBillItemAdminForm
    extra = 0
    show_change_link = True


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0


@admin.register(StudentBillItem)
class StudentBillItemAdmin(admin.ModelAdmin):
    form = StudentBillItemAdminForm
    list_display = ("bill", "bill_item", "description", "amount", "charge_date", "fee_category")
    list_filter = ("fee_category", "charge_date", "bill__academic_class")
    search_fields = (
        "bill__student__student_name",
        "bill__student__reg_no",
        "bill_item__item_name",
        "description",
        "notes",
    )


@admin.register(StudentBill)
class StudentBillAdmin(admin.ModelAdmin):
    list_display = ('student', 'academic_class', 'bill_date', 'status', 'total_amount', 'amount_paid', 'balance')
    list_filter = ('academic_class', 'status')
    search_fields = ('student__student_name', 'student__reg_no', 'academic_class__Class__name')
    inlines = [StudentBillItemInline, PaymentInline]
    readonly_fields = ('total_amount', 'amount_paid', 'balance')

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset.select_related('student', 'academic_class')


@admin.register(ClassBill)
class ClassBillAdmin(admin.ModelAdmin):
    list_display = ('academic_class', 'bill_item', 'amount')
    list_filter = ('academic_class', 'bill_item')
    search_fields = ('academic_class__name', 'bill_item__item_name')


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('bill', 'payment_date', 'amount', 'payment_method', 'reference_no', 'recorded_by')
    list_filter = ('payment_method', 'payment_date')
    search_fields = ('reference_no', 'recorded_by', 'bill__student__first_name', 'bill__student__last_name')
    readonly_fields = ('bill',)
