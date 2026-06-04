from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count

from app.models.results import (
    Result,
    VerificationCorrectionLog,
    VerificationDiscrepancy,
    VerificationSample,
)


STATUS_PRIORITY = {
    "DRAFT": 1,
    "PENDING": 2,
    "FLAGGED": 3,
    "VERIFIED": 4,
}


class Command(BaseCommand):
    help = (
        "Detect and merge duplicate Result rows for the same (assessment, student) "
        "before applying the unique constraint migration."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            default=False,
            help="Apply changes. If omitted, runs in dry-run mode.",
        )
        parser.add_argument(
            "--assessment-id",
            action="append",
            dest="assessment_ids",
            type=int,
            default=[],
            help="Restrict cleanup to one or more assessment IDs.",
        )

    def handle(self, *args, **options):
        apply_changes = options.get("apply", False)
        assessment_ids = options.get("assessment_ids") or []

        duplicate_groups = (
            Result.objects.values("assessment_id", "student_id")
            .annotate(row_count=Count("id"))
            .filter(row_count__gt=1)
            .order_by("assessment_id", "student_id")
        )
        if assessment_ids:
            duplicate_groups = duplicate_groups.filter(assessment_id__in=assessment_ids)

        if not duplicate_groups.exists():
            self.stdout.write(self.style.SUCCESS("No duplicate Result rows found."))
            return

        self.stdout.write(
            self.style.WARNING(
                f"Found {duplicate_groups.count()} duplicate (assessment, student) group(s)."
            )
        )
        self.stdout.write(
            "Mode: " + (self.style.SUCCESS("APPLY") if apply_changes else self.style.WARNING("DRY-RUN"))
        )

        merged_rows = 0
        deleted_rows = 0

        for group in duplicate_groups:
            assessment_id = group["assessment_id"]
            student_id = group["student_id"]
            rows = list(
                Result.objects.filter(assessment_id=assessment_id, student_id=student_id)
                .select_related("assessment", "student")
                .order_by("-id")
            )
            if len(rows) <= 1:
                continue

            keep_row = self._pick_canonical_row(rows)
            newest_row = max(rows, key=lambda item: item.id)
            strongest_row = max(
                rows,
                key=lambda item: (
                    STATUS_PRIORITY.get((item.status or "").upper(), 0),
                    int(item.batch_id is not None),
                    item.id,
                ),
            )

            self.stdout.write(
                f"- Assessment {assessment_id}, Student {student_id}: "
                f"{len(rows)} rows -> keep #{keep_row.id}, delete {len(rows) - 1}"
            )

            if not apply_changes:
                continue

            with transaction.atomic():
                update_fields = []

                if keep_row.score != newest_row.score:
                    keep_row.score = newest_row.score
                    update_fields.append("score")

                strongest_status = strongest_row.status
                current_rank = STATUS_PRIORITY.get((keep_row.status or "").upper(), 0)
                strongest_rank = STATUS_PRIORITY.get((strongest_status or "").upper(), 0)
                if strongest_status and strongest_rank > current_rank:
                    keep_row.status = strongest_status
                    update_fields.append("status")

                if keep_row.batch_id is None and strongest_row.batch_id is not None:
                    keep_row.batch_id = strongest_row.batch_id
                    update_fields.append("batch")

                if update_fields:
                    keep_row.save(update_fields=update_fields)

                deleted = self._merge_and_delete_duplicates(keep_row, rows)
                deleted_rows += deleted
                merged_rows += 1

        if apply_changes:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Merged {merged_rows} duplicate group(s); removed {deleted_rows} duplicate row(s)."
                )
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    "Dry-run complete. Re-run with --apply to execute the cleanup."
                )
            )

    def _pick_canonical_row(self, rows):
        row_ids = [row.id for row in rows]
        sampled_result_ids = set(
            VerificationSample.objects.filter(result_id__in=row_ids).values_list("result_id", flat=True)
        )

        return max(
            rows,
            key=lambda item: (
                int(item.id in sampled_result_ids),
                STATUS_PRIORITY.get((item.status or "").upper(), 0),
                int(item.batch_id is not None),
                item.id,
            ),
        )

    def _merge_and_delete_duplicates(self, keep_row, rows):
        deleted_count = 0
        keep_sample = VerificationSample.objects.filter(result_id=keep_row.id).first()

        for row in rows:
            if row.id == keep_row.id:
                continue

            VerificationCorrectionLog.objects.filter(result_id=row.id).update(result_id=keep_row.id)

            row_sample = VerificationSample.objects.filter(result_id=row.id).first()
            if row_sample:
                if keep_sample is None:
                    VerificationDiscrepancy.objects.filter(sample_id=row_sample.id).update(result_id=keep_row.id)
                    row_sample.result_id = keep_row.id
                    row_sample.save(update_fields=["result"])
                    keep_sample = row_sample
                else:
                    VerificationDiscrepancy.objects.filter(sample_id=row_sample.id).delete()
                    row_sample.delete()

            VerificationDiscrepancy.objects.filter(result_id=row.id).update(result_id=keep_row.id)
            row.delete()
            deleted_count += 1

        return deleted_count
