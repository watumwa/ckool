from app.models.subjects import *
from app.services.level_scope import get_level_subjects_queryset

def get_all_subjects(active_level=None):
    if active_level:
        return get_level_subjects_queryset(active_level=active_level)
    return Subject.objects.all()

def get_subject(id):
    return Subject.objects.get(pk=id)
