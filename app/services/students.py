import csv
import re
from datetime import datetime
from django.db import transaction
from app.selectors.school_settings import get_current_academic_year
from app.selectors.classes import get_academic_class_stream, get_class_by_code, get_current_term
import app.selectors.fees_selectors as fees_selectors
from app.models.students import Student, ClassRegister, StudentRegistrationCSV
from app.models.fees_payment import StudentBill, StudentBillItem,ClassBill
from app.models.classes import *
from app.models.school_settings import AcademicYear
from app.constants import GENDERS, NATIONALITIES, RELIGIONS


def register_student(student, _class, stream):
    if isinstance(_class, str):  
        _class = get_class_by_code(_class)  
    current_academic_year = get_current_academic_year()
    term = get_current_term()
    academic_class = AcademicClass.objects.filter(
        academic_year=current_academic_year,
        Class=_class,
        term=term,
    ).first()
    if not academic_class:
        raise ValueError(
            f"No Academic Class configured for class '{_class}' in current year/term."
        )
    class_stream = get_academic_class_stream(academic_class, stream)
    class_register = ClassRegister(academic_class_stream=class_stream, student=student)
    class_register.save()
    create_student_bill(student, academic_class)
    return class_register


HEADER_ALIASES = {
    "student_number": {"student_number", "student number", "student id", "learner id", "learner number"},
    "reg_no": {"reg_no", "reg no", "id no", "registration no", "admission no"},
    "student_name": {"student_name", "student name", "name"},
    "gender": {"gender", "sex"},
    "birthdate": {"birthdate", "birth date", "date of birth", "dob"},
    "nationality": {"nationality", "country"},
    "religion": {"religion"},
    "address": {"address"},
    "guardian": {"guardian", "guardian name"},
    "relationship": {"relationship"},
    "contact": {"guardian contact", "contact", "guardian phone", "phone"},
    "academic_year": {"academic year", "year", "entry year"},
    "current_class": {"current class", "class", "class code"},
    "stream": {"stream"},
    "term": {"term", "term id", "term number"},
}


def _normalize_header(header):
    normalized = str(header or "").strip().lower().replace("_", " ")
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return " ".join(normalized.split())


def _find_header_row(rows):
    for idx, row in enumerate(rows):
        normalized = [_normalize_header(cell) for cell in row if str(cell).strip()]
        has_student_name = any(value == "student name" for value in normalized)
        has_term = any(value == "term" or value.startswith("term ") for value in normalized)
        if has_student_name and has_term:
            return idx
    return None


def _build_field_positions(header_row):
    positions = {}
    normalized_headers = [_normalize_header(col) for col in header_row]
    for i, header in enumerate(normalized_headers):
        for canonical, aliases in HEADER_ALIASES.items():
            if any(header == alias or header.startswith(f"{alias} ") for alias in aliases):
                positions[canonical] = i
    return positions


def _parse_birthdate(raw_value, row_number):
    raw_value = str(raw_value or "").strip()
    date_formats = ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d/%m/%y", "%m/%d/%y")
    for fmt in date_formats:
        try:
            return datetime.strptime(raw_value, fmt).date()
        except ValueError:
            continue
    raise ValueError(
        f"Row {row_number}: invalid birthdate '{raw_value}'. Use YYYY-MM-DD (or dd/mm/yyyy)."
    )


def _resolve_academic_year(raw_value, row_number):
    value = str(raw_value or "").strip()
    if not value:
        year = get_current_academic_year()
        if not year:
            raise ValueError(f"Row {row_number}: no current academic year is configured.")
        return year

    year = AcademicYear.objects.filter(academic_year=value).first()
    if year:
        return year

    if value.isdigit():
        year = AcademicYear.objects.filter(id=int(value)).first()
        if year:
            return year

    raise ValueError(f"Row {row_number}: academic year '{value}' was not found.")


def _resolve_term(raw_value, academic_year, row_number):
    raw = str(raw_value or "").strip()
    if not raw:
        raise ValueError(f"Row {row_number}: term is required.")

    normalized = raw.lower().replace("term", "").replace(" ", "")
    roman_map = {"i": "1", "ii": "2", "iii": "3"}
    term_number = roman_map.get(normalized, normalized)

    term = Term.objects.filter(academic_year=academic_year, term=term_number).first()
    if term:
        return term

    if raw.isdigit():
        term = Term.objects.filter(id=int(raw), academic_year=academic_year).first()
        if term:
            return term

    raise ValueError(
        f"Row {row_number}: term '{raw}' is invalid for academic year '{academic_year.academic_year}'."
    )


def _resolve_class(raw_value, row_number):
    value = str(raw_value or "").strip()
    if not value:
        raise ValueError(f"Row {row_number}: class is required.")

    klass = Class.objects.filter(code__iexact=value).first() or Class.objects.filter(name__iexact=value).first()
    if not klass:
        raise ValueError(f"Row {row_number}: class '{value}' was not found.")
    return klass


def _resolve_stream(raw_value, row_number):
    value = str(raw_value or "").strip()
    if not value:
        raise ValueError(f"Row {row_number}: stream is required.")

    stream = Stream.objects.filter(stream__iexact=value).first()
    if not stream:
        raise ValueError(f"Row {row_number}: stream '{value}' was not found.")
    return stream


def _normalize_gender(raw_value, row_number):
    value = str(raw_value or "").strip().lower()
    gender_map = {"m": "M", "male": "M", "f": "F", "female": "F"}
    normalized = gender_map.get(value)
    if normalized:
        return normalized
    allowed = ", ".join(choice[0] for choice in GENDERS)
    raise ValueError(f"Row {row_number}: invalid gender '{raw_value}'. Allowed: {allowed}.")


def _normalize_choice(raw_value, row_number, field_name, allowed_choices):
    value = str(raw_value or "").strip()
    if not value:
        raise ValueError(f"Row {row_number}: {field_name} is required.")

    allowed_values = [choice[0] for choice in allowed_choices]
    for allowed in allowed_values:
        if allowed.lower() == value.lower():
            return allowed
    raise ValueError(
        f"Row {row_number}: invalid {field_name} '{value}'. Allowed values: {', '.join(allowed_values)}."
    )


def bulk_student_registration(csv_obj):
    created_count = 0
    skipped_count = 0
    errors = []
    seen_reg_numbers = set()
    seen_student_numbers = set()

    with open(csv_obj.file_name.path, "r", encoding="utf-8-sig", newline="") as f:
        rows = [row for row in csv.reader(f) if any(str(cell).strip() for cell in row)]

    if not rows:
        raise ValueError("Uploaded CSV is empty.")

    header_index = _find_header_row(rows)
    if header_index is None:
        raise ValueError("CSV header row not found. Use the provided template.")

    header_row = rows[header_index]
    field_positions = _build_field_positions(header_row)
    required_fields = [
        "student_name",
        "gender",
        "birthdate",
        "nationality",
        "religion",
        "address",
        "guardian",
        "relationship",
        "contact",
        "current_class",
        "stream",
        "term",
    ]

    missing_fields = [field for field in required_fields if field not in field_positions]
    if missing_fields:
        raise ValueError(f"CSV is missing required columns: {', '.join(missing_fields)}.")

    for row_number, row in enumerate(rows[header_index + 1 :], start=header_index + 2):
        try:
            def get_value(field_name):
                pos = field_positions[field_name]
                return row[pos].strip() if pos < len(row) else ""

            reg_no = get_value("reg_no") if "reg_no" in field_positions else ""
            if reg_no:
                if reg_no in seen_reg_numbers:
                    raise ValueError(f"Row {row_number}: duplicate Reg No '{reg_no}' in CSV.")
                seen_reg_numbers.add(reg_no)
                if Student.objects.filter(reg_no=reg_no).exists():
                    raise ValueError(f"Row {row_number}: student with Reg No '{reg_no}' already exists.")

            student_number = ""
            if "student_number" in field_positions:
                student_number = get_value("student_number")
                if student_number:
                    if not (student_number.isdigit() and len(student_number) == 6):
                        raise ValueError(f"Row {row_number}: Student ID must be a 6-digit number.")
                    if student_number in seen_student_numbers:
                        raise ValueError(f"Row {row_number}: duplicate Student ID '{student_number}' in CSV.")
                    seen_student_numbers.add(student_number)
                    if Student.objects.filter(student_number=student_number).exists():
                        raise ValueError(f"Row {row_number}: student with Student ID '{student_number}' already exists.")

            student_name = get_value("student_name")
            if not student_name:
                raise ValueError(f"Row {row_number}: student name is required.")

            academic_year = _resolve_academic_year(get_value("academic_year"), row_number)
            term = _resolve_term(get_value("term"), academic_year, row_number)
            current_class = _resolve_class(get_value("current_class"), row_number)
            stream = _resolve_stream(get_value("stream"), row_number)
            gender = _normalize_gender(get_value("gender"), row_number)
            birthdate = _parse_birthdate(get_value("birthdate"), row_number)
            nationality = _normalize_choice(get_value("nationality"), row_number, "nationality", NATIONALITIES)
            religion = _normalize_choice(get_value("religion"), row_number, "religion", RELIGIONS)

            academic_class = AcademicClass.objects.filter(
                academic_year=academic_year,
                Class=current_class,
                term=term,
            ).first()
            if not academic_class:
                raise ValueError(
                    f"Row {row_number}: no Academic Class setup for class '{current_class.code}' and term '{term.term}'."
                )

            class_stream = AcademicClassStream.objects.filter(
                academic_class=academic_class, stream=stream
            ).first()
            if not class_stream:
                raise ValueError(
                    f"Row {row_number}: no class stream found for class '{current_class.code}' and stream '{stream.stream}'."
                )

            with transaction.atomic():
                student_data = {
                    "student_name": student_name,
                    "gender": gender,
                    "birthdate": birthdate,
                    "nationality": nationality,
                    "religion": religion,
                    "address": get_value("address"),
                    "guardian": get_value("guardian"),
                    "relationship": get_value("relationship"),
                    "contact": get_value("contact"),
                    "academic_year": academic_year,
                    "current_class": current_class,
                    "stream": stream,
                    "term": term,
                }

                if reg_no:
                    student_data["reg_no"] = reg_no
                if student_number:
                    student_data["student_number"] = student_number

                student = Student.objects.create(**student_data)
                ClassRegister.objects.get_or_create(
                    academic_class_stream=class_stream,
                    student=student,
                )
                create_student_bill(student, academic_class)

            created_count += 1
        except ValueError as exc:
            skipped_count += 1
            errors.append(str(exc))
        except Exception as exc:
            skipped_count += 1
            errors.append(f"Row {row_number}: unexpected error: {exc}")

    if created_count == 0 and errors:
        raise ValueError(errors[0])

    return {
        "created_count": created_count,
        "skipped_count": skipped_count,
        "errors": errors,
    }




def delete_all_csv_files():
    StudentRegistrationCSV.objects.all().delete()
        
def create_student_bill(student, academic_class):
    """
    Creates a StudentBill and assigns all Class Bills 
    """
    
    student_bill = (
        StudentBill.objects.filter(student=student, academic_class=academic_class)
        .order_by("id")
        .first()
    )
    if not student_bill:
        student_bill = StudentBill.objects.create(
            student=student,
            academic_class=academic_class,
            status="Unpaid",
        )

    school_fees_description = f"School Fees for {academic_class.term} - {academic_class.academic_year}"
    school_fees_bill_item = fees_selectors.get_bill_item_by_name("School Fees")
    if school_fees_bill_item:
        qs = StudentBillItem.objects.filter(
            bill=student_bill,
            bill_item=school_fees_bill_item,
        ).order_by("id")
        if qs.exists():
            bill_item_row = qs.first()
            if qs.count() > 1:
                qs.exclude(pk=bill_item_row.pk).delete()
            bill_item_row.description = school_fees_description
            bill_item_row.amount = academic_class.fees_amount
            bill_item_row.save()
        else:
            create_bill_Item(
                student_bill,
                school_fees_description,
                academic_class.fees_amount,
                school_fees_bill_item,
            )

    # Get all additional Class Bills for this academic class
    class_bills = ClassBill.objects.filter(academic_class=academic_class)

    for class_bill in class_bills:
        qs = StudentBillItem.objects.filter(
            bill=student_bill, bill_item=class_bill.bill_item
        ).order_by("id")
        if qs.exists():
            bill_item_row = qs.first()
            if qs.count() > 1:
                qs.exclude(pk=bill_item_row.pk).delete()
            bill_item_row.description = class_bill.bill_item.description
            bill_item_row.amount = class_bill.amount
            bill_item_row.save()
        else:
            StudentBillItem.objects.create(
                bill=student_bill,
                bill_item=class_bill.bill_item,
                description=class_bill.bill_item.description,
                amount=class_bill.amount
            )
    return student_bill

    
def create_bill_Item(bill, description, amount, bill_item=None):
    if bill_item == None:
        bill_item = fees_selectors.get_bill_item_by_name("School Fees")
    
    bill_item = StudentBillItem(bill=bill, bill_item=bill_item, description=description, amount=amount)
    
    bill_item.save()
    
    return bill_item
    
def create_class_bill_item(academic_class, bill_item, amount):
    class_bills = fees_selectors.get_academic_class_bills(academic_class)
    bill_item = fees_selectors.get_bill_item(bill_item)
    description = f"{bill_item.item_name} for {academic_class.Class} {academic_class.academic_year}"
    
    for bill in class_bills:
        create_bill_Item(bill, description, amount, bill_item)
        
    
   
    
    
