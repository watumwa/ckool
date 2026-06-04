"""Academics service for the admin control-tower dashboard."""

from __future__ import annotations

from collections import defaultdict

from django.db.models import Avg, Count, Q, Sum

from app.models.fees_payment import Payment, StudentBillItem
from app.models.classes import StudentPromotionHistory
from app.models.results import Assessment, Result
from app.services.level_scope import (
    get_level_academic_classes_queryset,
    get_level_students_queryset,
)
from app.services.school_level import get_active_school_level
from app.services.teacher_assignments import get_class_subject_teacher_rows


def get_academics_context(request, scope):
    """Student and performance analytics used by the admin dashboard."""
    current_year = scope.get("current_year")
    current_term = scope.get("current_term")
    active_level = get_active_school_level(request)
    scoped_students = get_level_students_queryset(active_level=active_level)
    scoped_academic_classes = get_level_academic_classes_queryset(active_level=active_level)

    student_scope = scoped_students
    if current_year and current_term:
        student_scope = student_scope.filter(academic_year=current_year, term=current_term)

    total_students = student_scope.count()
    active_students = student_scope.filter(is_active=True).count()
    inactive_students = student_scope.filter(is_active=False).count()
    male_students = student_scope.filter(gender="M", is_active=True).count()
    female_students = student_scope.filter(gender="F", is_active=True).count()

    new_admissions_this_term = total_students
    withdrawals_this_term = inactive_students
    transfers_this_term = 0  # no transfer model yet
    discipline_cases_count = 0  # no discipline model yet

    students_by_class = list(
        student_scope.filter(is_active=True)
        .values("current_class__name")
        .annotate(total=Count("id"))
        .order_by("-total")
    )

    enrollment_trend_rows = list(
        scoped_students.values("academic_year__academic_year")
        .annotate(
            total=Count("id"),
            active=Count("id", filter=Q(is_active=True)),
            inactive=Count("id", filter=Q(is_active=False)),
        )
        .order_by("academic_year__academic_year")
    )

    performance_scope = Result.objects.none()
    total_assessments = 0
    completed_assessments = 0
    overall_average = 0
    class_performance_rows = []
    top_performing_classes = []
    lowest_performing_subjects = []
    teachers_best_results = []
    students_with_fee_arrears = 0

    if current_year and current_term:
        term_scoped_academic_classes = scoped_academic_classes.filter(
            academic_year=current_year,
            term=current_term,
        )
        performance_scope = Result.objects.filter(
            assessment__academic_class__in=term_scoped_academic_classes,
            assessment__academic_class__academic_year=current_year,
            assessment__academic_class__term=current_term,
        )
        total_assessments = Assessment.objects.filter(
            academic_class__in=term_scoped_academic_classes,
            academic_class__academic_year=current_year,
            academic_class__term=current_term,
        ).count()
        completed_assessments = (
            performance_scope.values("assessment_id").distinct().count()
        )
        overall_average = (
            performance_scope.aggregate(avg=Avg("score")).get("avg") or 0
        )

        class_performance_rows = list(
            performance_scope.values("assessment__academic_class__Class__name")
            .annotate(
                avg_score=Avg("score"),
                results_count=Count("id"),
            )
            .order_by("-avg_score")
        )
        top_performing_classes = class_performance_rows[:5]

        lowest_performing_subjects = list(
            performance_scope.values("assessment__subject__name")
            .annotate(avg_score=Avg("score"), results_count=Count("id"))
            .order_by("avg_score")[:5]
        )

        assessment_rows = list(
            Assessment.objects.filter(
                academic_class__in=term_scoped_academic_classes,
                academic_class__academic_year=current_year,
                academic_class__term=current_term,
            ).values("id", "academic_class_id", "subject_id")
        )
        assessment_ids = [row["id"] for row in assessment_rows]
        assessment_map = {
            row["id"]: (row["academic_class_id"], row["subject_id"]) for row in assessment_rows
        }

        allocation_map = defaultdict(dict)
        if assessment_rows:
            class_ids = {row["academic_class_id"] for row in assessment_rows}
            subject_ids = {row["subject_id"] for row in assessment_rows}
            allocation_rows = get_class_subject_teacher_rows(
                class_ids=class_ids,
                subject_ids=subject_ids,
                current_year=current_year,
                current_term=current_term,
            )
            for alloc in allocation_rows:
                teacher_id = alloc["teacher_id"]
                if not teacher_id:
                    continue
                key = (
                    alloc["academic_class_id"],
                    alloc["subject_id"],
                )
                allocation_map[key][teacher_id] = {
                    "teacher_id": teacher_id,
                    "teacher_name": alloc["teacher_name"],
                }

        teacher_totals = {}
        if assessment_ids:
            result_rows = (
                Result.objects.filter(assessment_id__in=assessment_ids)
                .values("assessment_id")
                .annotate(avg_score=Avg("score"), total_results=Count("id"))
            )
            for row in result_rows:
                assessment_key = assessment_map.get(row["assessment_id"])
                if not assessment_key:
                    continue
                teachers = allocation_map.get(assessment_key, {})
                if not teachers:
                    continue
                total_results = row["total_results"] or 0
                avg_score = float(row["avg_score"] or 0)
                for teacher in teachers.values():
                    bucket = teacher_totals.setdefault(
                        teacher["teacher_id"],
                        {
                            "teacher_name": teacher["teacher_name"],
                            "weighted_score_total": 0.0,
                            "results_total": 0,
                            "assessments": 0,
                        },
                    )
                    bucket["weighted_score_total"] += avg_score * total_results
                    bucket["results_total"] += total_results
                    bucket["assessments"] += 1

        for teacher_id, totals in teacher_totals.items():
            results_total = totals["results_total"] or 0
            avg_score = (
                round(totals["weighted_score_total"] / results_total, 1)
                if results_total
                else 0
            )
            teachers_best_results.append(
                {
                    "teacher_id": teacher_id,
                    "teacher_name": totals["teacher_name"],
                    "avg_score": avg_score,
                    "assessments": totals["assessments"],
                    "results_total": results_total,
                }
            )
        teachers_best_results = sorted(
            teachers_best_results, key=lambda row: row["avg_score"], reverse=True
        )[:5]

        billed_by_student = list(
            StudentBillItem.objects.filter(
                bill__academic_class__in=term_scoped_academic_classes,
                bill__academic_class__academic_year=current_year,
                bill__academic_class__term=current_term,
                bill__student__is_active=True,
            )
            .values("bill__student_id")
            .annotate(total_billed=Sum("amount"))
        )
        paid_map = {
            row["bill__student_id"]: row["total_paid"] or 0
            for row in Payment.objects.filter(
                bill__academic_class__in=term_scoped_academic_classes,
                bill__academic_class__academic_year=current_year,
                bill__academic_class__term=current_term,
                bill__student__is_active=True,
            )
            .values("bill__student_id")
            .annotate(total_paid=Sum("amount"))
        }
        students_with_fee_arrears = 0
        for row in billed_by_student:
            total_billed = row["total_billed"] or 0
            total_paid = paid_map.get(row["bill__student_id"], 0)
            if total_billed > total_paid:
                students_with_fee_arrears += 1

    completion_rate = (
        round((completed_assessments / total_assessments) * 100, 1)
        if total_assessments
        else 0
    )

    promotion_history_scope = StudentPromotionHistory.objects.filter(
        source_academic_class__in=scoped_academic_classes
    )
    if current_year and current_term:
        promotion_history_scope = promotion_history_scope.filter(
            target_academic_class__academic_year=current_year,
            target_academic_class__term=current_term,
        )

    promotion_aggregates = promotion_history_scope.aggregate(
        runs=Count("id"),
        promoted_total=Sum("promoted_count"),
        candidates_total=Sum("total_candidates"),
    )
    recent_promotion_rows = list(
        promotion_history_scope.select_related(
            "promoted_by",
            "source_academic_class__Class",
            "target_academic_class__Class",
        ).order_by("-promoted_at")[:6]
    )

    return {
        "academics_total_students": total_students,
        "academics_active_students": active_students,
        "academics_inactive_students": inactive_students,
        "academics_male_students": male_students,
        "academics_female_students": female_students,
        "academics_new_admissions": new_admissions_this_term,
        "academics_withdrawals": withdrawals_this_term,
        "academics_transfers": transfers_this_term,
        "academics_students_with_fee_arrears": students_with_fee_arrears,
        "academics_discipline_cases": discipline_cases_count,
        "academics_students_by_class": students_by_class,
        "academics_enrollment_trend_rows": enrollment_trend_rows,
        "academics_total_assessments": total_assessments,
        "academics_completed_assessments": completed_assessments,
        "academics_completion_rate": completion_rate,
        "academics_overall_average": round(overall_average, 1),
        "academics_class_performance_rows": class_performance_rows,
        "academics_top_performing_classes": top_performing_classes,
        "academics_lowest_subjects": lowest_performing_subjects,
        "academics_teachers_best_results": teachers_best_results,
        "academics_promotion_runs": promotion_aggregates["runs"] or 0,
        "academics_promotion_promoted_total": promotion_aggregates["promoted_total"] or 0,
        "academics_promotion_candidates_total": promotion_aggregates["candidates_total"] or 0,
        "academics_recent_promotion_rows": recent_promotion_rows,
    }
