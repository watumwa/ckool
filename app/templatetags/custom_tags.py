from django import template

register = template.Library()

@register.filter
def get_student_count(student_name, student_name_counts):
    return student_name_counts.get(student_name, 0)



@register.filter
def lookup(dictionary, key):
    """
    Access a dictionary value by key in a template.
    Returns None if the key doesn't exist.
    """
    return dictionary.get(key)




@register.filter
def lookup(d, key):
    if not isinstance(d, dict):
        return None
    return d.get(key, None)

