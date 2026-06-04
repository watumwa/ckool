from functools import wraps

from django.contrib import messages
from django.shortcuts import redirect

from app.models.school_settings import SchoolSetting
def primary_mode_required(view_func):
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        school_setting = SchoolSetting.load()
        education_level = (
            request.session.get("active_school_level")
            or getattr(school_setting, "education_level", SchoolSetting.EducationLevel.PRIMARY)
        )

        if education_level != SchoolSetting.EducationLevel.PRIMARY:
            messages.error(
                request,
                "Primary results workflow is disabled while school mode is set to Secondary.",
            )
            return redirect("secondary:dashboard")

        return view_func(request, *args, **kwargs)

    return _wrapped
