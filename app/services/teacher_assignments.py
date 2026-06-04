from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, Sequence

from app.models.classes import AcademicClass, AcademicClassStream, ClassSubjectAllocation, Term
from app.models.school_settings import AcademicYear
from app.models.staffs import Staff
from app.models.subjects import Subject
from app.models.timetables import Timetable


@dataclass(frozen=True)
class TeacherAssignment:
    academic_class_stream: AcademicClassStream
    subject: Subject
    subject_teacher: Staff | None
    source: str

    @property
    def academic_class_stream_id(self) -> int:
        return self.academic_class_stream.id

    @property
    def subject_id(self) -> int:
        return self.subject.id


def _as_ids(values: Iterable[object] | None) -> set[int]:
    if values is None:
        return set()
    ids: set[int] = set()
    for value in values:
        if isinstance(value, int):
            ids.add(value)
            continue
        pk = getattr(value, "pk", None)
        if pk:
            ids.add(int(pk))
    return ids


def _apply_timetable_filters(
    queryset,
    *,
    current_year: AcademicYear | None = None,
    current_term: Term | None = None,
    academic_classes: Sequence[AcademicClass] | None = None,
    class_streams: Sequence[AcademicClassStream] | None = None,
    class_stream_ids: set[int] | None = None,
    subject_ids: set[int] | None = None,
):
    if current_year:
        queryset = queryset.filter(class_stream__academic_class__academic_year=current_year)
    if current_term:
        queryset = queryset.filter(class_stream__academic_class__term=current_term)
    if academic_classes is not None:
        queryset = queryset.filter(class_stream__academic_class__in=academic_classes)
    if class_streams is not None:
        queryset = queryset.filter(class_stream__in=class_streams)
    if class_stream_ids:
        queryset = queryset.filter(class_stream_id__in=class_stream_ids)
    if subject_ids:
        queryset = queryset.filter(subject_id__in=subject_ids)
    return queryset


def _apply_allocation_filters(
    queryset,
    *,
    current_year: AcademicYear | None = None,
    current_term: Term | None = None,
    academic_classes: Sequence[AcademicClass] | None = None,
    class_streams: Sequence[AcademicClassStream] | None = None,
    class_stream_ids: set[int] | None = None,
    subject_ids: set[int] | None = None,
):
    if current_year:
        queryset = queryset.filter(academic_class_stream__academic_class__academic_year=current_year)
    if current_term:
        queryset = queryset.filter(academic_class_stream__academic_class__term=current_term)
    if academic_classes is not None:
        queryset = queryset.filter(academic_class_stream__academic_class__in=academic_classes)
    if class_streams is not None:
        queryset = queryset.filter(academic_class_stream__in=class_streams)
    if class_stream_ids:
        queryset = queryset.filter(academic_class_stream_id__in=class_stream_ids)
    if subject_ids:
        queryset = queryset.filter(subject_id__in=subject_ids)
    return queryset


def get_teacher_assignments(
    staff: Staff,
    *,
    current_year: AcademicYear | None = None,
    current_term: Term | None = None,
    academic_classes: Sequence[AcademicClass] | None = None,
    class_streams: Sequence[AcademicClassStream] | None = None,
) -> list[TeacherAssignment]:
    """
    Return teacher assignments from a timetable-first source with allocation fallback.
    This allows gradual migration away from direct ClassSubjectAllocation reads.
    """
    assignment_map: dict[tuple[int, int], TeacherAssignment] = {}

    timetable_rows = _apply_timetable_filters(
        Timetable.objects.filter(teacher=staff).select_related(
            "class_stream__academic_class__Class",
            "class_stream__academic_class__academic_year",
            "class_stream__academic_class__term",
            "class_stream__stream",
            "subject",
            "teacher",
        ),
        current_year=current_year,
        current_term=current_term,
        academic_classes=academic_classes,
        class_streams=class_streams,
    ).order_by(
        "class_stream__academic_class__Class__name",
        "class_stream__stream__stream",
        "subject__name",
        "weekday",
        "time_slot__start_time",
    )
    for lesson in timetable_rows:
        key = (lesson.class_stream_id, lesson.subject_id)
        if key in assignment_map:
            continue
        assignment_map[key] = TeacherAssignment(
            academic_class_stream=lesson.class_stream,
            subject=lesson.subject,
            subject_teacher=lesson.teacher,
            source="timetable",
        )

    allocation_rows = _apply_allocation_filters(
        ClassSubjectAllocation.objects.filter(subject_teacher=staff).select_related(
            "academic_class_stream__academic_class__Class",
            "academic_class_stream__academic_class__academic_year",
            "academic_class_stream__academic_class__term",
            "academic_class_stream__stream",
            "subject",
            "subject_teacher",
        ),
        current_year=current_year,
        current_term=current_term,
        academic_classes=academic_classes,
        class_streams=class_streams,
    ).order_by(
        "academic_class_stream__academic_class__Class__name",
        "academic_class_stream__stream__stream",
        "subject__name",
    )
    for allocation in allocation_rows:
        key = (allocation.academic_class_stream_id, allocation.subject_id)
        if key in assignment_map:
            continue
        assignment_map[key] = TeacherAssignment(
            academic_class_stream=allocation.academic_class_stream,
            subject=allocation.subject,
            subject_teacher=allocation.subject_teacher,
            source="allocation",
        )

    return sorted(
        assignment_map.values(),
        key=lambda row: (
            row.academic_class_stream.academic_class.Class.name,
            row.academic_class_stream.stream.stream,
            row.subject.name,
        ),
    )


def get_class_stream_assignments(
    class_streams: Sequence[AcademicClassStream],
    *,
    current_year: AcademicYear | None = None,
    current_term: Term | None = None,
    academic_classes: Sequence[AcademicClass] | None = None,
) -> list[TeacherAssignment]:
    """
    Return class-stream subject-teacher assignments for class-teacher and reporting flows.
    Timetable rows with assigned teachers are preferred; allocations backfill any gaps.
    """
    class_stream_ids = _as_ids(class_streams)
    if not class_stream_ids:
        return []

    assignment_map: dict[tuple[int, int], TeacherAssignment] = {}
    timetable_rows = _apply_timetable_filters(
        Timetable.objects.filter(
            class_stream_id__in=class_stream_ids,
            teacher_id__isnull=False,
        ).select_related(
            "class_stream__academic_class__Class",
            "class_stream__academic_class__academic_year",
            "class_stream__academic_class__term",
            "class_stream__stream",
            "subject",
            "teacher",
        ),
        current_year=current_year,
        current_term=current_term,
        academic_classes=academic_classes,
        class_stream_ids=class_stream_ids,
    ).order_by(
        "class_stream__academic_class__Class__name",
        "class_stream__stream__stream",
        "subject__name",
        "weekday",
        "time_slot__start_time",
    )
    for lesson in timetable_rows:
        key = (lesson.class_stream_id, lesson.subject_id)
        if key in assignment_map:
            continue
        assignment_map[key] = TeacherAssignment(
            academic_class_stream=lesson.class_stream,
            subject=lesson.subject,
            subject_teacher=lesson.teacher,
            source="timetable",
        )

    allocation_rows = _apply_allocation_filters(
        ClassSubjectAllocation.objects.filter(
            academic_class_stream_id__in=class_stream_ids
        ).select_related(
            "academic_class_stream__academic_class__Class",
            "academic_class_stream__academic_class__academic_year",
            "academic_class_stream__academic_class__term",
            "academic_class_stream__stream",
            "subject",
            "subject_teacher",
        ),
        current_year=current_year,
        current_term=current_term,
        academic_classes=academic_classes,
        class_stream_ids=class_stream_ids,
    ).order_by(
        "academic_class_stream__academic_class__Class__name",
        "academic_class_stream__stream__stream",
        "subject__name",
    )
    for allocation in allocation_rows:
        key = (allocation.academic_class_stream_id, allocation.subject_id)
        if key in assignment_map:
            continue
        assignment_map[key] = TeacherAssignment(
            academic_class_stream=allocation.academic_class_stream,
            subject=allocation.subject,
            subject_teacher=allocation.subject_teacher,
            source="allocation",
        )

    return sorted(
        assignment_map.values(),
        key=lambda row: (
            row.academic_class_stream.academic_class.Class.name,
            row.academic_class_stream.stream.stream,
            row.subject.name,
        ),
    )


def get_teacher_ids_for_class_streams(
    class_stream_ids: Sequence[int] | Sequence[AcademicClassStream],
    *,
    current_year: AcademicYear | None = None,
    current_term: Term | None = None,
) -> set[int]:
    ids = _as_ids(class_stream_ids)
    if not ids:
        return set()

    timetable_qs = _apply_timetable_filters(
        Timetable.objects.filter(class_stream_id__in=ids, teacher_id__isnull=False),
        current_year=current_year,
        current_term=current_term,
        class_stream_ids=ids,
    )
    allocation_qs = _apply_allocation_filters(
        ClassSubjectAllocation.objects.filter(academic_class_stream_id__in=ids),
        current_year=current_year,
        current_term=current_term,
        class_stream_ids=ids,
    )

    teacher_ids = set(timetable_qs.values_list("teacher_id", flat=True))
    teacher_ids.update(
        allocation_qs.values_list("subject_teacher_id", flat=True)
    )
    teacher_ids.discard(None)
    return {int(value) for value in teacher_ids}


def get_class_subject_teacher_rows(
    *,
    class_ids: Sequence[int],
    subject_ids: Sequence[int],
    current_year: AcademicYear | None = None,
    current_term: Term | None = None,
) -> list[dict]:
    """
    Rows used for teacher-performance mapping:
    {academic_class_id, subject_id, teacher_id, teacher_name}
    """
    class_id_set = _as_ids(class_ids)
    subject_id_set = _as_ids(subject_ids)
    if not class_id_set or not subject_id_set:
        return []

    row_map: dict[tuple[int, int, int], dict] = {}
    timetable_rows = _apply_timetable_filters(
        Timetable.objects.filter(
            class_stream__academic_class_id__in=class_id_set,
            subject_id__in=subject_id_set,
            teacher_id__isnull=False,
        ).select_related("class_stream__academic_class", "teacher"),
        current_year=current_year,
        current_term=current_term,
        subject_ids=subject_id_set,
    ).values(
        "class_stream__academic_class_id",
        "subject_id",
        "teacher_id",
        "teacher__first_name",
        "teacher__last_name",
    )
    for row in timetable_rows:
        teacher_id = row["teacher_id"]
        key = (row["class_stream__academic_class_id"], row["subject_id"], teacher_id)
        if key in row_map:
            continue
        full_name = f"{row['teacher__first_name']} {row['teacher__last_name']}".strip()
        row_map[key] = {
            "academic_class_id": row["class_stream__academic_class_id"],
            "subject_id": row["subject_id"],
            "teacher_id": teacher_id,
            "teacher_name": full_name or "Unknown",
        }

    allocation_rows = _apply_allocation_filters(
        ClassSubjectAllocation.objects.filter(
            academic_class_stream__academic_class_id__in=class_id_set,
            subject_id__in=subject_id_set,
        ).values(
            "academic_class_stream__academic_class_id",
            "subject_id",
            "subject_teacher_id",
            "subject_teacher__first_name",
            "subject_teacher__last_name",
        ),
        current_year=current_year,
        current_term=current_term,
        subject_ids=subject_id_set,
    )
    for row in allocation_rows:
        teacher_id = row["subject_teacher_id"]
        if not teacher_id:
            continue
        key = (
            row["academic_class_stream__academic_class_id"],
            row["subject_id"],
            teacher_id,
        )
        if key in row_map:
            continue
        full_name = (
            f"{row['subject_teacher__first_name']} {row['subject_teacher__last_name']}"
        ).strip()
        row_map[key] = {
            "academic_class_id": row["academic_class_stream__academic_class_id"],
            "subject_id": row["subject_id"],
            "teacher_id": teacher_id,
            "teacher_name": full_name or "Unknown",
        }

    return list(row_map.values())


def get_allocation_queryset(
    *,
    teacher: Staff | None = None,
    current_year: AcademicYear | None = None,
    current_term: Term | None = None,
    academic_classes: Sequence[AcademicClass] | None = None,
    class_streams: Sequence[AcademicClassStream] | None = None,
    class_stream_ids: Sequence[int] | None = None,
    subject_ids: Sequence[int] | None = None,
):
    stream_id_set = _as_ids(class_stream_ids)
    subject_id_set = _as_ids(subject_ids)

    queryset = ClassSubjectAllocation.objects.all()
    if teacher is not None:
        queryset = queryset.filter(subject_teacher=teacher)
    queryset = _apply_allocation_filters(
        queryset,
        current_year=current_year,
        current_term=current_term,
        academic_classes=academic_classes,
        class_streams=class_streams,
        class_stream_ids=stream_id_set,
        subject_ids=subject_id_set,
    )
    return queryset.select_related(
        "academic_class_stream__academic_class__Class",
        "academic_class_stream__academic_class__academic_year",
        "academic_class_stream__academic_class__term",
        "academic_class_stream__stream",
        "subject",
        "subject_teacher",
    ).order_by(
        "academic_class_stream__academic_class__Class__name",
        "academic_class_stream__stream__stream",
        "subject__name",
    )


def upsert_class_subject_allocation(
    *,
    class_stream: AcademicClassStream,
    subject: Subject,
    subject_teacher: Staff,
):
    return ClassSubjectAllocation.objects.update_or_create(
        academic_class_stream=class_stream,
        subject=subject,
        defaults={"subject_teacher": subject_teacher},
    )


def save_class_subject_allocation(
    allocation: ClassSubjectAllocation,
    *,
    class_stream: AcademicClassStream,
    subject: Subject,
    subject_teacher: Staff,
):
    allocation.academic_class_stream = class_stream
    allocation.subject = subject
    allocation.subject_teacher = subject_teacher
    allocation.save()
    return allocation


def delete_class_subject_allocation_record(allocation: ClassSubjectAllocation):
    allocation.delete()


def copy_allocations_for_term_transition(
    *,
    previous_class_streams: Sequence[AcademicClassStream],
    current_class_streams: Sequence[AcademicClassStream],
):
    previous_allocations = list(get_allocation_queryset(class_streams=previous_class_streams))
    by_class_and_stream = defaultdict(list)
    for alloc in previous_allocations:
        key = (
            alloc.academic_class_stream.academic_class.Class_id,
            alloc.academic_class_stream.stream_id,
        )
        by_class_and_stream[key].append(alloc)

    created_count = 0
    skipped_count = 0
    errors: list[str] = []

    for current_stream in current_class_streams:
        key = (
            current_stream.academic_class.Class_id,
            current_stream.stream_id,
        )
        for prev_alloc in by_class_and_stream.get(key, []):
            try:
                _, created = ClassSubjectAllocation.objects.get_or_create(
                    academic_class_stream=current_stream,
                    subject=prev_alloc.subject,
                    defaults={"subject_teacher": prev_alloc.subject_teacher},
                )
                if created:
                    created_count += 1
                else:
                    skipped_count += 1
            except Exception as exc:  # pragma: no cover - defensive guard for DB edge cases
                message = str(exc)
                if "Duplicate entry" in message or "UNIQUE constraint" in message:
                    skipped_count += 1
                else:
                    errors.append(message)

    return {
        "created_count": created_count,
        "skipped_count": skipped_count,
        "errors": errors,
    }
