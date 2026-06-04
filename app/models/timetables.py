from django.apps import apps
from django.core.exceptions import ValidationError
from django.db import models

class Classroom(models.Model):
    name = models.CharField(max_length=50)
    location = models.CharField(max_length=100, verbose_name="Block", blank=True, null=True)
    capacity = models.PositiveIntegerField(default=0)

    def __str__(self):
        return self.name
    

class WeekDay(models.TextChoices):
    MONDAY = 'MON', 'Monday'
    TUESDAY = 'TUE', 'Tuesday'
    WEDNESDAY = 'WED', 'Wednesday'
    THURSDAY = 'THU', 'Thursday'
    FRIDAY = 'FRI', 'Friday'
    SATURDAY = 'SAT', 'Saturday'
    SUNDAY = 'SUN', 'Sunday'


class TimeSlot(models.Model):
    start_time = models.TimeField()
    end_time = models.TimeField()

    class Meta:
        ordering = ['start_time', 'end_time', 'id']
        unique_together = ('start_time', 'end_time')

    def __str__(self):
        return f'{self.start_time.strftime("%H:%M")} - {self.end_time.strftime("%H:%M")}'

    def clean(self):
        if self.start_time >= self.end_time:
            raise ValidationError("Start time must be before end time.")

        overlap = (
            TimeSlot.objects
            .exclude(pk=self.pk)
            .filter(start_time__lt=self.end_time, end_time__gt=self.start_time)
            .exists()
        )
        if overlap:
            raise ValidationError("This time slot overlaps with an existing time slot. Please adjust the time range.")

class BreakPeriod(models.Model):
    
    weekday = models.CharField(max_length=3, choices=WeekDay.choices)
    name = models.CharField(max_length=20, default="Break")
    time_slot = models.ForeignKey(TimeSlot, on_delete=models.CASCADE)

    class Meta:
        unique_together = ('weekday', 'time_slot')

    def __str__(self):
        return f'{self.name} on {self.weekday} at {self.time_slot}'


class Timetable(models.Model):
    class_stream = models.ForeignKey("app.AcademicClassStream", on_delete=models.CASCADE, related_name='timetables')
    weekday = models.CharField(max_length=3, choices=WeekDay.choices)
    time_slot = models.ForeignKey(TimeSlot, on_delete=models.CASCADE)
    subject = models.ForeignKey('app.Subject', on_delete=models.CASCADE)
    teacher = models.ForeignKey('app.Staff', on_delete=models.SET_NULL, null=True, blank=True, related_name='teaching_slots')
    classroom = models.ForeignKey(Classroom, on_delete=models.SET_NULL, null=True, blank=True, related_name="allocations")
    allocation = models.ForeignKey(
        "app.ClassSubjectAllocation",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="timetable_entries",
    )

    class Meta:
        # Update this to refer to the correct fields
        unique_together = ('class_stream', 'weekday', 'time_slot')

    def __str__(self):
        return f'{self.subject} on {self.weekday} at {self.time_slot}'

    def _resolve_allocation(self):
        if not self.class_stream_id or not self.subject_id:
            return None

        ClassSubjectAllocation = apps.get_model("app", "ClassSubjectAllocation")
        allocation_qs = ClassSubjectAllocation.objects.filter(
            academic_class_stream_id=self.class_stream_id,
            subject_id=self.subject_id,
        )
        if self.teacher_id:
            allocation = allocation_qs.filter(subject_teacher_id=self.teacher_id).first()
            if allocation:
                return allocation
        return allocation_qs.first()

    def clean(self):
        allocation = self.allocation
        if allocation:
            if (
                self.class_stream_id
                and allocation.academic_class_stream_id != self.class_stream_id
            ):
                raise ValidationError(
                    {"allocation": "Selected allocation does not match this class stream."}
                )
            if self.subject_id and allocation.subject_id != self.subject_id:
                raise ValidationError(
                    {"subject": "Subject must match the selected class subject allocation."}
                )
            if self.teacher_id and allocation.subject_teacher_id != self.teacher_id:
                raise ValidationError(
                    {"teacher": "Teacher must match the selected class subject allocation."}
                )
        else:
            allocation = self._resolve_allocation()
            if not allocation and self.class_stream_id and self.subject_id:
                raise ValidationError(
                    {
                        "subject": (
                            "No class subject allocation exists for this class stream and subject."
                        )
                    }
                )
            if allocation:
                self.allocation = allocation
                if self.teacher_id and allocation.subject_teacher_id != self.teacher_id:
                    raise ValidationError(
                        {"teacher": "Teacher must match the class subject allocation."}
                    )

        if allocation:
            self.subject_id = allocation.subject_id
            self.teacher_id = allocation.subject_teacher_id

        # Conflict: Same teacher at same time (skip when teacher is unset)
        if self.teacher:
            teacher_conflict = Timetable.objects.filter(
                teacher=self.teacher,
                weekday=self.weekday,
                time_slot=self.time_slot
            ).exclude(pk=self.pk).exists()

            if teacher_conflict:
                raise ValidationError("This teacher is already assigned at this time.")

        # Conflict: Same classroom at same time
        if self.classroom:
            room_conflict = Timetable.objects.filter(
                classroom=self.classroom,
                weekday=self.weekday,
                time_slot=self.time_slot
            ).exclude(pk=self.pk).exists()

            if room_conflict:
                raise ValidationError("This classroom is already in use at this time.")

        # Conflict: Same class already scheduled
        class_conflict = Timetable.objects.filter(
            class_stream=self.class_stream,
            weekday=self.weekday,
            time_slot=self.time_slot
        ).exclude(pk=self.pk).exists()

        if class_conflict:
            raise ValidationError("This class already has a subject at this time.")

    def save(self, *args, **kwargs):
        self.full_clean()  
        super().save(*args, **kwargs)



    
