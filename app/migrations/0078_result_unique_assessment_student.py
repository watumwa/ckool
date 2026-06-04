from django.db import migrations, models
from django.db.models import Count


STATUS_PRIORITY = {
    "DRAFT": 1,
    "PENDING": 2,
    "FLAGGED": 3,
    "VERIFIED": 4,
}


def dedupe_results_for_unique_constraint(apps, schema_editor):
    Result = apps.get_model("app", "Result")
    VerificationSample = apps.get_model("app", "VerificationSample")
    VerificationDiscrepancy = apps.get_model("app", "VerificationDiscrepancy")
    VerificationCorrectionLog = apps.get_model("app", "VerificationCorrectionLog")
    db_alias = schema_editor.connection.alias

    duplicate_groups = (
        Result.objects.using(db_alias)
        .values("assessment_id", "student_id")
        .annotate(row_count=Count("id"))
        .filter(row_count__gt=1)
    )

    for group in duplicate_groups:
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

        keep_sample = VerificationSample.objects.using(db_alias).filter(result_id=keep_row.id).first()

        for row in rows[1:]:
            VerificationCorrectionLog.objects.using(db_alias).filter(result_id=row.id).update(
                result_id=keep_row.id
            )

            row_sample = VerificationSample.objects.using(db_alias).filter(result_id=row.id).first()
            if row_sample:
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

            VerificationDiscrepancy.objects.using(db_alias).filter(result_id=row.id).update(
                result_id=keep_row.id
            )
            row.delete()


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0077_academicclassstream_is_timetable_locked"),
    ]

    operations = [
        migrations.RunPython(dedupe_results_for_unique_constraint, noop_reverse),
        migrations.AddConstraint(
            model_name="result",
            constraint=models.UniqueConstraint(
                fields=("assessment", "student"),
                name="uniq_result_assessment_student",
            ),
        ),
    ]
