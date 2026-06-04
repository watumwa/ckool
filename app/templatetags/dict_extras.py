from django import template

register = template.Library()

@register.filter
def get_item(d, key):
    """
    Safely fetch dict item by key in Django templates:
    Usage: {{ some_dict|get_item:dynamic_key }}
    """
    try:
        return d.get(key)
    except Exception:
        return None
