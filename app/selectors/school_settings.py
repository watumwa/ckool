from app.models.school_settings import *

def get_current_academic_year():
    try:
        return AcademicYear.objects.get(is_current=True)
    except AcademicYear.DoesNotExist:
        return None

def get_sections():
    return Section.objects.all()

def get_section(id):
    return Section.objects.get(pk=id)

def get_academic_years():
    return AcademicYear.objects.all()

def get_signatures():
    return Signature.objects.all()

def get_signature(id):
    return Signature.objects.get(pk=id)

def get_all_currencies():
    return Currency.objects.all()


def get_currency(currency_id):
    return Currency.objects.get(pk=currency_id)


def get_usd_currency():
    try:
        return Currency.objects.get(code="USD")
    except Currency.DoesNotExist:
        return None


def get_base_currency():
    school_setting = SchoolSetting.load()
    country = school_setting.country
    if country == "UG":
        return get_ugx_currency()

def get_currency_from_code(code):
    try:
        return Currency.objects.get(code=code)
    except Currency.DoesNotExist:
        return None


def get_ugx_currency():
    try:
        return Currency.objects.get(code="UGX")
    except Currency.DoesNotExist:
        return None

def get_all_departments():
    return Department.objects.all()

def get_department(id):
    return Department.objects.get(pk=id)
    
    