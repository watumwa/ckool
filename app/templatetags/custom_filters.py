from django import template

register = template.Library()

@register.filter
def dict_key(dictionary, key):
    """Return the value for the given key from the dictionary."""
    return dictionary.get(key, None)

@register.filter
def get_item(dictionary, key):
    """Safely return the value for the given key from a dictionary."""
    if not isinstance(dictionary, dict):
        return None  # Return None if the input is not a dictionary
    return dictionary.get(str(key), None)  # Safely get the value or None

@register.filter
def not_reserved_key(value):
    return value not in ['total_final_score', 'total_points', 'student_id', 'student_name']

@register.filter
def is_top_score(score, subject_scores):
    """
    Check if the score is the highest among all students for the given subject_scores.
    `subject_scores` is expected to be a list of scores.
    """
    try:
        score = float(score)
        max_score = max([float(s) for s in subject_scores if s is not None])
        return score == max_score
    except:
        return False

@register.filter
def get_score(student, subject):
    return student.get(subject, 0)  # Note: This assumes student is a dict

@register.filter
def sum_attr(iterable, attr_name):
    """
    Sum numeric attribute `attr_name` over any iterable of objects or dicts.
    - Safely skips None and non-numeric values
    - Works for both obj.attr and dict['attr'] cases
    """
    total = 0.0
    if not iterable:
        return 0.0
    for item in iterable:
        try:
            # Try object attribute first
            val = getattr(item, attr_name, None)
            if val is None and isinstance(item, dict):
                # Fallback to dict key
                val = item.get(attr_name, None)
            if val is None:
                continue
            # Convert to float safely
            total += float(val)
        except Exception:
            # Ignore non-numeric/coercion errors
            continue
    return total

@register.filter
def subtract(a, b):
    """
    Subtract b from a with safe numeric coercion.
    Usage: {{ a|subtract:b }}
    """
    try:
        return float(a) - float(b)
    except Exception:
        try:
            # handle Decimal or string commas
            from decimal import Decimal
            return Decimal(str(a).replace(',', '')) - Decimal(str(b).replace(',', ''))
        except Exception:
            return 0