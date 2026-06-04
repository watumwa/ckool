from decimal import Decimal
import random
import logging

from django.db import transaction, models
from django.utils import timezone

logger = logging.getLogger(__name__)

from app.models.results import (
    ResultBatch,
    Result,
    VerificationSample,
    ResultVerificationSetting,
    ResultVerificationNotification,
    ResultVerificationReport,
    VerificationDiscrepancy,
    VerificationCorrectionLog,
)
from app.models.accounts import StaffAccount


def ensure_batch_for_assessment(assessment):
    batch, _created = ResultBatch.objects.get_or_create(assessment=assessment)
    return batch


def attach_batch_to_results(assessment, batch):
    Result.objects.filter(assessment=assessment, batch__isnull=True).update(batch=batch)


def submit_batch_for_verification(assessment, user):
    settings = ResultVerificationSetting.get_settings()
    batch = ensure_batch_for_assessment(assessment)
    logger.info(
        "submit_batch_for_verification start: assessment_id=%s batch_id=%s status=%s user_id=%s",
        getattr(assessment, "id", None),
        getattr(batch, "id", None),
        getattr(batch, "status", None),
        getattr(user, "id", None),
    )
    if batch.status != "DRAFT":
        logger.warning(
            "submit_batch_for_verification blocked: batch not DRAFT (status=%s)",
            batch.status,
        )
        return batch, 0, False

    results = list(Result.objects.filter(assessment=assessment))
    if not results:
        logger.warning(
            "submit_batch_for_verification blocked: no results for assessment_id=%s",
            getattr(assessment, "id", None),
        )
        return batch, 0, False

    attach_batch_to_results(assessment, batch)

    with transaction.atomic():
        batch.status = "PENDING"
        batch.submitted_by = user
        batch.submitted_at = timezone.now()
        batch.save(update_fields=["status", "submitted_by", "submitted_at"])

        Result.objects.filter(assessment=assessment).update(status="PENDING", batch=batch)
        VerificationSample.objects.filter(result__assessment=assessment).delete()
        logger.info(
            "submit_batch_for_verification pending: batch_id=%s results=%s",
            getattr(batch, "id", None),
            len(results),
        )

        percent = Decimal(str(settings.sample_percent))
        sample_size = int((Decimal(str(len(results))) * percent) / Decimal("100"))
        if percent > 0 and sample_size == 0:
            sample_size = 1

        sample_size = min(sample_size, len(results))
        if sample_size > 0:
            sampled_results = random.sample(results, sample_size)
            VerificationSample.objects.bulk_create(
                [VerificationSample(result=r) for r in sampled_results]
            )

        dos_accounts = StaffAccount.objects.filter(
            (
                models.Q(role__name__iexact="Director of Studies")
                | models.Q(role__name__iexact="DOS")
                | models.Q(staff__roles__name__iexact="Director of Studies")
                | models.Q(staff__roles__name__iexact="DOS")
            )
        ).select_related("user").distinct()
        logger.info(
            "submit_batch_for_verification DOS recipients=%s",
            list(dos_accounts.values_list("user_id", flat=True)),
        )
        for dos in dos_accounts:
            ResultVerificationNotification.objects.create(
                recipient=dos.user,
                batch=batch,
                title="Results submitted for verification",
                message=f"{assessment} has been submitted for verification.",
            )

    return batch, sample_size, True


def update_sample_mark(sample, dos_mark, user):
    settings = ResultVerificationSetting.get_settings()
    tolerance = Decimal(str(settings.tolerance_marks))
    is_match = abs(Decimal(str(dos_mark)) - Decimal(str(sample.result.score))) <= tolerance
    # Always persist the entered verifier mark for auditability.
    sample.dos_mark = dos_mark
    sample.checked_by = user
    sample.checked_at = timezone.now()
    sample.matched = is_match
    sample.save(update_fields=["dos_mark", "checked_by", "checked_at", "matched"])


def evaluate_batch_verification(batch, user, rejection_reason=None):
    samples = VerificationSample.objects.filter(result__batch=batch)
    if not samples.exists():
        return batch.status

    if samples.filter(checked_at__isnull=True).exists():
        return batch.status

    checked_samples = samples.exclude(checked_at__isnull=True)
    if not checked_samples.exists():
        return batch.status

    any_mismatch = checked_samples.filter(matched=False).exists()
    if any_mismatch:
        batch.status = "FLAGGED"
        batch.rejection_reason = rejection_reason or batch.rejection_reason
        batch.save(update_fields=["status", "rejection_reason"])
        Result.objects.filter(batch=batch).update(status="FLAGGED")
        ResultVerificationNotification.objects.filter(batch=batch, read=False).update(
            read=True,
            read_at=timezone.now(),
        )
        logger.info("evaluate_batch_verification flagged: batch_id=%s", batch.id)
        _create_verification_report(batch, user)
        return batch.status

    batch.status = "VERIFIED"
    batch.verified_by = user
    batch.verified_at = timezone.now()
    batch.rejection_reason = None
    batch.save(update_fields=["status", "verified_by", "verified_at", "rejection_reason"])
    Result.objects.filter(batch=batch).update(status="VERIFIED")
    ResultVerificationNotification.objects.filter(batch=batch, read=False).update(
        read=True,
        read_at=timezone.now(),
    )
    logger.info("evaluate_batch_verification verified: batch_id=%s", batch.id)
    _create_verification_report(batch, user)
    return batch.status
def _create_verification_report(batch, user):
    assessment = batch.assessment
    total_scripts = Result.objects.filter(batch=batch).count()
    samples = VerificationSample.objects.filter(result__batch=batch).select_related(
        "result", "result__student"
    )
    sampled_count = samples.count()
    reentered_count = samples.exclude(checked_at__isnull=True).count()
    matches_count = samples.filter(matched=True).count()
    mismatches_count = samples.filter(matched=False).count()
    accuracy_percent = 0
    if reentered_count > 0:
        accuracy_percent = (matches_count / reentered_count) * 100

    report_status = "RECHECK"
    if batch.status == "VERIFIED":
        report_status = "APPROVED"
    elif batch.status == "FLAGGED":
        report_status = "REJECTED"

    report, _created = ResultVerificationReport.objects.update_or_create(
        batch=batch,
        defaults={
            "total_scripts": total_scripts,
            "sampled_count": sampled_count,
            "reentered_count": reentered_count,
            "matches_count": matches_count,
            "mismatches_count": mismatches_count,
            "corrections_count": VerificationCorrectionLog.objects.filter(batch=batch).count(),
            "accuracy_percent": round(accuracy_percent, 2),
            "status": report_status,
            "verified_by": user,
            "verified_at": timezone.now(),
            "sampling_method": "Random (system)",
        },
    )
# Create discrepancy records for mismatches 
    for sample in samples.filter(matched=False):
        if sample.dos_mark is None:
            continue
        difference = sample.dos_mark - sample.result.score
        VerificationDiscrepancy.objects.update_or_create(
            sample=sample,
            defaults={
                "batch": batch,
                "result": sample.result,
                "teacher_mark": sample.result.score,
                "verifier_mark": sample.dos_mark,
                "difference": difference,
                "corrected_mark": None,
                "action_taken": "Flagged",
            },
        )

    return report


def record_correction(batch, result, old_mark, new_mark, reason, user):
    VerificationCorrectionLog.objects.create(
        batch=batch,
        result=result,
        old_mark=old_mark,
        new_mark=new_mark,
        reason=reason,
        corrected_by=user,
    )


def reset_batch_to_draft(batch, user=None):
    with transaction.atomic():
        VerificationSample.objects.filter(result__batch=batch).delete()
        batch.status = "DRAFT"
        batch.submitted_by = None
        batch.submitted_at = None
        batch.verified_by = None
        batch.verified_at = None
        batch.save(update_fields=[
            "status", "submitted_by", "submitted_at", "verified_by", "verified_at"
        ])
        Result.objects.filter(batch=batch).update(status="DRAFT")
    return True
