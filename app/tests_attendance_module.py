import json
from datetime import date

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from app.models.accounts import StaffAccount
from app.models.attendance import AttendanceRecord, AttendanceSession, AttendanceStatus
from app.models.classes import AcademicClass, AcademicClassStream, Class, ClassSubjectAllocation, Stream, Term
from app.models.school_settings import AcademicYear, Section
from app.models.staffs import Role, Staff
from app.models.students import ClassRegister, Student
from app.models.subjects import Subject
from app.models.timetables import TimeSlot, Timetable, WeekDay
from app.services.attendance import get_or_create_session
from app.services.teacher_assignments import get_teacher_assignments


class AttendanceModuleFlowTests(TestCase):
    def setUp(self):
        self.role, _ = Role.objects.get_or_create(name="Teacher")

        self.teacher = Staff.objects.create(
            first_name="Test",
            last_name="Teacher",
            birth_date=date(1990, 1, 1),
            gender="M",
            address="Kampala",
            marital_status="U",
            contacts="0700000000",
            email="teacher@example.com",
            qualification="B.Ed",
            nin_no="CFX1234567890A",
            hire_date=date(2021, 1, 1),
            department="Academic",
            salary="1200000.00",
            is_academic_staff=True,
            is_administrator_staff=False,
            is_support_staff=False,
            staff_status="Active",
            staff_photo=SimpleUploadedFile("teacher.jpg", b"img", content_type="image/jpeg"),
        )

        self.user = User.objects.create_user(username="teacheruser", password="pass12345")
        StaffAccount.objects.create(staff=self.teacher, user=self.user, role=self.role)

        self.year = AcademicYear.objects.create(academic_year="2026", is_current=True)
        self.term = Term.objects.create(
            academic_year=self.year,
            term="1",
            start_date=date(2026, 1, 10),
            end_date=date(2026, 4, 10),
            is_current=True,
        )
        self.section = Section.objects.create(section_name="O-Level")
        self.base_class = Class.objects.create(name="Senior 2", code="S2", section=self.section)
        self.stream = Stream.objects.create(stream="A")
        self.academic_class = AcademicClass.objects.create(
            section=self.section,
            Class=self.base_class,
            academic_year=self.year,
            term=self.term,
            fees_amount=100000,
        )
        self.teacher = Staff.objects.create(
            first_name="Attendance",
            last_name="Teacher",
            birth_date=date(1990, 1, 1),
            gender="M",
            address="Address",
            marital_status="U",
            contacts="0700000000",
            email="attendance.teacher@example.com",
            qualification="Degree",
            nin_no="CFX1234567890A",
            hire_date=date(2020, 1, 1),
            department="Academic",
            salary="1000000.00",
            is_academic_staff=True,
            is_administrator_staff=False,
            is_support_staff=False,
            staff_status="Active",
            staff_photo=SimpleUploadedFile("staff.jpg", b"fake-image-bytes", content_type="image/jpeg"),
        )
        self.class_stream = AcademicClassStream.objects.create(
            academic_class=self.academic_class,
            stream=self.stream,
            class_teacher=self.teacher,
        )

        self.subject = Subject.objects.create(
            code="MATH",
            name="Mathematics",
            description="Math",
            credit_hours=4,
            section=self.section,
            type="Core",
        )
        ClassSubjectAllocation.objects.create(
            academic_class_stream=self.class_stream,
            subject=self.subject,
            subject_teacher=self.teacher,
        )

        self.slot = TimeSlot.objects.create(start_time="08:00", end_time="09:00")
        self.lesson = Timetable.objects.create(
            class_stream=self.class_stream,
            weekday=WeekDay.MONDAY,
            time_slot=self.slot,
            subject=self.subject,
            teacher=self.teacher,
        )

        student = Student.objects.create(
            reg_no="",
            student_name="Student One",
            gender="M",
            birthdate=date(2011, 1, 1),
            nationality="Ugandan",
            religion="Muslim",
            address="Kampala",
            guardian="Parent",
            relationship="Father",
            contact="0700000010",
            academic_year=self.year,
            current_class=self.base_class,
            stream=self.stream,
            term=self.term,
            is_active=True,
        )
        ClassRegister.objects.create(academic_class_stream=self.class_stream, student=student)

    def test_session_uniqueness_uses_class_subject_date_slot(self):
        other_teacher = Staff.objects.create(
            first_name="Another",
            last_name="Teacher",
            birth_date=date(1988, 1, 1),
            gender="F",
            address="Kampala",
            marital_status="M",
            contacts="0700000100",
            email="another@example.com",
            qualification="B.Ed",
            nin_no="CFX1234567891B",
            hire_date=date(2020, 1, 1),
            department="Academic",
            salary="1000000.00",
            is_academic_staff=True,
            is_administrator_staff=False,
            is_support_staff=False,
            staff_status="Active",
            staff_photo=SimpleUploadedFile("teacher2.jpg", b"img", content_type="image/jpeg"),
        )

        session_one = get_or_create_session(
            class_stream=self.class_stream,
            subject=self.subject,
            teacher=self.teacher,
            date=date(2026, 3, 2),
            time_slot=self.slot,
            academic_year=self.year,
            term=self.term,
        )
        session_two = get_or_create_session(
            class_stream=self.class_stream,
            subject=self.subject,
            teacher=other_teacher,
            date=date(2026, 3, 2),
            time_slot=self.slot,
            academic_year=self.year,
            term=self.term,
        )

        self.assertEqual(session_one.pk, session_two.pk)
        self.assertEqual(AttendanceSession.objects.count(), 1)
        self.assertEqual(session_two.teacher, other_teacher)

    def test_session_can_exist_without_timetable_lesson_link(self):
        session = get_or_create_session(
            class_stream=self.class_stream,
            subject=self.subject,
            teacher=self.teacher,
            date=date(2026, 3, 3),  # Tuesday: no lesson configured in setup
            time_slot=self.slot,
            academic_year=self.year,
            term=self.term,
            lesson=None,
        )
        self.assertIsNone(session.lesson)

    def test_teacher_assignments_prefer_timetable_then_allocation_fallback(self):
        chemistry = Subject.objects.create(
            code="CHEM",
            name="Chemistry",
            description="Chemistry",
            credit_hours=4,
            section=self.section,
            type="Core",
        )
        ClassSubjectAllocation.objects.create(
            academic_class_stream=self.class_stream,
            subject=chemistry,
            subject_teacher=self.teacher,
        )

        assignments = get_teacher_assignments(
            self.teacher,
            current_year=self.year,
            current_term=self.term,
        )
        by_subject = {row.subject.code: row for row in assignments}

        self.assertIn("MATH", by_subject)
        self.assertIn("CHEM", by_subject)
        self.assertEqual(by_subject["MATH"].source, "timetable")
        self.assertEqual(by_subject["CHEM"].source, "allocation")

    def test_timetable_enforces_allocation_consistency(self):
        auto_linked = Timetable.objects.create(
            class_stream=self.class_stream,
            weekday=WeekDay.TUESDAY,
            time_slot=self.slot,
            subject=self.subject,
        )
        self.assertEqual(auto_linked.teacher_id, self.teacher.id)
        self.assertIsNotNone(auto_linked.allocation_id)

        other_teacher = Staff.objects.create(
            first_name="Wrong",
            last_name="Teacher",
            birth_date=date(1989, 1, 1),
            gender="F",
            address="Kampala",
            marital_status="M",
            contacts="0700000101",
            email="wrong@example.com",
            qualification="B.Ed",
            nin_no="CFX1234567892C",
            hire_date=date(2020, 1, 1),
            department="Academic",
            salary="1000000.00",
            is_academic_staff=True,
            is_administrator_staff=False,
            is_support_staff=False,
            staff_status="Active",
            staff_photo=SimpleUploadedFile("teacher3.jpg", b"img", content_type="image/jpeg"),
        )

        with self.assertRaises(ValidationError):
            Timetable.objects.create(
                class_stream=self.class_stream,
                weekday=WeekDay.WEDNESDAY,
                time_slot=self.slot,
                subject=self.subject,
                teacher=other_teacher,
            )

    def test_timetable_center_blocks_teacher_mismatch(self):
        self.client.login(username="teacheruser", password="pass12345")
        other_teacher = Staff.objects.create(
            first_name="Mismatch",
            last_name="Teacher",
            birth_date=date(1987, 1, 1),
            gender="F",
            address="Kampala",
            marital_status="M",
            contacts="0700000102",
            email="mismatch@example.com",
            qualification="B.Ed",
            nin_no="CFX1234567893D",
            hire_date=date(2019, 1, 1),
            department="Academic",
            salary="1100000.00",
            is_academic_staff=True,
            is_administrator_staff=False,
            is_support_staff=False,
            staff_status="Active",
            staff_photo=SimpleUploadedFile("teacher4.jpg", b"img", content_type="image/jpeg"),
        )

        payload = {
            "Monday": {
                str(self.slot.id): {
                    "subject": self.subject.id,
                    "teacher": other_teacher.id,
                    "classroom": "",
                }
            }
        }
        response = self.client.post(
            reverse("timetable_center"),
            data={
                "class_stream_id": self.class_stream.id,
                "timetable_json": json.dumps(payload),
            },
            HTTP_HOST="localhost",
        )
        self.assertEqual(response.status_code, 302)

        self.lesson.refresh_from_db()
        self.assertEqual(self.lesson.teacher_id, self.teacher.id)
        self.assertIsNotNone(self.lesson.allocation_id)

    def test_take_attendance_submits_and_locks_session(self):
        self.client.login(username="teacheruser", password="pass12345")

        target_date = date(2026, 3, 2)  # Monday
        url = (
            f"{reverse('take_attendance')}?class_stream={self.class_stream.id}"
            f"&subject={self.subject.id}&date={target_date.isoformat()}&time_slot={self.slot.id}"
        )

        get_response = self.client.get(url, HTTP_HOST="localhost")
        self.assertEqual(get_response.status_code, 200)

        student_id = ClassRegister.objects.get(academic_class_stream=self.class_stream).student_id
        payload = {str(student_id): {"status": "late", "remarks": "Transport delay"}}

        post_response = self.client.post(
            reverse("take_attendance"),
            data={
                "class_stream": self.class_stream.id,
                "subject": self.subject.id,
                "date": target_date.isoformat(),
                "time_slot": self.slot.id,
                "attendance_payload": json.dumps(payload),
            },
            HTTP_HOST="localhost",
        )
        self.assertEqual(post_response.status_code, 302)

        session = AttendanceSession.objects.get(
            class_stream=self.class_stream,
            subject=self.subject,
            date=target_date,
            time_slot=self.slot,
        )
        self.assertTrue(session.is_locked)
        self.assertEqual(session.lesson_id, self.lesson.id)
        record = AttendanceRecord.objects.get(session=session, student_id=student_id)
        self.assertEqual(record.status, AttendanceStatus.LATE)

    def test_unlock_attendance_requires_admin(self):
        session = AttendanceSession.objects.create(
            class_stream=self.class_stream,
            subject=self.subject,
            teacher=self.teacher,
            academic_year=self.year,
            term=self.term,
            date=date(2026, 3, 2),
            time_slot=self.slot,
            is_locked=True,
        )

        self.client.login(username="teacheruser", password="pass12345")
        non_admin_response = self.client.post(
            reverse("unlock_attendance", kwargs={"session_id": session.id}),
            data={"reason": "Unauthorized reopen attempt"},
            HTTP_HOST="localhost",
        )
        self.assertEqual(non_admin_response.status_code, 302)
        session.refresh_from_db()
        self.assertTrue(session.is_locked)

        admin = User.objects.create_superuser("rootadmin", "root@example.com", "pass12345")
        self.client.force_login(admin)
        admin_response = self.client.post(
            reverse("unlock_attendance", kwargs={"session_id": session.id}),
            data={"reason": "Admin override"},
            HTTP_HOST="localhost",
        )
        self.assertEqual(admin_response.status_code, 302)
        session.refresh_from_db()
        self.assertFalse(session.is_locked)
