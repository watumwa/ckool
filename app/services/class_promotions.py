from __future__ import annotations

from dataclasses import dataclass, field

from django.db import transaction

from app.models.classes import (
    AcademicClass,
    AcademicClassStream,
    StudentPromotionHistory,
)
from app.models.students import ClassRegister


@dataclass
class PromotionOutcome:
    total_candidates: int = 0
    promoted_count: int = 0
    already_registered_count: int = 0
    skipped_inactive_count: int = 0
    skipped_duplicate_source_count: int = 0
    updated_student_snapshots: int = 0
    missing_stream_names: tuple[str, ...] = field(default_factory=tuple)

    @property
    def has_missing_streams(self) -> bool:
        return bool(self.missing_stream_names)


def promote_students_to_academic_class(
    *,
    source_academic_class: AcademicClass,
    target_academic_class: AcademicClass,
    source_stream: AcademicClassStream | None = None,
    active_students_only: bool = True,
    student_ids: list[int] | tuple[int, ...] | set[int] | None = None,
    promoted_by=None,
    log_history: bool = True,
) -> PromotionOutcome:
    if source_academic_class.id == target_academic_class.id:
        raise ValueError("Target academic class must be different from source class.")
    if source_stream and source_stream.academic_class_id != source_academic_class.id:
        raise ValueError("Selected source stream does not belong to the source academic class.")

    source_registers = ClassRegister.objects.filter(
        academic_class_stream__academic_class=source_academic_class
    ).select_related(
        "student",
        "academic_class_stream__stream",
    )
    if student_ids is not None:
        selected_ids = set()
        for student_id in student_ids:
            if student_id is None:
                continue
            try:
                selected_ids.add(int(student_id))
            except (TypeError, ValueError):
                continue
        if not selected_ids:
            outcome = PromotionOutcome()
            _create_promotion_history(
                source_academic_class=source_academic_class,
                target_academic_class=target_academic_class,
                source_stream=source_stream,
                active_students_only=active_students_only,
                outcome=outcome,
                promoted_by=promoted_by,
                enabled=log_history,
            )
            return outcome
        source_registers = source_registers.filter(student_id__in=selected_ids)
    if source_stream:
        source_registers = source_registers.filter(academic_class_stream=source_stream)

    outcome = PromotionOutcome()
    if active_students_only:
        outcome.skipped_inactive_count = (
            source_registers.filter(student__is_active=False)
            .values("student_id")
            .distinct()
            .count()
        )
        source_registers = source_registers.filter(student__is_active=True)

    source_register_rows = list(source_registers.order_by("student_id", "id"))
    source_pairs = {
        (row.student_id, row.academic_class_stream.stream_id)
        for row in source_register_rows
    }
    outcome.total_candidates = len(source_pairs)
    if not source_register_rows:
        _create_promotion_history(
            source_academic_class=source_academic_class,
            target_academic_class=target_academic_class,
            source_stream=source_stream,
            active_students_only=active_students_only,
            outcome=outcome,
            promoted_by=promoted_by,
            enabled=log_history,
        )
        return outcome

    target_streams = {
        class_stream.stream_id: class_stream
        for class_stream in AcademicClassStream.objects.filter(
            academic_class=target_academic_class
        ).select_related("stream")
    }

    missing_stream_names = sorted(
        {
            row.academic_class_stream.stream.stream
            for row in source_register_rows
            if row.academic_class_stream.stream_id not in target_streams
        }
    )
    if missing_stream_names:
        outcome.missing_stream_names = tuple(missing_stream_names)
        _create_promotion_history(
            source_academic_class=source_academic_class,
            target_academic_class=target_academic_class,
            source_stream=source_stream,
            active_students_only=active_students_only,
            outcome=outcome,
            promoted_by=promoted_by,
            enabled=log_history,
        )
        return outcome

    processed_pairs: set[tuple[int, int]] = set()
    with transaction.atomic():
        for source_register in source_register_rows:
            destination_stream = target_streams[source_register.academic_class_stream.stream_id]
            destination_key = (source_register.student_id, destination_stream.id)
            if destination_key in processed_pairs:
                outcome.skipped_duplicate_source_count += 1
                continue
            processed_pairs.add(destination_key)

            _, created = ClassRegister.objects.get_or_create(
                academic_class_stream=destination_stream,
                student=source_register.student,
            )
            if created:
                outcome.promoted_count += 1
            else:
                outcome.already_registered_count += 1

            student = source_register.student
            update_fields: list[str] = []
            if student.current_class_id != target_academic_class.Class_id:
                student.current_class_id = target_academic_class.Class_id
                update_fields.append("current_class")
            if student.stream_id != destination_stream.stream_id:
                student.stream_id = destination_stream.stream_id
                update_fields.append("stream")
            if student.academic_year_id != target_academic_class.academic_year_id:
                student.academic_year_id = target_academic_class.academic_year_id
                update_fields.append("academic_year")
            if student.term_id != target_academic_class.term_id:
                student.term_id = target_academic_class.term_id
                update_fields.append("term")

            if update_fields:
                student.save(update_fields=update_fields)
                outcome.updated_student_snapshots += 1

    _create_promotion_history(
        source_academic_class=source_academic_class,
        target_academic_class=target_academic_class,
        source_stream=source_stream,
        active_students_only=active_students_only,
        outcome=outcome,
        promoted_by=promoted_by,
        enabled=log_history,
    )

    return outcome


def _create_promotion_history(
    *,
    source_academic_class: AcademicClass,
    target_academic_class: AcademicClass,
    source_stream: AcademicClassStream | None,
    active_students_only: bool,
    outcome: PromotionOutcome,
    promoted_by,
    enabled: bool,
):
    if not enabled:
        return

    if promoted_by and not getattr(promoted_by, "is_authenticated", False):
        promoted_by = None

    StudentPromotionHistory.objects.create(
        source_academic_class=source_academic_class,
        target_academic_class=target_academic_class,
        source_stream=source_stream,
        promoted_by=promoted_by,
        active_students_only=active_students_only,
        total_candidates=outcome.total_candidates,
        promoted_count=outcome.promoted_count,
        already_registered_count=outcome.already_registered_count,
        skipped_inactive_count=outcome.skipped_inactive_count,
        skipped_duplicate_source_count=outcome.skipped_duplicate_source_count,
        updated_student_snapshots=outcome.updated_student_snapshots,
        missing_stream_names=list(outcome.missing_stream_names),
    )
