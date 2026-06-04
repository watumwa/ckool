# decorators.py
from functools import wraps

from django.contrib import messages
from django.shortcuts import redirect


def _resolve_active_role(request):
    session_role = (request.session.get("active_role_name") or "").strip()
    if session_role:
        return session_role
    try:
        staff_account = request.user.staff_account
        if staff_account and staff_account.role:
            return staff_account.role.name
    except Exception:
        pass
    return ""


def _user_has_role(request, allowed_roles):
    if not getattr(request.user, "is_authenticated", False):
        return False
    if getattr(request.user, "is_superuser", False):
        return True

    allowed = {str(role).strip().lower() for role in allowed_roles}
    active = _resolve_active_role(request).strip().lower()
    if active in allowed:
        return True

    try:
        return request.user.staff_account.staff.roles.filter(name__in=list(allowed_roles)).exists()
    except Exception:
        return False


def role_required_any(*allowed_roles, redirect_to="index_page"):
    """Require one of the named Staff roles using active session role plus staff roles.

    This is safer than checking sidebar visibility only; a user typing a URL
    manually should still be denied if their role is not allowed.
    """
    def decorator(function):
        @wraps(function)
        def wrapper(request, *args, **kwargs):
            if _user_has_role(request, allowed_roles):
                return function(request, *args, **kwargs)
            messages.error(request, "You do not have permission to open that page.")
            return redirect(redirect_to)
        return wrapper
    return decorator


def role_required(role, function=None, redirect_to="/"):
    """
    Backwards-compatible single-role decorator.
    """
    def decorator(function):
        @wraps(function)
        def wrapper(request, *args, **kwargs):
            if _user_has_role(request, [role]):
                return function(request, *args, **kwargs)
            return redirect(redirect_to)
        return wrapper

    if function is not None:
        return decorator(function)
    return decorator


admin_required = lambda function=None, redirect_to="/": role_required("Admin", function, redirect_to)
teacher_required = lambda function=None, redirect_to="/": role_required("Teacher", function, redirect_to)
