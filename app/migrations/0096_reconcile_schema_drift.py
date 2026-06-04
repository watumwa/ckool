from django.db import migrations
from django.db.models import Count


STATUS_PRIORITY = {
    "DRAFT": 1,
    "PENDING": 2,
    "FLAGGED": 3,
    "VERIFIED": 4,
}


def _table_exists(connection, table_name):
    with connection.cursor() as cursor:
        return table_name in connection.introspection.table_names(cursor)


def _column_names(connection, table_name):
    with connection.cursor() as cursor:
        description = connection.introspection.get_table_description(cursor, table_name)
    return {col.name for col in description}


def _has_unique_assessment_student_constraint(connection, table_name):
    with connection.cursor() as cursor:
        constraints = connection.introspection.get_constraints(cursor, table_name)

    for name, info in constraints.items():
        columns = info.get("columns") or []
        if name == "uniq_result_assessment_student" and info.get("unique"):
            return True
        if info.get("unique") and columns == ["assessment_id", "student_id"]:
            return True
    return False


def _backfill_timetable_allocations(apps, schema_editor):
    Timetable = apps.get_model("app", "Timetable")
    ClassSubjectAllocation = apps.get_model("app", "ClassSubjectAllocation")
    db_alias = schema_editor.connection.alias

    allocation_rows = ClassSubjectAllocation.objects.using(db_alias).values(
        "id",
        "academic_class_stream_id",
        "subject_id",
        "subject_teacher_id",
    )

    by_stream_subject = {}
    by_stream_subject_teacher = {}
    for row in allocation_rows.iterator(chunk_size=500):
        stream_subject_key = (row["academic_class_stream_id"], row["subject_id"])
        by_stream_subject[stream_subject_key] = row
        by_stream_subject_teacher[(
            row["academic_class_stream_id"],
            row["subject_id"],
            row["subject_teacher_id"],
        )] = row

    lessons = Timetable.objects.using(db_alias).filter(allocation_id__isnull=True)
    for lesson in lessons.iterator(chunk_size=500):
        allocation = None
        if lesson.teacher_id:
            allocation = by_stream_subject_teacher.get(
                (lesson.class_stream_id, lesson.subject_id, lesson.teacher_id)
            )
        if allocation is None:
            allocation = by_stream_subject.get((lesson.class_stream_id, lesson.subject_id))
        if allocation is None:
            continue

        updates = {"allocation_id": allocation["id"]}
        if lesson.teacher_id != allocation["subject_teacher_id"]:
            updates["teacher_id"] = allocation["subject_teacher_id"]

        Timetable.objects.using(db_alias).filter(pk=lesson.pk).update(**updates)


def _dedupe_results(apps, schema_editor):
    connection = schema_editor.connection
    db_alias = connection.alias

    Result = apps.get_model("app", "Result")
    VerificationSample = apps.get_model("app", "VerificationSample")
    VerificationDiscrepancy = apps.get_model("app", "VerificationDiscrepancy")
    VerificationCorrectionLog = apps.get_model("app", "VerificationCorrectionLog")

    sample_table_exists = _table_exists(connection, VerificationSample._meta.db_table)
    discrepancy_table_exists = _table_exists(connection, VerificationDiscrepancy._meta.db_table)
    correction_log_table_exists = _table_exists(connection, VerificationCorrectionLog._meta.db_table)

    duplicate_groups = (
        Result.objects.using(db_alias)
        .values("assessment_id", "student_id")
        .annotate(row_count=Count("id"))
        .filter(row_count__gt=1)
    )

    for group in duplicate_groups.iterator(chunk_size=200):
        rows = list(
            Result.objects.using(db_alias)
            .filter(
                assessment_id=group["assessment_id"],
                student_id=group["student_id"],
            )
            .order_by("-id")
        )
        if len(rows) <= 1:
            continue

        keep_row = rows[0]
        strongest_row = max(
            rows,
            key=lambda item: (
                STATUS_PRIORITY.get((item.status or "").upper(), 0),
                int(item.batch_id is not None),
                item.id,
            ),
        )

        update_fields = []
        strongest_status = strongest_row.status
        if strongest_status:
            strongest_rank = STATUS_PRIORITY.get((strongest_status or "").upper(), 0)
            keep_rank = STATUS_PRIORITY.get((keep_row.status or "").upper(), 0)
            if strongest_rank > keep_rank:
                keep_row.status = strongest_status
                update_fields.append("status")

        if keep_row.batch_id is None and strongest_row.batch_id is not None:
            keep_row.batch_id = strongest_row.batch_id
            update_fields.append("batch")

        if update_fields:
            keep_row.save(update_fields=update_fields)

        keep_sample = None
        if sample_table_exists:
            keep_sample = VerificationSample.objects.using(db_alias).filter(result_id=keep_row.id).first()

        for row in rows[1:]:
            if correction_log_table_exists:
                VerificationCorrectionLog.objects.using(db_alias).filter(result_id=row.id).update(
                    result_id=keep_row.id
                )

            row_sample = None
            if sample_table_exists:
                row_sample = VerificationSample.objects.using(db_alias).filter(result_id=row.id).first()

            if row_sample and discrepancy_table_exists:
                if keep_sample is None:
                    VerificationDiscrepancy.objects.using(db_alias).filter(sample_id=row_sample.id).update(
                        result_id=keep_row.id
                    )
                    row_sample.result_id = keep_row.id
                    row_sample.save(update_fields=["result"])
                    keep_sample = row_sample
                else:
                    VerificationDiscrepancy.objects.using(db_alias).filter(sample_id=row_sample.id).delete()
                    row_sample.delete()
            elif row_sample and keep_sample is None:
                row_sample.result_id = keep_row.id
                row_sample.save(update_fields=["result"])
                keep_sample = row_sample
            elif row_sample:
                row_sample.delete()

            if discrepancy_table_exists:
                VerificationDiscrepancy.objects.using(db_alias).filter(result_id=row.id).update(
                    result_id=keep_row.id
                )
            row.delete()


def reconcile_schema_drift(apps, schema_editor):
    connection = schema_editor.connection

    Timetable = apps.get_model("app", "Timetable")
    Result = apps.get_model("app", "Result")
    ClassSubjectAllocation = apps.get_model("app", "ClassSubjectAllocation")

    timetable_table = Timetable._meta.db_table
    result_table = Result._meta.db_table

    if _table_exists(connection, timetable_table):
        columns = _column_names(connection, timetable_table)
        if "allocation_id" not in columns:
            allocation_field = Timetable._meta.get_field("allocation")
            schema_editor.add_field(Timetable, allocation_field)

        if _table_exists(connection, ClassSubjectAllocation._meta.db_table):
            _backfill_timetable_allocations(apps, schema_editor)

    if _table_exists(connection, result_table):
        _dedupe_results(apps, schema_editor)

        if not _has_unique_assessment_student_constraint(connection, result_table):
            constraint = next(
                c for c in Result._meta.constraints if c.name == "uniq_result_assessment_student"
            )
            schema_editor.add_constraint(Result, constraint)


def noop_reverse(apps, schema_editor):
    return


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0095_alter_role_name"),
    ]

    operations = [
        migrations.RunPython(reconcile_schema_drift, reverse_code=noop_reverse),
    ]
