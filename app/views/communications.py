from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.db.models import Q, Count
from app.forms.communications import AnnouncementForm, EventForm, MessageThreadForm, MessageForm
from app.models.communications import Announcement, Event, MessageThread, Message, AnnouncementTarget, MessageThreadArchive
from app.models.accounts import StaffAccount
from app.models.classes import AcademicClassStream, ClassSubjectAllocation


def _is_admin_or_head(request):
    staff_account = getattr(request.user, "staff_account", None)
    role_name = staff_account.role.name if staff_account and staff_account.role else None
    active_role = request.session.get("active_role_name")
    effective_role = active_role or role_name
    return effective_role in {"Admin", "Head Teacher", "Head master"}


def _can_target_head_teacher(request):
    staff_account = getattr(request.user, "staff_account", None)
    role_name = staff_account.role.name if staff_account and staff_account.role else None
    active_role = request.session.get("active_role_name")
    effective_role = active_role or role_name
    return effective_role not in {"Teacher", "Class Teacher"}


def _audience_filter(request):
    staff_account = getattr(request.user, "staff_account", None)
    role_name = staff_account.role.name if staff_account and staff_account.role else None
    active_role = request.session.get("active_role_name")
    effective_role = active_role or role_name

    if effective_role in {"Admin", "Head Teacher", "Head master"}:
        return None
    if effective_role == "Director of Studies":
        return ["all", "dos"]
    if effective_role == "Bursar":
        return ["all", "bursar"]
    if effective_role == "Class Teacher":
        return ["all", "class_teacher", "teachers"]
    if effective_role == "Teacher":
        return ["all", "teachers"]
    return ["all"]


def _effective_role(request):
    staff_account = getattr(request.user, "staff_account", None)
    role_name = staff_account.role.name if staff_account and staff_account.role else None
    active_role = request.session.get("active_role_name")
    return active_role or role_name


@login_required
def announcement_list(request):
    can_target_head = _can_target_head_teacher(request)
    effective_role = _effective_role(request)
    audience = _audience_filter(request)
    now = timezone.now()
    announcements = Announcement.objects.all()
    if audience is not None:
        announcements = announcements.filter(audience__in=audience)
        announcements = announcements.exclude(audience="class_stream")
        announcements = announcements.filter(is_active=True, starts_at__lte=now).filter(
            Q(ends_at__isnull=True) | Q(ends_at__gte=now)
        )

    # Append class stream announcements for class teachers
    if _effective_role(request) == "Class Teacher":
        staff_account = StaffAccount.objects.filter(user=request.user).select_related("staff").first()
        if staff_account and staff_account.staff:
            class_streams = AcademicClassStream.objects.filter(class_teacher=staff_account.staff)
            teacher_ids = ClassSubjectAllocation.objects.filter(
                academic_class_stream__in=class_streams
            ).values_list("subject_teacher_id", flat=True)
            announcements = announcements | Announcement.objects.filter(
                audience="class_stream",
                targets__staff_id__in=teacher_ids,
                is_active=True,
                starts_at__lte=now,
            ).filter(Q(ends_at__isnull=True) | Q(ends_at__gte=now))
    total_count = announcements.count()
    active_count = announcements.filter(is_active=True).count()
    high_count = announcements.filter(priority="high").count()
    pinned_announcements = announcements.filter(priority="high")[:5]

    return render(request, "communications/announcements_list.html", {
        "announcements": announcements,
        "can_manage": _is_admin_or_head(request),
        "user_role": effective_role,
        "form": AnnouncementForm(can_target_head=can_target_head, effective_role=effective_role),
        "can_target_head": can_target_head,
        "announcement_total": total_count,
        "announcement_active": active_count,
        "announcement_high": high_count,
        "pinned_announcements": pinned_announcements,
    })


@login_required
def announcement_create(request):
    can_target_head = _can_target_head_teacher(request)
    effective_role = _effective_role(request)
    if request.method == "POST":
        form = AnnouncementForm(request.POST, can_target_head=can_target_head, effective_role=effective_role)
        if form.is_valid():
            announcement = form.save(commit=False)
            if not can_target_head and announcement.audience == "head":
                messages.error(request, "Teachers cannot target Head Teacher.")
                return redirect("announcement_create")
            if announcement.audience == "class_stream" and effective_role != "Class Teacher":
                messages.error(request, "Only Class Teachers can target class stream teachers.")
                return redirect("announcement_create")
            announcement.created_by = request.user
            announcement.save()
            if announcement.audience == "class_stream":
                staff_account = StaffAccount.objects.filter(user=request.user).select_related("staff").first()
                if staff_account and staff_account.staff:
                    class_streams = AcademicClassStream.objects.filter(class_teacher=staff_account.staff)
                    teacher_ids = ClassSubjectAllocation.objects.filter(
                        academic_class_stream__in=class_streams
                    ).values_list("subject_teacher_id", flat=True)
                    AnnouncementTarget.objects.bulk_create([
                        AnnouncementTarget(announcement=announcement, staff_id=teacher_id)
                        for teacher_id in teacher_ids
                    ])
            messages.success(request, "Announcement created.")
            return redirect("announcement_list")
    else:
        form = AnnouncementForm(initial={"starts_at": timezone.now()}, can_target_head=can_target_head, effective_role=effective_role)
    return render(request, "communications/announcement_form.html", {"form": form, "can_target_head": can_target_head})


@login_required
def announcement_edit(request, pk):
    can_target_head = _can_target_head_teacher(request)
    effective_role = _effective_role(request)
    announcement = get_object_or_404(Announcement, pk=pk)
    if request.method == "POST":
        form = AnnouncementForm(request.POST, instance=announcement, can_target_head=can_target_head, effective_role=effective_role)
        if form.is_valid():
            updated = form.save(commit=False)
            if not can_target_head and updated.audience == "head":
                messages.error(request, "Teachers cannot target Head Teacher.")
                return redirect("announcement_edit", pk=announcement.pk)
            if updated.audience == "class_stream" and effective_role != "Class Teacher":
                messages.error(request, "Only Class Teachers can target class stream teachers.")
                return redirect("announcement_edit", pk=announcement.pk)
            updated.save()
            if updated.audience == "class_stream":
                updated.targets.all().delete()
                staff_account = StaffAccount.objects.filter(user=request.user).select_related("staff").first()
                if staff_account and staff_account.staff:
                    class_streams = AcademicClassStream.objects.filter(class_teacher=staff_account.staff)
                    teacher_ids = ClassSubjectAllocation.objects.filter(
                        academic_class_stream__in=class_streams
                    ).values_list("subject_teacher_id", flat=True)
                    AnnouncementTarget.objects.bulk_create([
                        AnnouncementTarget(announcement=updated, staff_id=teacher_id)
                        for teacher_id in teacher_ids
                    ])
            messages.success(request, "Announcement updated.")
            return redirect("announcement_list")
    else:
        form = AnnouncementForm(instance=announcement, can_target_head=can_target_head, effective_role=effective_role)
    return render(request, "communications/announcement_form.html", {
        "form": form,
        "announcement": announcement,
        "can_target_head": can_target_head,
    })


@login_required
def announcement_delete(request, pk):
    announcement = get_object_or_404(Announcement, pk=pk)
    if announcement.created_by != request.user and not _is_admin_or_head(request):
        messages.error(request, "You can only delete your own announcements.")
        return redirect("announcement_list")
    announcement.delete()
    messages.success(request, "Announcement deleted.")
    return redirect("announcement_list")


@login_required
def event_list(request):
    can_target_head = _can_target_head_teacher(request)
    effective_role = _effective_role(request)
    audience = _audience_filter(request)
    now = timezone.now()
    events = Event.objects.all()
    if audience is not None:
        events = events.filter(audience__in=audience)
        events = events.filter(is_active=True, start_datetime__gte=now)
    total_count = events.count()
    active_count = events.filter(is_active=True).count()

    return render(request, "communications/events_list.html", {
        "events": events,
        "can_manage": _is_admin_or_head(request),
        "user_role": effective_role,
        "form": EventForm(can_target_head=can_target_head, effective_role=effective_role),
        "can_target_head": can_target_head,
        "event_total": total_count,
        "event_active": active_count,
    })


@login_required
def message_inbox(request):
    show_archived = request.GET.get("archived") == "1"
    archive_ids = MessageThreadArchive.objects.filter(user=request.user).values_list("thread_id", flat=True)

    threads = MessageThread.objects.filter(participants=request.user).distinct()
    if show_archived:
        threads = threads.filter(id__in=archive_ids)
    else:
        threads = threads.exclude(id__in=archive_ids)

    threads = threads.order_by("-updated_at").prefetch_related("participants")

    thread_items = []
    for thread in threads:
        others = [p for p in thread.participants.all() if p != request.user]
        thread_items.append({
            "thread": thread,
            "others": others,
        })

    return render(request, "communications/messages_inbox.html", {
        "threads": threads,
        "thread_items": thread_items,
        "show_archived": show_archived,
    })


@login_required
def message_thread(request, pk):
    thread = get_object_or_404(MessageThread, pk=pk, participants=request.user)

    if request.method == "POST" and request.POST.get("archive"):
        MessageThreadArchive.objects.get_or_create(thread=thread, user=request.user)
        messages.success(request, "Conversation archived.")
        return redirect("message_inbox")

    if request.method == "POST" and request.POST.get("unarchive"):
        MessageThreadArchive.objects.filter(thread=thread, user=request.user).delete()
        messages.success(request, "Conversation unarchived.")
        return redirect("message_inbox")

    if request.method == "POST" and request.POST.get("delete_message_id"):
        msg_id = request.POST.get("delete_message_id")
        msg = get_object_or_404(Message, pk=msg_id, sender=request.user, thread=thread)
        msg.delete()
        messages.success(request, "Message deleted.")
        return redirect("message_thread", pk=pk)

    if request.method == "POST":
        form = MessageForm(request.POST)
        if form.is_valid():
            msg = form.save(commit=False)
            msg.thread = thread
            msg.sender = request.user
            msg.save()
            thread.updated_at = timezone.now()
            thread.save(update_fields=["updated_at"])
            return redirect("message_thread", pk=pk)
    else:
        form = MessageForm()

    is_archived = MessageThreadArchive.objects.filter(thread=thread, user=request.user).exists()

    return render(request, "communications/message_thread.html", {
        "thread": thread,
        "form": form,
        "is_archived": is_archived,
    })


@login_required
def message_new(request):
    effective_role = _effective_role(request)
    if request.method == "POST":
        form = MessageThreadForm(request.POST, sender=request.user, effective_role=effective_role)
        if form.is_valid():
            recipients = list(form.cleaned_data["recipients"])
            subject = form.cleaned_data.get("subject", "")

            participant_users = [request.user] + [r.user for r in recipients]

            existing_thread = MessageThread.objects.filter(participants=request.user).distinct()
            for user in participant_users[1:]:
                existing_thread = existing_thread.filter(participants=user)

            existing_thread = existing_thread.annotate(p_count=Count("participants")).filter(
                p_count=len(participant_users)
            ).first()

            if existing_thread:
                thread = existing_thread
            else:
                thread = MessageThread.objects.create(
                    subject=subject,
                    created_by=request.user,
                )
                thread.participants.add(*participant_users)

            # initial message
            body = request.POST.get("body")
            if body:
                Message.objects.create(thread=thread, sender=request.user, body=body)
                thread.updated_at = timezone.now()
                thread.save(update_fields=["updated_at"])

            MessageThreadArchive.objects.filter(thread=thread, user=request.user).delete()

            return redirect("message_thread", pk=thread.pk)
    else:
        form = MessageThreadForm(sender=request.user, effective_role=effective_role)
    return render(request, "communications/message_new.html", {"form": form})


@login_required
def event_create(request):
    can_target_head = _can_target_head_teacher(request)
    if request.method == "POST":
        form = EventForm(request.POST, can_target_head=can_target_head)
        if form.is_valid():
            event = form.save(commit=False)
            if not can_target_head and event.audience == "head":
                messages.error(request, "Teachers cannot target Head Teacher.")
                return redirect("event_create")
            event.created_by = request.user
            event.save()
            messages.success(request, "Event created.")
            return redirect("event_list")
    else:
        form = EventForm(can_target_head=can_target_head)
    return render(request, "communications/event_form.html", {"form": form, "can_target_head": can_target_head})


@login_required
def event_edit(request, pk):
    can_target_head = _can_target_head_teacher(request)
    event = get_object_or_404(Event, pk=pk)
    if request.method == "POST":
        form = EventForm(request.POST, instance=event, can_target_head=can_target_head)
        if form.is_valid():
            updated = form.save(commit=False)
            if not can_target_head and updated.audience == "head":
                messages.error(request, "Teachers cannot target Head Teacher.")
                return redirect("event_edit", pk=event.pk)
            updated.save()
            messages.success(request, "Event updated.")
            return redirect("event_list")
    else:
        form = EventForm(instance=event, can_target_head=can_target_head)
    return render(request, "communications/event_form.html", {
        "form": form,
        "event": event,
        "can_target_head": can_target_head,
    })


@login_required
def event_delete(request, pk):
    event = get_object_or_404(Event, pk=pk)
    if event.created_by != request.user and not _is_admin_or_head(request):
        messages.error(request, "You can only delete your own events.")
        return redirect("event_list")
    event.delete()
    messages.success(request, "Event deleted.")
    return redirect("event_list")
