from django.db.models import Q

from app.models.classes import AcademicClass, AcademicClassStream, Class
from app.models.school_settings import SchoolSetting, Section
from app.models.students import Student
from app.models.subjects import Subject
from app.services.school_level import get_active_school_level


def _resolve_active_level(request=None, active_level=None):
    if active_level:
        return active_level
    if request is not None:
        return get_active_school_level(request)
    return SchoolSetting.EducationLevel.PRIMARY


def _is_secondary_level(active_level):
    return active_level in {
        SchoolSetting.EducationLevel.SECONDARY_LOWER,
        SchoolSetting.EducationLevel.SECONDARY_UPPER,
    }


def _class_level_filter(active_level, field_prefix=""):
    if not _is_secondary_level(active_level):
        return None

    if active_level == SchoolSetting.EducationLevel.SECONDARY_LOWER:
        code_values = ["S1", "S2", "S3", "S4", "O1", "O2", "O3", "O4"]
        name_values = [
            "Senior 1",
            "Senior 2",
            "Senior 3",
            "Senior 4",
            "S1",
            "S2",
            "S3",
            "S4",
            "O-Level",
            "O level",
        ]
    else:
        code_values = ["S5", "S6", "A1", "A2"]
        name_values = [
            "Senior 5",
            "Senior 6",
            "S5",
            "S6",
            "A-Level",
            "A level",
        ]

    level_filter = Q(**{f"{field_prefix}code__in": code_values})
    for name in name_values:
        level_filter |= Q(**{f"{field_prefix}name__icontains": name})
    return level_filter


def _subject_level_filter(active_level, field_prefix=""):
    if not _is_secondary_level(active_level):
        return None

    if active_level == SchoolSetting.EducationLevel.SECONDARY_LOWER:
        code_hints = ["S1", "S2", "S3", "S4", "O"]
        name_hints = [
            "Senior 1",
            "Senior 2",
            "Senior 3",
            "Senior 4",
            "S1",
            "S2",
            "S3",
            "S4",
            "O-Level",
            "O level",
        ]
    else:
        code_hints = ["S5", "S6", "A"]
        name_hints = [
            "Senior 5",
            "Senior 6",
            "S5",
            "S6",
            "A-Level",
            "A level",
        ]

    level_filter = Q(**{f"{field_prefix}code__icontains": code_hints[0]})
    for code_hint in code_hints[1:]:
        level_filter |= Q(**{f"{field_prefix}code__icontains": code_hint})
    for name_hint in name_hints:
        level_filter |= Q(**{f"{field_prefix}name__icontains": name_hint})
    return level_filter


def get_level_sections_queryset(*, request=None, active_level=None):
    active_level = _resolve_active_level(request=request, active_level=active_level)
    sections = Section.objects.all().order_by("section_name")
    secondary_sections = sections.filter(Section.secondary_filter())

    if _is_secondary_level(active_level):
        if secondary_sections.exists():
            return secondary_sections
        return sections

    primary_sections = sections.exclude(Section.secondary_filter())
    if primary_sections.exists():
        return primary_sections

    return sections


def get_level_classes_queryset(*, request=None, active_level=None):
    active_level = _resolve_active_level(request=request, active_level=active_level)
    queryset = Class.objects.filter(
        section__in=get_level_sections_queryset(active_level=active_level)
    ).order_by("name")
    class_filter = _class_level_filter(active_level)
    if class_filter is None:
        return queryset

    if active_level == SchoolSetting.EducationLevel.SECONDARY_UPPER:
        generic_section_ids = list(
            get_level_sections_queryset(active_level=active_level)
            .filter(Section.generic_secondary_filter())
            .values_list("id", flat=True)
        )
        if not generic_section_ids:
            return queryset
        generic_classes = queryset.filter(section_id__in=generic_section_ids).filter(class_filter)
        non_generic_classes = queryset.exclude(section_id__in=generic_section_ids)
        merged = (generic_classes | non_generic_classes).distinct()
        return merged if merged.exists() else queryset

    filtered = queryset.filter(class_filter)
    return filtered if filtered.exists() else queryset


def get_level_academic_classes_queryset(*, request=None, active_level=None):
    active_level = _resolve_active_level(request=request, active_level=active_level)
    queryset = (
        AcademicClass.objects.filter(
            section__in=get_level_sections_queryset(active_level=active_level)
        )
        .select_related("Class", "academic_year", "term", "section")
        .order_by("-academic_year__academic_year", "-term__start_date", "Class__name")
    )
    class_filter = _class_level_filter(active_level, field_prefix="Class__")
    if class_filter is None:
        return queryset

    if active_level == SchoolSetting.EducationLevel.SECONDARY_UPPER:
        generic_section_ids = list(
            get_level_sections_queryset(active_level=active_level)
            .filter(Section.generic_secondary_filter())
            .values_list("id", flat=True)
        )
        if not generic_section_ids:
            return queryset
        generic_classes = queryset.filter(section_id__in=generic_section_ids).filter(class_filter)
        non_generic_classes = queryset.exclude(section_id__in=generic_section_ids)
        merged = (generic_classes | non_generic_classes).distinct()
        return merged if merged.exists() else queryset

    filtered = queryset.filter(class_filter)
    return filtered if filtered.exists() else queryset


def get_level_class_streams_queryset(*, request=None, active_level=None):
    return AcademicClassStream.objects.filter(
        academic_class__in=get_level_academic_classes_queryset(
            request=request,
            active_level=active_level,
        )
    ).select_related("academic_class", "stream", "class_teacher")


def get_level_subjects_queryset(*, request=None, active_level=None):
    active_level = _resolve_active_level(request=request, active_level=active_level)
    queryset = Subject.objects.filter(
        section__in=get_level_sections_queryset(request=request, active_level=active_level)
    ).order_by("name")
    subject_filter = _subject_level_filter(active_level)
    if subject_filter is None:
        return queryset
    filtered = queryset.filter(subject_filter)
    return filtered if filtered.exists() else queryset


def get_level_students_queryset(*, request=None, active_level=None):
    active_level = _resolve_active_level(request=request, active_level=active_level)
    class_ids = get_level_classes_queryset(active_level=active_level).values_list("id", flat=True)
    queryset = Student.objects.filter(current_class_id__in=class_ids).order_by("student_name")
    if queryset.exists():
        return queryset
    return Student.objects.filter(
        current_class__section__in=get_level_sections_queryset(active_level=active_level)
    ).order_by("student_name")


def bind_form_level_querysets(form, *, request=None, active_level=None):
    sections = get_level_sections_queryset(request=request, active_level=active_level)
    classes = get_level_classes_queryset(request=request, active_level=active_level)
    academic_classes = get_level_academic_classes_queryset(request=request, active_level=active_level)
    class_streams = get_level_class_streams_queryset(request=request, active_level=active_level)
    subjects = get_level_subjects_queryset(request=request, active_level=active_level)
    students = get_level_students_queryset(request=request, active_level=active_level)

    if "section" in form.fields:
        form.fields["section"].queryset = sections
    if "current_class" in form.fields:
        form.fields["current_class"].queryset = classes
    if "Class" in form.fields:
        form.fields["Class"].queryset = classes
    if "academic_class" in form.fields:
        form.fields["academic_class"].queryset = academic_classes
    if "academic_class_stream" in form.fields:
        form.fields["academic_class_stream"].queryset = class_streams
    if "subject" in form.fields:
        form.fields["subject"].queryset = subjects
    if "student" in form.fields:
        form.fields["student"].queryset = students
