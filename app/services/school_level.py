from app.models.school_settings import SchoolSetting


def get_level_label(level):
    return dict(SchoolSetting.EducationLevel.choices).get(level, level or "Unknown")


def get_enabled_levels(school_setting=None):
    school_setting = school_setting or SchoolSetting.load()
    if hasattr(school_setting, "get_enabled_levels"):
        return school_setting.get_enabled_levels()

    fallback = getattr(school_setting, "education_level", SchoolSetting.EducationLevel.PRIMARY)
    return [fallback or SchoolSetting.EducationLevel.PRIMARY]


def get_active_school_level(request=None, school_setting=None):
    school_setting = school_setting or SchoolSetting.load()
    enabled_levels = get_enabled_levels(school_setting)
    default_level = getattr(school_setting, "education_level", SchoolSetting.EducationLevel.PRIMARY)
    if default_level not in enabled_levels:
        default_level = enabled_levels[0]

    if request is None:
        return default_level

    session_level = request.session.get("active_school_level")
    if session_level in enabled_levels:
        return session_level

    request.session["active_school_level"] = default_level
    return default_level


def set_active_school_level(request, level, school_setting=None):
    school_setting = school_setting or SchoolSetting.load()
    enabled_levels = get_enabled_levels(school_setting)
    if level not in enabled_levels:
        raise ValueError("Selected school level is not enabled for this school.")
    request.session["active_school_level"] = level
    return level
