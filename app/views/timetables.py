import json
from datetime import timedelta
from urllib.parse import urlencode
from django.shortcuts import render, redirect
from django.contrib import messages
from django.core.exceptions import ValidationError
from app.models.timetables import  TimeSlot, Timetable, Classroom, WeekDay, BreakPeriod
from django.contrib.auth.decorators import login_required
from django.urls import reverse
from app.models.accounts import StaffAccount
from app.models.classes import AcademicClassStream, AcademicClass, Term
from app.models.attendance import AttendanceSession
from app.models.students import ClassRegister
from app.models.school_settings import AcademicYear, SchoolSetting
from app.forms.timetables import TimeSlotForm
from app.services.teacher_assignments import get_allocation_queryset, get_teacher_assignments
from collections import defaultdict
from django.db.models import Q
from django.http import HttpResponse
from django.template.loader import render_to_string
from xhtml2pdf import pisa
from django.utils import timezone



@login_required
def timetable_center(request):
    staff_account = getattr(request.user, "staff_account", None)
    role_name = str(getattr(getattr(staff_account, "role", None), "name", "") or "").lower()
    active_role = str(request.session.get("active_role_name") or "").lower()
    effective_role = active_role or role_name
    editable_roles = {"admin", "director of studies", "dos"}
    lock_roles = {"admin", "head master", "head teacher", "headteacher"}
    can_edit_timetable = effective_role in editable_roles
    can_lock_timetable = effective_role in lock_roles
    hide_time_slots = not can_edit_timetable

    all_class_streams = (
        AcademicClassStream.objects
        .select_related(
            "academic_class__Class",
            "academic_class__academic_year",
            "academic_class__term",
            "stream",
            "class_teacher",
        )
        .order_by(
            "-academic_class__academic_year__academic_year",
            "-academic_class__term__term",
            "academic_class__Class__name",
            "stream__stream",
        )
        .distinct()
    )

    year_ids = all_class_streams.values_list("academic_class__academic_year_id", flat=True).distinct()
    academic_years = AcademicYear.objects.filter(id__in=year_ids).order_by("-academic_year", "-id")

    selected_year_id = request.GET.get("academic_year") or request.POST.get("academic_year")
    if selected_year_id and not academic_years.filter(pk=selected_year_id).exists():
        selected_year_id = None
    if not selected_year_id:
        default_year = academic_years.filter(is_current=True).first() or academic_years.first()
        selected_year_id = str(default_year.id) if default_year else ""

    term_ids = all_class_streams.values_list("academic_class__term_id", flat=True).distinct()
    selected_term_id = request.GET.get("term") or request.POST.get("term")

    selected_class_id = request.GET.get("class_stream_id") or request.POST.get("class_stream_id")
    preselected_class = (
        all_class_streams.filter(pk=selected_class_id).first()
        if selected_class_id
        else None
    )
    if preselected_class:
        selected_year_id = str(preselected_class.academic_class.academic_year_id)
        selected_term_id = str(preselected_class.academic_class.term_id)

    # Recompute terms for the effective academic year context.
    terms = Term.objects.filter(id__in=term_ids)
    if selected_year_id:
        terms = terms.filter(academic_year_id=selected_year_id)
    terms = terms.order_by("term", "start_date", "id")
    if selected_term_id and not terms.filter(pk=selected_term_id).exists():
        selected_term_id = None
    if not selected_term_id:
        default_term = terms.filter(is_current=True).first() or terms.first()
        selected_term_id = str(default_term.id) if default_term else ""

    class_streams = all_class_streams
    if selected_year_id:
        class_streams = class_streams.filter(academic_class__academic_year_id=selected_year_id)
    if selected_term_id:
        class_streams = class_streams.filter(academic_class__term_id=selected_term_id)

    selected_class = None
    if selected_class_id:
        selected_class = class_streams.filter(pk=selected_class_id).first()
        if not selected_class:
            selected_class_id = None

    def _redirect_url(class_stream_id=None):
        params = {}
        if selected_year_id:
            params["academic_year"] = selected_year_id
        if selected_term_id:
            params["term"] = selected_term_id
        stream_id = class_stream_id if class_stream_id is not None else selected_class_id
        if stream_id:
            params["class_stream_id"] = stream_id
        query = urlencode(params)
        return f"{request.path}?{query}" if query else request.path

    time_slots = TimeSlot.objects.order_by('start_time', 'end_time', 'id')
    time_slot_form = TimeSlotForm()
    timetable_data = {}
    break_map = {}
    break_any_slots = {}
    allocation_subjects = []
    allocation_subject_ids = []
    allocation_teacher_map = {}
    conflict_alerts = []
    total_students = 0
    subjects_allocated_count = 0
    is_timetable_locked = bool(getattr(selected_class, "is_timetable_locked", False))

    if selected_class_id:
        timetable_entries = Timetable.objects.filter(class_stream=selected_class).select_related(
            'time_slot',
            'subject',
            'teacher',
            'classroom',
            'allocation',
        )
        # Build nested dict for template access: timetable_data[weekday][slot_id] = entry
        nested = defaultdict(dict)
        for entry in timetable_entries:
            nested[entry.weekday][entry.time_slot.id] = entry
        timetable_data = nested

        break_qs = BreakPeriod.objects.select_related("time_slot").all()
        break_map = {f"{b.weekday}_{b.time_slot_id}": b for b in break_qs}
        break_any_slots = {b.time_slot_id: b for b in break_qs}

        allocation_subjects = list(
            get_allocation_queryset(
                class_streams=[selected_class],
                current_year=selected_class.academic_class.academic_year,
                current_term=selected_class.academic_class.term,
            )
        )
        allocation_subject_ids = [row.subject_id for row in allocation_subjects]
        allocation_teacher_map = {
            str(row.subject_id): {
                "teacher_id": row.subject_teacher_id or "",
                "teacher_name": str(row.subject_teacher) if row.subject_teacher else "",
            }
            for row in allocation_subjects
        }
        total_students = ClassRegister.objects.filter(academic_class_stream=selected_class).count()
        subjects_allocated_count = len(allocation_subjects)

        teacher_ids = [entry.teacher_id for entry in timetable_entries if entry.teacher_id]
        if teacher_ids:
            overlap_rows = Timetable.objects.filter(
                teacher_id__in=teacher_ids
            ).exclude(
                class_stream=selected_class
            ).select_related(
                "teacher",
                "time_slot",
                "class_stream__academic_class__Class",
                "class_stream__stream",
            )
            overlap_map = defaultdict(list)
            for row in overlap_rows:
                overlap_map[(row.teacher_id, row.weekday, row.time_slot_id)].append(row)

            weekday_labels = dict(WeekDay.choices)
            seen_conflicts = set()
            for entry in timetable_entries:
                for other in overlap_map.get((entry.teacher_id, entry.weekday, entry.time_slot_id), []):
                    conflict_key = (
                        entry.teacher_id,
                        entry.weekday,
                        entry.time_slot_id,
                        other.class_stream_id,
                    )
                    if conflict_key in seen_conflicts:
                        continue
                    seen_conflicts.add(conflict_key)
                    other_stream = (
                        f"{other.class_stream.academic_class.Class.code}"
                        f"{other.class_stream.stream.stream}"
                    )
                    conflict_alerts.append(
                        {
                            "teacher": str(entry.teacher),
                            "weekday": weekday_labels.get(entry.weekday, entry.weekday),
                            "time_slot": str(entry.time_slot),
                            "other_stream": other_stream,
                            "link": reverse("school_timetable"),
                            "message": (
                                f"{entry.teacher} is already assigned to {other_stream} "
                                f"{weekday_labels.get(entry.weekday, entry.weekday)} {entry.time_slot}."
                            ),
                        }
                    )

    if request.method == 'POST':
        action = request.POST.get('action')

        posted_class_id = request.POST.get("class_stream_id") or selected_class_id
        if posted_class_id and (not selected_class or str(selected_class.id) != str(posted_class_id)):
            selected_class = all_class_streams.filter(pk=posted_class_id).first()
            if selected_class:
                selected_class_id = str(selected_class.id)
                selected_year_id = str(selected_class.academic_class.academic_year_id)
                selected_term_id = str(selected_class.academic_class.term_id)
                is_timetable_locked = bool(selected_class.is_timetable_locked)

        if action in {'add_time_slot', 'edit_time_slot', 'delete_time_slot'} and not can_edit_timetable:
            messages.error(request, "Only Admin or Director of Studies can manage periods.")
            return redirect(_redirect_url())

        if action == 'add_time_slot':
            time_slot_form = TimeSlotForm(request.POST)
            if time_slot_form.is_valid():
                time_slot_form.save()
                messages.success(request, "Time slot added successfully.")
            else:
                messages.error(request, "Please correct the time slot form errors.")
            return redirect(_redirect_url())

        if action == 'edit_time_slot':
            slot_id = request.POST.get('slot_id')
            slot = TimeSlot.objects.filter(pk=slot_id).first()
            if not slot:
                messages.error(request, "Time slot not found.")
                return redirect(_redirect_url())
            edit_form = TimeSlotForm(request.POST, instance=slot)
            if edit_form.is_valid():
                edit_form.save()
                messages.success(request, "Time slot updated successfully.")
            else:
                messages.error(request, "Please correct the time slot form errors.")
            return redirect(_redirect_url())

        if action == 'delete_time_slot':
            slot_id = request.POST.get('slot_id')
            slot = TimeSlot.objects.filter(pk=slot_id).first()
            if not slot:
                messages.error(request, "Time slot not found.")
                return redirect(_redirect_url())
            if Timetable.objects.filter(time_slot=slot).exists():
                messages.error(request, "Cannot delete a time slot that is used in the timetable.")
                return redirect(_redirect_url())
            slot.delete()
            messages.success(request, "Time slot deleted successfully.")
            return redirect(_redirect_url())

        if not selected_class:
            messages.error(request, "Please select class stream first.")
            return redirect(_redirect_url())

        if action == "toggle_lock":
            if not can_lock_timetable:
                messages.error(request, "Only Admin can lock or unlock timetable.")
                return redirect(_redirect_url(selected_class.id))
            lock_value = request.POST.get("lock") == "1"
            if bool(selected_class.is_timetable_locked) == lock_value:
                messages.info(
                    request,
                    "Timetable lock status is already up to date.",
                )
            else:
                selected_class.is_timetable_locked = lock_value
                selected_class.save(update_fields=["is_timetable_locked"])
                status = "locked" if lock_value else "unlocked"
                messages.success(request, f"Timetable {status} successfully.")
            return redirect(_redirect_url(selected_class.id))

        if action == 'print_pdf':
            timetable_entries = Timetable.objects.filter(
                class_stream=selected_class
            ).select_related('time_slot', 'subject', 'teacher', 'classroom')

            nested = defaultdict(dict)
            for entry in timetable_entries:
                nested[entry.weekday][entry.time_slot.id] = entry

            school = SchoolSetting.load()
            break_qs = BreakPeriod.objects.select_related("time_slot").all()
            break_map = {f"{b.weekday}_{b.time_slot_id}": b for b in break_qs}
            break_any_slots = {b.time_slot_id: b for b in break_qs}

            context = {
                "school": school,
                "class_stream": selected_class,
                "academic_year": getattr(selected_class.academic_class.academic_year, "academic_year", "-"),
                "term": getattr(selected_class.academic_class.term, "term", "-"),
                "time_slots": TimeSlot.objects.all(),
                "weekdays": WeekDay.choices,
                "timetable_data": nested,
                "break_map": break_map,
                "break_any_slots": break_any_slots,
                "generated_at": timezone.now(),
            }
            html = render_to_string("timetable/timetable_print.html", context)
            response = HttpResponse(content_type="application/pdf")
            response["Content-Disposition"] = "inline; filename=timetable.pdf"
            pisa_status = pisa.CreatePDF(html, dest=response)
            if pisa_status.err:
                return HttpResponse("PDF generation error", status=500)
            return response

        if action == 'copy_previous':
            if not can_edit_timetable:
                messages.error(request, "Only Admin or Director of Studies can edit timetable.")
                return redirect(_redirect_url(selected_class.id))
            if selected_class.is_timetable_locked:
                messages.error(request, "Timetable is locked. Unlock it first to make changes.")
                return redirect(_redirect_url(selected_class.id))

            # Current context
            curr_ac = selected_class.academic_class
            curr_term_code = curr_ac.term.term  # "1" | "2" | "3"
            curr_year_pk = curr_ac.academic_year.pk

            # Find the most recent earlier AcademicClass for the same base Class
            # Earlier means: any prior year, or same year with a lower term number.
            earlier_ac_qs = (
                AcademicClass.objects
                .filter(Class=curr_ac.Class)
                .filter(
                    Q(academic_year__pk__lt=curr_year_pk) |
                    Q(academic_year__pk=curr_year_pk, term__term__lt=curr_term_code)
                )
                .order_by('-academic_year__pk', '-term__term')
            )

            source_stream = None
            source_ac = None

            # Strategy: choose the first earlier stream that actually has timetable entries.
            for ac in earlier_ac_qs:
                cand_stream = AcademicClassStream.objects.filter(
                    academic_class=ac,
                    stream=selected_class.stream
                ).first()
                if not cand_stream:
                    continue
                if Timetable.objects.filter(class_stream=cand_stream).exists():
                    source_stream = cand_stream
                    source_ac = ac
                    break

            # If none of the earlier streams have entries, fall back to the immediate previous AcademicClass (if any)
            if source_stream is None:
                source_ac = earlier_ac_qs.first()
                if source_ac:
                    source_stream = AcademicClassStream.objects.filter(
                        academic_class=source_ac,
                        stream=selected_class.stream
                    ).first()

            # If still nothing found, inform and exit
            if not source_stream:
                messages.warning(request, "No previous class stream found to copy from for this Class/Stream.")
                return redirect(_redirect_url(selected_class.id))

            prev_entries = (
                Timetable.objects
                .filter(class_stream=source_stream)
                .select_related('time_slot', 'subject', 'teacher', 'classroom')
            )

            if not prev_entries:
                messages.warning(request, "No timetable entries found in previous terms for this stream to copy.")
                return redirect(_redirect_url(selected_class.id))

            allocation_rows = list(
                get_allocation_queryset(
                    class_streams=[selected_class],
                    current_year=selected_class.academic_class.academic_year,
                    current_term=selected_class.academic_class.term,
                )
            )
            allocation_by_subject = {allocation.subject_id: allocation for allocation in allocation_rows}
            if not allocation_by_subject:
                messages.warning(
                    request,
                    "No subject allocations are configured for this class stream. "
                    "Set allocations first, then copy the timetable.",
                )
                return redirect(_redirect_url(selected_class.id))

            created_or_updated = 0
            skipped_teacher_conflicts = 0
            skipped_room = 0
            skipped_missing_allocation = 0
            skipped_invalid = 0

            for e in prev_entries:
                allocation = allocation_by_subject.get(e.subject_id)
                if not allocation:
                    skipped_missing_allocation += 1
                    continue

                assigned_teacher = allocation.subject_teacher
                if assigned_teacher:
                    teacher_in_use = (
                        Timetable.objects
                        .filter(teacher=assigned_teacher, weekday=e.weekday, time_slot=e.time_slot)
                        .exclude(class_stream=selected_class)
                        .exists()
                    )
                    if teacher_in_use:
                        skipped_teacher_conflicts += 1
                        continue

                defaults = {
                    'subject': allocation.subject,
                    'teacher': assigned_teacher,
                    'classroom': e.classroom,
                    'allocation': allocation,
                }

                # Avoid classroom conflicts across other class streams at same weekday+slot
                if e.classroom_id:
                    room_in_use = (
                        Timetable.objects
                        .filter(classroom=e.classroom, weekday=e.weekday, time_slot=e.time_slot)
                        .exclude(class_stream=selected_class)
                        .exists()
                    )
                    if room_in_use:
                        defaults['classroom'] = None
                        skipped_room += 1

                try:
                    Timetable.objects.update_or_create(
                        class_stream=selected_class,
                        weekday=e.weekday,
                        time_slot=e.time_slot,
                        defaults=defaults
                    )
                    created_or_updated += 1
                except ValidationError:
                    skipped_invalid += 1

            msg = f"Copied {created_or_updated} timetable entries from the most recent previous term."
            if (
                skipped_teacher_conflicts
                or skipped_room
                or skipped_missing_allocation
                or skipped_invalid
            ):
                parts = []
                if skipped_teacher_conflicts:
                    parts.append(f"{skipped_teacher_conflicts} teacher conflict(s) skipped")
                if skipped_room:
                    parts.append(f"{skipped_room} room conflict(s) cleared")
                if skipped_missing_allocation:
                    parts.append(f"{skipped_missing_allocation} subject(s) had no allocation")
                if skipped_invalid:
                    parts.append(f"{skipped_invalid} invalid row(s) skipped")
                msg += " (" + ", ".join(parts) + ")."
            messages.success(request, msg)
            return redirect(_redirect_url(selected_class.id))

        if action == 'auto_generate':
            if not can_edit_timetable:
                messages.error(request, "Only Admin or Director of Studies can edit timetable.")
                return redirect(_redirect_url(selected_class.id))
            if selected_class.is_timetable_locked:
                messages.error(request, "Timetable is locked. Unlock it first to make changes.")
                return redirect(_redirect_url(selected_class.id))

            time_slots = list(TimeSlot.objects.all())
            weekdays = [code for code, _ in WeekDay.choices]

            allocations = list(
                get_allocation_queryset(
                    class_streams=[selected_class],
                    current_year=selected_class.academic_class.academic_year,
                    current_term=selected_class.academic_class.term,
                )
            )

            if not allocations:
                messages.warning(request, "No subject allocations found for this class stream.")
                return redirect(_redirect_url(selected_class.id))

            slot_index = 0

            total_slots = len(time_slots) * len(weekdays)
            if total_slots == 0:
                messages.error(request, "Please configure time slots before auto-generating the timetable.")
                return redirect(_redirect_url(selected_class.id))

            for allocation in allocations:
                if slot_index >= total_slots:
                    messages.warning(request, "Not enough time slots to schedule all allocations.")
                    break

                day_index = slot_index // len(time_slots)
                time_index = slot_index % len(time_slots)
                weekday_code = weekdays[day_index]
                time_slot = time_slots[time_index]
                assigned_teacher = allocation.subject_teacher

                # Skip conflicts for teacher/classroom by finding next free slot
                attempts = 0
                while attempts < total_slots:
                    conflict_filter = Q(class_stream=selected_class, weekday=weekday_code, time_slot=time_slot)
                    if assigned_teacher:
                        conflict_filter |= Q(
                            teacher=assigned_teacher,
                            weekday=weekday_code,
                            time_slot=time_slot,
                        )
                    conflict = Timetable.objects.filter(conflict_filter).exists()
                    if not conflict:
                        break
                    slot_index = (slot_index + 1) % total_slots
                    day_index = slot_index // len(time_slots)
                    time_index = slot_index % len(time_slots)
                    weekday_code = weekdays[day_index]
                    time_slot = time_slots[time_index]
                    attempts += 1

                if attempts >= total_slots:
                    messages.warning(
                        request,
                        "Could not place all allocations due to teacher/time conflicts.",
                    )
                    break

                Timetable.objects.update_or_create(
                    class_stream=selected_class,
                    weekday=weekday_code,
                    time_slot=time_slot,
                    defaults={
                        'subject': allocation.subject,
                        'teacher': assigned_teacher,
                        'allocation': allocation,
                        'classroom': None,
                    }
                )
                slot_index += 1

            messages.success(request, "Timetable auto-generated from subject allocations.")
            return redirect(_redirect_url(selected_class.id))

        # Default: save timetable from JSON payload
        timetable_json = request.POST.get('timetable_json')
        if action in {"save_timetable", "", None} and not can_edit_timetable:
            messages.error(request, "Only Admin or Director of Studies can edit timetable.")
            return redirect(_redirect_url(selected_class.id))
        if action in {"save_timetable", "", None} and selected_class.is_timetable_locked:
            messages.error(request, "Timetable is locked. Unlock it first to make changes.")
            return redirect(_redirect_url(selected_class.id))

        saved_count = 0
        cleared_count = 0
        skipped_missing_allocation = 0
        skipped_teacher_mismatch = 0
        skipped_teacher_conflicts = 0
        skipped_room_conflicts = 0
        skipped_bad_slots = 0
        skipped_invalid = 0

        if timetable_json:
            timetable_data = json.loads(timetable_json)
            allocation_rows = list(
                get_allocation_queryset(
                    class_streams=[selected_class],
                    current_year=selected_class.academic_class.academic_year,
                    current_term=selected_class.academic_class.term,
                )
            )
            allocation_by_subject = {allocation.subject_id: allocation for allocation in allocation_rows}

            # Convert label (e.g., "Monday") to short code (e.g., "MON")
            weekday_map = {label: code for code, label in WeekDay.choices}

            for weekday_label, slots in timetable_data.items():
                weekday_code = weekday_map.get(weekday_label, weekday_label)

                for time_slot_id, entry in slots.items():
                    subject_raw = entry.get('subject')
                    if not subject_raw:
                        try:
                            time_slot = TimeSlot.objects.get(pk=time_slot_id)
                        except TimeSlot.DoesNotExist:
                            skipped_bad_slots += 1
                            continue
                        deleted_count, _ = Timetable.objects.filter(
                            class_stream=selected_class,
                            weekday=weekday_code,
                            time_slot=time_slot,
                        ).delete()
                        if deleted_count:
                            cleared_count += 1
                        continue
                    try:
                        subject_id = int(subject_raw)
                    except (TypeError, ValueError):
                        skipped_missing_allocation += 1
                        continue

                    allocation = allocation_by_subject.get(subject_id)
                    if not allocation:
                        skipped_missing_allocation += 1
                        continue

                    teacher_raw = entry.get('teacher')
                    teacher_id = None
                    if teacher_raw not in (None, "", "null"):
                        try:
                            teacher_id = int(teacher_raw)
                        except (TypeError, ValueError):
                            skipped_teacher_mismatch += 1
                            continue
                    if teacher_id and teacher_id != allocation.subject_teacher_id:
                        skipped_teacher_mismatch += 1
                        continue

                    try:
                        time_slot = TimeSlot.objects.get(pk=time_slot_id)
                    except TimeSlot.DoesNotExist:
                        skipped_bad_slots += 1
                        continue

                    if allocation.subject_teacher_id:
                        if Timetable.objects.filter(
                            teacher_id=allocation.subject_teacher_id,
                            weekday=weekday_code,
                            time_slot=time_slot,
                        ).exclude(class_stream=selected_class).exists():
                            skipped_teacher_conflicts += 1
                            continue

                    classroom_raw = entry.get('classroom')
                    classroom_id = None
                    if classroom_raw not in (None, "", "null"):
                        try:
                            classroom_id = int(classroom_raw)
                        except (TypeError, ValueError):
                            classroom_id = None

                    if classroom_id and Timetable.objects.filter(
                        classroom_id=classroom_id,
                        weekday=weekday_code,
                        time_slot=time_slot,
                    ).exclude(class_stream=selected_class).exists():
                        skipped_room_conflicts += 1
                        continue

                    try:
                        Timetable.objects.update_or_create(
                            class_stream=selected_class,
                            weekday=weekday_code,
                            time_slot=time_slot,
                            defaults={
                                'subject': allocation.subject,
                                'teacher': allocation.subject_teacher,
                                'allocation': allocation,
                                'classroom_id': classroom_id,
                            }
                        )
                        saved_count += 1
                    except ValidationError:
                        skipped_invalid += 1

        if saved_count or cleared_count:
            messages.success(
                request,
                f"Timetable updated successfully ({saved_count} saved, {cleared_count} cleared).",
            )
        elif timetable_json:
            messages.warning(request, "No timetable rows were saved.")
        else:
            messages.success(request, "Timetable updated successfully.")

        if (
            skipped_missing_allocation
            or skipped_teacher_mismatch
            or skipped_teacher_conflicts
            or skipped_room_conflicts
            or skipped_bad_slots
            or skipped_invalid
        ):
            parts = []
            if skipped_missing_allocation:
                parts.append(f"{skipped_missing_allocation} row(s) had no subject allocation")
            if skipped_teacher_mismatch:
                parts.append(f"{skipped_teacher_mismatch} row(s) had teacher/allocation mismatch")
            if skipped_teacher_conflicts:
                parts.append(f"{skipped_teacher_conflicts} teacher conflict(s)")
            if skipped_room_conflicts:
                parts.append(f"{skipped_room_conflicts} room conflict(s)")
            if skipped_bad_slots:
                parts.append(f"{skipped_bad_slots} invalid time slot(s)")
            if skipped_invalid:
                parts.append(f"{skipped_invalid} invalid row(s)")
            messages.warning(request, "Some rows were skipped: " + ", ".join(parts) + ".")

        return redirect(_redirect_url(selected_class.id))

    context = {
        "academic_years": academic_years,
        "terms": terms,
        "selected_year_id": str(selected_year_id) if selected_year_id else "",
        "selected_term_id": str(selected_term_id) if selected_term_id else "",
        "class_streams": class_streams,
        "selected_class": selected_class,
        "selected_class_id": str(selected_class_id) if selected_class_id else "",
        "time_slots": time_slots,
        "time_slot_form": time_slot_form,
        "timetable_data": timetable_data,
        "break_map": break_map,
        "break_any_slots": break_any_slots,
        "allocation_subjects": allocation_subjects,
        "allocation_subject_ids": allocation_subject_ids,
        "allocation_teacher_map": allocation_teacher_map,
        "classrooms": Classroom.objects.all(),
        "weekdays": WeekDay.choices,
        "hide_time_slots": hide_time_slots,
        "can_edit_timetable": can_edit_timetable,
        "can_lock_timetable": can_lock_timetable,
        "is_timetable_locked": is_timetable_locked,
        "conflict_alerts": conflict_alerts,
        "total_students": total_students,
        "subjects_allocated_count": subjects_allocated_count,
    }
    return render(request, "timetable/timetable_center.html", context)

def get_time_slots():
    """Utility function to get all time slots in order"""
    return TimeSlot.objects.order_by('start_time').all()


@login_required
def teacher_timetable_view(request):
    user = request.user
    try:
        staff_account = user.staff_account
    except AttributeError:
        messages.error(request, "You are not linked to a staff account.")
        return redirect("dashboard")

    if not hasattr(staff_account, 'staff'):
        messages.error(request, "Access denied.")
        return redirect("dashboard")

    staff = staff_account.staff
    role_names = []
    account_role = getattr(staff_account.role, "name", None)
    if account_role:
        role_names.append(account_role)
    active_role = request.session.get("active_role_name")
    if active_role:
        role_names.append(active_role)
    try:
        role_names.extend(list(staff.roles.values_list("name", flat=True)))
    except Exception:
        pass
    role_names = [str(name).lower() for name in role_names if name]

    if not staff.is_academic_staff and not any("teacher" in name for name in role_names):
        messages.error(request, "Access denied.")
        return redirect("dashboard")

    # Timetable-first assignment source with allocation fallback.
    assignments = get_teacher_assignments(staff)
    subjects = sorted({a.subject for a in assignments}, key=lambda x: x.name)
    class_streams = sorted({a.academic_class_stream for a in assignments}, key=lambda x: str(x))
    assignment_pairs = {(a.academic_class_stream_id, a.subject_id) for a in assignments}

    # Filters from query params
    selected_weekday = request.GET.get("weekday")
    selected_subject = request.GET.get("subject")
    selected_stream = request.GET.get("stream")

    timetable_filter = Q(teacher=staff) | Q(allocation__subject_teacher=staff)
    if selected_weekday:
        timetable_filter &= Q(weekday=selected_weekday)
    if selected_subject:
        timetable_filter &= Q(subject_id=selected_subject)
    if selected_stream:
        timetable_filter &= Q(class_stream_id=selected_stream)

    timetable_entries = Timetable.objects.filter(timetable_filter).select_related(
        'class_stream', 'subject', 'time_slot', 'classroom', 'allocation', 'allocation__subject_teacher'
    ).order_by('weekday', 'time_slot__start_time')

    # Fallback: infer from class-subject assignments when timetable rows do not keep teacher fk.
    if not timetable_entries.exists() and assignment_pairs:
        inferred_filter = Q()
        for class_stream_id, subject_id in assignment_pairs:
            inferred_filter |= Q(class_stream_id=class_stream_id, subject_id=subject_id)
        if selected_weekday:
            inferred_filter &= Q(weekday=selected_weekday)
        if selected_subject:
            inferred_filter &= Q(subject_id=selected_subject)
        if selected_stream:
            inferred_filter &= Q(class_stream_id=selected_stream)

        timetable_entries = Timetable.objects.filter(inferred_filter).select_related(
            'class_stream', 'subject', 'time_slot', 'classroom', 'allocation', 'allocation__subject_teacher'
        ).order_by('weekday', 'time_slot__start_time')

    time_slots = get_time_slots()
    timetable_data = {
        day[0]: {slot.id: [] for slot in time_slots} for day in WeekDay.choices
    }

    timetable_entries = list(timetable_entries)
    if timetable_entries:
        subject_map = {subject.id: subject for subject in subjects}
        class_stream_map = {stream.id: stream for stream in class_streams}
        for entry in timetable_entries:
            subject_map.setdefault(entry.subject_id, entry.subject)
            class_stream_map.setdefault(entry.class_stream_id, entry.class_stream)
        subjects = sorted(subject_map.values(), key=lambda x: x.name)
        class_streams = sorted(class_stream_map.values(), key=lambda x: str(x))

    for entry in timetable_entries:
        if entry.weekday not in timetable_data:
            continue
        timetable_data[entry.weekday][entry.time_slot.id].append(entry)

    today = timezone.localdate()
    weekday_to_index = {code: idx for idx, (code, _) in enumerate(WeekDay.choices)}
    today_index = today.weekday()

    attendance_map = {}
    target_dates = {}
    for entry in timetable_entries:
        lesson_index = weekday_to_index.get(entry.weekday)
        if lesson_index is None:
            continue
        offset = lesson_index - today_index
        lesson_date = today + timedelta(days=offset)
        target_dates[entry.pk] = lesson_date

    sessions = AttendanceSession.objects.filter(
        class_stream_id__in=[entry.class_stream_id for entry in timetable_entries],
        subject_id__in=[entry.subject_id for entry in timetable_entries],
        date__in=list(target_dates.values()),
        time_slot_id__in=[entry.time_slot_id for entry in timetable_entries],
    ).select_related("time_slot")
    session_lookup = {
        (session.class_stream_id, session.subject_id, session.date, session.time_slot_id): session
        for session in sessions
    }

    for entry in timetable_entries:
        lesson_date = target_dates.get(entry.pk)
        key = (entry.class_stream_id, entry.subject_id, lesson_date, entry.time_slot_id)
        session = session_lookup.get(key)
        if session and session.is_locked:
            status_label = "Taken"
            status_icon = "✅"
            status_css = "label-success"
            action_label = "View Attendance"
            action_css = "btn-default"
        elif session:
            status_label = "Draft"
            status_icon = "📝"
            status_css = "label-info"
            action_label = "Take Attendance"
            action_css = "btn-success"
        else:
            status_label = "Pending"
            status_icon = "⏳"
            status_css = "label-warning"
            action_label = "Take Attendance"
            action_css = "btn-success"

        attendance_map[entry.pk] = {
            "status_label": status_label,
            "status_icon": status_icon,
            "status_css": status_css,
            "action_label": action_label,
            "action_css": action_css,
            "target_date": lesson_date.isoformat() if lesson_date else "",
            "action_url": (
                f"{reverse('take_attendance')}?class_stream={entry.class_stream_id}"
                f"&subject={entry.subject_id}&date={lesson_date.isoformat() if lesson_date else today.isoformat()}"
                f"&time_slot={entry.time_slot_id}"
            ),
        }

    context = {
        "timetable_data": timetable_data,
        "time_slots": time_slots,
        "weekdays": WeekDay.choices,
        "teacher": staff,
        "subjects": subjects,
        "class_streams": class_streams,
        "selected_weekday": selected_weekday,
        "selected_subject": selected_subject,
        "selected_stream": selected_stream,
        "attendance_map": attendance_map,
        "today": today,
    }

    return render(request, "timetable/teacher_timetable.html", context)


@login_required
def school_timetable_overview(request):
    time_slots = TimeSlot.objects.order_by('start_time', 'end_time')
    class_streams = (
        AcademicClassStream.objects
        .select_related('academic_class__Class', 'academic_class__academic_year', 'academic_class__term', 'stream')
        .order_by('academic_class__Class__name', 'stream__stream')
    )
    timetable_entries = Timetable.objects.select_related(
        'class_stream', 'time_slot', 'subject', 'teacher', 'classroom'
    )
    timetable_data = defaultdict(lambda: defaultdict(dict))
    for entry in timetable_entries:
        timetable_data[entry.class_stream_id][entry.weekday][entry.time_slot.id] = entry
    context = {
        "time_slots": time_slots,
        "class_streams": class_streams,
        "timetable_data": timetable_data,
        "weekdays": WeekDay.choices,
    }
    return render(request, "timetable/school_timetable.html", context)


@login_required
def class_timetable_overview(request):
    class_streams = (
        AcademicClassStream.objects
        .select_related('academic_class__Class', 'academic_class__academic_year', 'academic_class__term', 'stream')
        .order_by('academic_class__Class__name', 'stream__stream')
    )
    context = {
        "class_streams": class_streams,
    }
    return render(request, "timetable/class_timetable.html", context)


@login_required
def classrooms_overview(request):
    classrooms = Classroom.objects.order_by('name')
    context = {
        "classrooms": classrooms,
    }
    return render(request, "timetable/classrooms.html", context)
