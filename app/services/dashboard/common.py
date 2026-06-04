"""Common helpers for the admin control-tower dashboard."""

from __future__ import annotations

from typing import Dict, List

from django.urls import reverse

from app.models.classes import Term
from app.selectors.school_settings import get_current_academic_year

ADMIN_CONTROL_ROLES = {
    "Admin",
    "Head Teacher",
    "Head master",
    "Headteacher",
}


def get_active_role(request) -> str:
    """Resolve the active role from session first, then staff account."""
    session_role = (request.session.get("active_role_name") or "").strip()
    if session_role:
        return session_role

    staff_account = getattr(request.user, "staff_account", None)
    if staff_account and getattr(staff_account, "role", None):
        return staff_account.role.name
    return "Support Staff"


def user_can_access_admin_dashboard(request) -> bool:
    """Guard for the admin control-tower pages."""
    if not getattr(request.user, "is_authenticated", False):
        return False
    if getattr(request.user, "is_superuser", False):
        return True
    return get_active_role(request) in ADMIN_CONTROL_ROLES


def resolve_scope(selected_term_param: str = "") -> Dict[str, object]:
    """Resolve current academic year and term scope for dashboard filters."""
    selected_term_param = (selected_term_param or "").strip()
    current_year = get_current_academic_year()
    current_term_flagged = (
        Term.objects.filter(is_current=True).select_related("academic_year").first()
    )

    term_options: List[Term] = []
    selected_term = None
    selected_term_label = ""

    if current_year:
        term_options = list(
            Term.objects.filter(academic_year=current_year)
            .select_related("academic_year")
            .order_by("term")
        )
        valid_term_ids = {str(term.id) for term in term_options}

        if selected_term_param in valid_term_ids:
            selected_term = next(
                (term for term in term_options if str(term.id) == selected_term_param), None
            )
        elif (
            current_term_flagged
            and current_term_flagged.academic_year_id == current_year.id
        ):
            selected_term = current_term_flagged
        elif term_options:
            selected_term = term_options[0]
        else:
            selected_term = current_term_flagged
    else:
        selected_term = current_term_flagged
        if selected_term:
            current_year = selected_term.academic_year
            term_options = list(
                Term.objects.filter(academic_year=current_year)
                .select_related("academic_year")
                .order_by("term")
            )

    if selected_term:
        selected_term_label = (
            f"Term {selected_term.term} {selected_term.academic_year.academic_year}"
        )

    return {
        "current_year": current_year,
        "current_term": selected_term,
        "term_options": term_options,
        "selected_term": str(selected_term.id) if selected_term else "",
        "selected_term_label": selected_term_label,
        "scope_is_configured": bool(current_year and selected_term),
    }


def get_section_navigation(active_section: str) -> List[Dict[str, str]]:
    """Section tabs for the control-tower pages."""
    sections = [
        {
            "key": "overview",
            "label": "Overview",
            "icon": "fa-th-large",
            "url": reverse("dashboard_overview"),
        },
        {
            "key": "finance",
            "label": "Finance",
            "icon": "fa-line-chart",
            "url": reverse("dashboard_finance"),
        },
        {
            "key": "academics",
            "label": "Academics",
            "icon": "fa-graduation-cap",
            "url": reverse("dashboard_academics"),
        },
        {
            "key": "attendance",
            "label": "Attendance",
            "icon": "fa-calendar-check-o",
            "url": reverse("dashboard_attendance"),
        },
        {
            "key": "reports",
            "label": "Reports",
            "icon": "fa-file-text-o",
            "url": reverse("dashboard_reports"),
        },
    ]
    for section in sections:
        section["is_active"] = section["key"] == active_section
    return sections


def get_dashboard_base_context(
    request,
    scope: Dict[str, object],
    *,
    active_section: str,
    section_title: str,
) -> Dict[str, object]:
    """Shared context for all admin control-tower section templates."""
    user_role = get_active_role(request)
    return {
        "user_role": user_role,
        "is_admin_dashboard": user_role in ADMIN_CONTROL_ROLES,
        "dashboard_section_title": section_title,
        "dashboard_sections": get_section_navigation(active_section),
        "current_year": scope.get("current_year"),
        "current_term": scope.get("current_term"),
        "selected_term": scope.get("selected_term"),
        "selected_term_label": scope.get("selected_term_label", ""),
        "term_options": scope.get("term_options", []),
        "scope_is_configured": scope.get("scope_is_configured", False),
    }
