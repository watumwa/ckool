from django import template
from app.models.results import ResultBatch
from app.models.school_settings import SchoolSetting
from app.services.school_level import get_active_school_level

register = template.Library()


@register.simple_tag(takes_context=True)
def pending_verification_count(context):
    """Returns the count of ResultBatch items with status 'PENDING'."""
    request = context.get("request")
    if get_active_school_level(request) != SchoolSetting.EducationLevel.PRIMARY:
        return 0
    return ResultBatch.objects.filter(status='PENDING').count()


@register.simple_tag(takes_context=True)
def get_pending_verifications(context, limit=5):
    """Returns a list of pending verifications."""
    request = context.get("request")
    if get_active_school_level(request) != SchoolSetting.EducationLevel.PRIMARY:
        return []
    return ResultBatch.objects.filter(status='PENDING').order_by('-submitted_at')[:limit]
