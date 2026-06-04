from app.models.results import GradingSystem

def calculate_grade_and_points(score):
    try:
        grading = GradingSystem.objects.get(min_score__lte=score, max_score__gte=score)
        return grading.grade, grading.points
    except GradingSystem.DoesNotExist:
        return "N/A", None  
