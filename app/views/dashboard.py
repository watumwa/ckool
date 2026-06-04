from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from app.services.dashboard import (
    get_academics_context,
    get_attendance_context,
    get_dashboard_base_context,
    get_finance_context,
    get_overview_context,
    get_reports_context,
    resolve_scope,
    user_can_access_admin_dashboard,
)


def _render_dashboard_section(
    request,
    *,
    template_name: str,
    section_key: str,
    section_title: str,
    section_context_fn,
):
    if not user_can_access_admin_dashboard(request):
        messages.error(
            request,
            "You do not have access to the Admin Control Tower. Switch to an admin role.",
        )
        return redirect("index_page")

    scope = resolve_scope(request.GET.get("term", ""))
    context = get_dashboard_base_context(
        request,
        scope,
        active_section=section_key,
        section_title=section_title,
    )
    context.update(section_context_fn(request, scope))
    return render(request, template_name, context)


@login_required
def dashboard_overview_view(request):
    return _render_dashboard_section(
        request,
        template_name="dashboard/overview.html",
        section_key="overview",
        section_title="Overview",
        section_context_fn=get_overview_context,
    )


@login_required
def dashboard_finance_view(request):
    return _render_dashboard_section(
        request,
        template_name="dashboard/finance.html",
        section_key="finance",
        section_title="Finance",
        section_context_fn=get_finance_context,
    )


@login_required
def dashboard_academics_view(request):
    return _render_dashboard_section(
        request,
        template_name="dashboard/academics.html",
        section_key="academics",
        section_title="Academics",
        section_context_fn=get_academics_context,
    )


@login_required
def dashboard_attendance_view(request):
    return _render_dashboard_section(
        request,
        template_name="dashboard/attendance.html",
        section_key="attendance",
        section_title="Attendance",
        section_context_fn=get_attendance_context,
    )


@login_required
def dashboard_reports_view(request):
    return _render_dashboard_section(
        request,
        template_name="dashboard/reports.html",
        section_key="reports",
        section_title="Reports",
        section_context_fn=get_reports_context,
    )
