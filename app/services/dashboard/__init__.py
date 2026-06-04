"""Dashboard service layer for admin control-tower sections."""

from .common import (
    get_active_role,
    get_dashboard_base_context,
    resolve_scope,
    user_can_access_admin_dashboard,
)
from .overview import get_overview_context
from .finance import get_finance_context
from .academics import get_academics_context
from .attendance import get_attendance_context
from .reports import get_reports_context

__all__ = [
    "get_active_role",
    "get_dashboard_base_context",
    "resolve_scope",
    "user_can_access_admin_dashboard",
    "get_overview_context",
    "get_finance_context",
    "get_academics_context",
    "get_attendance_context",
    "get_reports_context",
]
