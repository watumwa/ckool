from django import template

register = template.Library()

@register.filter
def get_item(mapping, key):
    
    if mapping is None:
        return None

    # Prefer .get when available (dict-like)
    if hasattr(mapping, "get"):
        try:
            return mapping.get(key)
        except Exception:
            # Fall back to item access if .get failed unexpectedly
            pass

    # Fallback to [] access for mappings or sequences
    try:
        return mapping[key]
    except Exception:
        return None
