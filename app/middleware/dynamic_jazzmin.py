from django.conf import settings
from app.models.school_settings import SchoolSetting

class DynamicJazzminMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Fetch the school name from the SchoolSetting model
        try:
            school_setting = SchoolSetting.get_solo()
            school_name = school_setting.school_name if school_setting.school_name else "School Admin"
        except Exception:
            school_name = "School Admin"

        # Update JAZZMIN_SETTINGS dynamically
        settings.JAZZMIN_SETTINGS.update({
            "site_title": f"{school_name} Admin",
            "site_header": f"{school_name} Administration",
            "site_brand": school_name,
            "welcome_sign": f"Welcome to {school_name} Admin",
        })

        response = self.get_response(request)
        return response