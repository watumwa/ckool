from app.models.results import *
from app.models.school_settings import SchoolSetting
from django.db.models import Sum
from decimal import Decimal, InvalidOperation, ROUND_FLOOR


def _get_grading_row(score):
    try:
        normalized_score = Decimal(str(score)).quantize(Decimal('0.01'))
    except (ValueError, TypeError, InvalidOperation):
        return None

    grading_row = (
        GradingSystem.objects.filter(
            min_score__lte=normalized_score,
            max_score__gte=normalized_score,
        )
        .order_by('-min_score', '-max_score')
        .first()
    )
    if grading_row:
        return grading_row

    floored_score = normalized_score.quantize(Decimal('1'), rounding=ROUND_FLOOR)
    if floored_score == normalized_score:
        return None

    return (
        GradingSystem.objects.filter(
            min_score__lte=floored_score,
            max_score__gte=floored_score,
        )
        .order_by('-min_score', '-max_score')
        .first()
    )

def get_grade_and_points(score):
    try:
        grade_row = _get_grading_row(score)
        if grade_row:
            return grade_row.grade, float(grade_row.points)
        return "N/A", 0
    except (ValueError, TypeError):
        return "N/A", 0






def get_current_mode():
    setting = ResultModeSetting.objects.first()
    return setting.mode if setting else "CUMULATIVE"

def get_performance_metrics(assessments):
    if not assessments.exists():
        return {
            'average': Decimal('0.00'),
            'top_score': Decimal('0.00'),
            'bottom_score': Decimal('0.00'),
            'ordered_assessments': []
        }
    total_score = assessments.aggregate(total=Sum('score'))['total'] or Decimal('0.00')
    count = assessments.count()
    average = (total_score / count).quantize(Decimal('0.01')) if count > 0 else Decimal('0.00')
    ordered_assessments = assessments.order_by('-score')
    top_score = ordered_assessments.first()
    bottom_score = ordered_assessments.last()
    return {
        'average': average,
        'top_score': top_score.score if top_score else Decimal('0.00'),
        'bottom_score': bottom_score.score if bottom_score else Decimal('0.00'),
        'ordered_assessments': ordered_assessments
    }


def get_grade_from_average(score):
    grading = _get_grading_row(score)
    return grading.grade if grading else "N/A"

def calculate_weighted_subject_averages(assessments):
    if not assessments.exists():
        return []
    
    subject_scores = {}
    for result in assessments:
        subject = result.assessment.subject.name
        assessment_type = result.assessment.assessment_type
        weight = Decimal(str(result.assessment.assessment_type.weight or 1))
        raw_score = Decimal(str(result.score))
        if subject not in subject_scores:
            subject_scores[subject] = {
                'total_score': Decimal('0.0'),
                'total_weight': Decimal('0.0'),
                'assessments': [],
                'teacher': getattr(result.assessment.subject, 'teacher', None),
            }
        subject_scores[subject]['total_score'] += raw_score * weight
        subject_scores[subject]['total_weight'] += weight
        subject_scores[subject]['assessments'].append({
            'id': assessment_type.id,
            'name': assessment_type.name
        })
    
    averages = []
    for subject, data in subject_scores.items():
        average = (data['total_score'] / data['total_weight']).quantize(Decimal('0.01')) if data['total_weight'] else Decimal('0.00')
        grade, points = get_grade_and_points(average)
        unique_assessments = {a['id']: a for a in data['assessments']}.values()
        averages.append({
            'subject': subject,
            'average': float(average),
            'grade': grade,
            'points': points,
            'assessments': list(unique_assessments),
            'teacher': data['teacher'],
        })
    return averages


def _base_division(total_aggregates):
    if 4 <= total_aggregates <= 12:
        return "Division 1"
    elif 13 <= total_aggregates <= 24:
        return "Division 2"
    elif 25 <= total_aggregates <= 28:
        return "Division 3"
    elif 29 <= total_aggregates <= 32:
        return "Division 4"
    else:
        return "U"


def _division_rank(division_label):
    mapping = {
        "Division 1": 1,
        "Division 2": 2,
        "Division 3": 3,
        "Division 4": 4,
        "U": 5,
        None: 99,
        "-": 99,
    }
    return mapping.get(division_label, 99)


def _cap_division(division_label, cap_label):
    if not division_label or not cap_label:
        return division_label
    if _division_rank(division_label) > _division_rank(cap_label):
        return division_label
    return cap_label


def _extract_grade_and_points(subject_grade_value):
    if isinstance(subject_grade_value, dict):
        grade = str(subject_grade_value.get("grade", "")).strip().upper()
        points = subject_grade_value.get("points")
        return grade, points
    if subject_grade_value is None:
        return "", None
    grade_str = str(subject_grade_value).strip().upper()
    return grade_str, None


def _is_f9(grade_value, points_value):
    if points_value is not None:
        try:
            return int(points_value) == 9
        except (TypeError, ValueError):
            pass
    grade_value = (grade_value or "").strip().upper()
    return grade_value in {"F9", "9"} or "F9" in grade_value


def get_division(total_aggregates, subject_grades=None):
    base_division = _base_division(total_aggregates)

    if not subject_grades:
        return base_division

    try:
        settings = SchoolSetting.load()
    except Exception:
        return base_division

    critical_subjects = {
        name.strip().lower()
        for name in settings.division_critical_subjects.values_list("name", flat=True)
    } if settings else set()

    if not critical_subjects:
        return base_division

    f9_subjects = []
    for subject, grade_value in subject_grades.items():
        subject_key = str(subject).strip().lower()
        grade, points = _extract_grade_and_points(grade_value)
        if subject_key in critical_subjects and _is_f9(grade, points):
            f9_subjects.append(subject)

    if not f9_subjects:
        return base_division

    cap_label = getattr(settings, "division_f9_cap", None) or "Division 3"
    return _cap_division(base_division, cap_label)


def get_division_with_override(total_aggregates, subject_grades=None):
    base_division = _base_division(total_aggregates)
    selected_division = get_division(total_aggregates, subject_grades)

    if selected_division == base_division:
        return selected_division, None

    try:
        settings = SchoolSetting.load()
        critical_subjects = {
            name.strip().lower()
            for name in settings.division_critical_subjects.values_list("name", flat=True)
        } if settings else set()
    except Exception:
        critical_subjects = set()

    if not critical_subjects or not subject_grades:
        return selected_division, None

    f9_subjects = []
    for subject, grade_value in subject_grades.items():
        subject_key = str(subject).strip().lower()
        grade, points = _extract_grade_and_points(grade_value)
        if subject_key in critical_subjects and _is_f9(grade, points):
            f9_subjects.append(subject)

    if not f9_subjects:
        return selected_division, None

    cap_label = getattr(settings, "division_f9_cap", None) or "Division 3"
    note = f"Division capped at {cap_label} due to F9 in: {', '.join(f9_subjects)}"
    return selected_division, note
