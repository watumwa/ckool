from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO
from zipfile import ZipFile

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.sessions.middleware import SessionMiddleware
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from app.models.classes import (
    AcademicClass,
    AcademicClassStream,
    Class,
    Stream,
    StudentPromotionHistory,
    Term,
)
from app.models.fees_payment import BillItem, ClassBill, Payment, StudentBill, StudentBillItem
from app.models.results import (
    Assessment,
    AssessmentType,
    GradingSystem,
    Result,
    ResultVerificationSetting,
    VerificationCorrectionLog,
    VerificationDiscrepancy,
    VerificationSample,
)
from app.models.school_settings import AcademicYear, SchoolSetting, Section
from app.models.staffs import Staff
from app.models.students import ClassRegister, Student
from app.models.subjects import Subject
from app.services.level_scope import get_level_classes_queryset, get_level_sections_queryset
from app.services.fees_carry_forward import (
    CARRY_FORWARD_ITEM_NAME,
    build_carry_forward_preview,
    post_carry_forward,
)
from app.services.results_sampling import submit_batch_for_verification
from app.services.school_level import get_active_school_level
from core.tenant import register_database_alias, unregister_database_alias


class QuickSetupStudentFlowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="admin", password="pass12345")
        self.client.force_login(self.user)

        self.year = AcademicYear.objects.create(academic_year="2026", is_current=True)
        self.term = Term.objects.create(
            academic_year=self.year,
            term="1",
            start_date=date(2026, 1, 10),
            end_date=date(2026, 4, 10),
            is_current=True,
        )
        self.section = Section.objects.create(section_name="Secondary")
        self.class_obj = Class.objects.create(name="Senior 1", code="S1", section=self.section)
        self.stream = Stream.objects.create(stream="A")

    def _make_staff(self, first_name, last_name, is_academic_staff):
        return Staff.objects.create(
            first_name=first_name,
            last_name=last_name,
            birth_date=date(1990, 1, 1),
            gender="M",
            address="Address",
            marital_status="U",
            contacts="0700000000",
            email=f"{first_name.lower()}@example.com",
            qualification="Degree",
            nin_no="CFX1234567890A",
            hire_date=date(2020, 1, 1),
            department="Academic",
            salary="1000000.00",
            is_academic_staff=is_academic_staff,
            is_administrator_staff=not is_academic_staff,
            is_support_staff=False,
            staff_status="Active",
            staff_photo=SimpleUploadedFile("staff.jpg", b"fake-image-bytes", content_type="image/jpeg"),
        )

    def test_quick_create_academic_class_creates_record(self):
        response = self.client.post(
            reverse("quick_create_academic_class"),
            {
                "quick_class_id": self.class_obj.id,
                "quick_section_id": self.section.id,
                "quick_fees_amount": "150000",
            },
            follow=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            AcademicClass.objects.filter(
                Class=self.class_obj,
                section=self.section,
                academic_year=self.year,
                term=self.term,
            ).exists()
        )

    def test_quick_create_class_stream_requires_existing_academic_class(self):
        teacher = self._make_staff("John", "Teacher", True)

        response = self.client.post(
            reverse("quick_create_class_stream"),
            {
                "quick_stream_class_id": self.class_obj.id,
                "quick_stream_id": self.stream.id,
                "quick_teacher_id": teacher.id,
            },
            follow=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(AcademicClassStream.objects.exists())

    def test_quick_create_class_stream_rejects_non_academic_staff(self):
        academic_class = AcademicClass.objects.create(
            Class=self.class_obj,
            section=self.section,
            academic_year=self.year,
            term=self.term,
            fees_amount=120000,
        )
        admin_staff = self._make_staff("Jane", "Admin", False)

        response = self.client.post(
            reverse("quick_create_class_stream"),
            {
                "quick_stream_class_id": self.class_obj.id,
                "quick_stream_id": self.stream.id,
                "quick_teacher_id": admin_staff.id,
            },
            follow=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            AcademicClassStream.objects.filter(
                academic_class=academic_class,
                stream=self.stream,
            ).exists()
        )

    def test_quick_create_class_stream_creates_for_academic_staff(self):
        academic_class = AcademicClass.objects.create(
            Class=self.class_obj,
            section=self.section,
            academic_year=self.year,
            term=self.term,
            fees_amount=120000,
        )
        teacher = self._make_staff("Amina", "Tutor", True)

        response = self.client.post(
            reverse("quick_create_class_stream"),
            {
                "quick_stream_class_id": self.class_obj.id,
                "quick_stream_id": self.stream.id,
                "quick_teacher_id": teacher.id,
            },
            follow=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            AcademicClassStream.objects.filter(
                academic_class=academic_class,
                stream=self.stream,
                class_teacher=teacher,
            ).exists()
        )


class FeesCarryForwardTests(TestCase):
    def setUp(self):
        self.year = AcademicYear.objects.create(academic_year="2026", is_current=True)
        self.term_one = Term.objects.create(
            academic_year=self.year,
            term="1",
            start_date=date(2026, 1, 10),
            end_date=date(2026, 4, 10),
            is_current=False,
        )
        self.term_two = Term.objects.create(
            academic_year=self.year,
            term="2",
            start_date=date(2026, 5, 1),
            end_date=date(2026, 8, 15),
            is_current=True,
        )
        self.section = Section.objects.create(section_name="Primary")
        self.class_obj = Class.objects.create(name="Primary 1", code="P1", section=self.section)
        self.stream = Stream.objects.create(stream="A")
        self.source_academic_class = AcademicClass.objects.create(
            Class=self.class_obj,
            section=self.section,
            academic_year=self.year,
            term=self.term_one,
            fees_amount=100000,
        )
        self.target_academic_class = AcademicClass.objects.create(
            Class=self.class_obj,
            section=self.section,
            academic_year=self.year,
            term=self.term_two,
            fees_amount=120000,
        )
        self.student = Student.objects.create(
            reg_no="REG-CF-001",
            student_name="Carry Forward Learner",
            gender="M",
            birthdate=date(2018, 1, 1),
            nationality="Ugandan",
            religion="Muslim",
            address="Kampala",
            guardian="Parent",
            relationship="Father",
            contact="0700000000",
            academic_year=self.year,
            current_class=self.class_obj,
            stream=self.stream,
            term=self.term_two,
        )
        self.school_fees = BillItem.objects.create(
            item_name="School Fees",
            category="Tuition",
            bill_duration="Termly",
            description="Mandatory school fees",
        )
        self.source_bill = StudentBill.objects.create(
            student=self.student,
            academic_class=self.source_academic_class,
            status="Unpaid",
        )
        StudentBillItem.objects.create(
            bill=self.source_bill,
            bill_item=self.school_fees,
            description="Term 1 fees",
            amount=Decimal("100000"),
            fee_category="Tuition",
        )
        Payment.objects.create(
            bill=self.source_bill,
            payment_date=date(2026, 3, 1),
            amount=Decimal("40000"),
            payment_method="Cash",
            reference_no="CF-PAY-001",
            recorded_by="bursar",
        )

    def test_preview_finds_previous_term_outstanding_balance(self):
        rows = build_carry_forward_preview(
            source_term=self.term_one,
            target_term=self.term_two,
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].outstanding, Decimal("60000"))
        self.assertEqual(rows[0].target_academic_class, self.target_academic_class)

    def test_post_moves_balance_to_target_term_without_duplication(self):
        first_result = post_carry_forward(
            source_term=self.term_one,
            target_term=self.term_two,
        )
        second_result = post_carry_forward(
            source_term=self.term_one,
            target_term=self.term_two,
        )

        self.assertEqual(first_result["posted_count"], 1)
        self.assertEqual(second_result["posted_count"], 1)

        carry_item = BillItem.objects.get(item_name=CARRY_FORWARD_ITEM_NAME)
        target_bill = StudentBill.objects.get(
            student=self.student,
            academic_class=self.target_academic_class,
        )
        target_items = StudentBillItem.objects.filter(bill=target_bill, bill_item=carry_item)
        source_adjustments = StudentBillItem.objects.filter(bill=self.source_bill, bill_item=carry_item)

        self.assertEqual(target_items.count(), 1)
        self.assertEqual(source_adjustments.count(), 1)
        self.assertEqual(target_items.first().amount, Decimal("60000"))
        self.assertEqual(source_adjustments.first().amount, Decimal("-60000"))

        self.source_bill.refresh_from_db()
        target_bill.refresh_from_db()
        self.assertEqual(self.source_bill.balance, Decimal("0.00"))
        self.assertEqual(target_bill.balance, Decimal("60000.00"))

class SecondaryLevelScopeTests(TestCase):
    def setUp(self):
        self.primary_section = Section.objects.create(section_name="Primary")
        self.olevel_section = Section.objects.create(section_name="O-Level")
        self.alevel_section = Section.objects.create(section_name="A-Level")

        Class.objects.create(name="Primary 1", code="P1", section=self.primary_section)
        Class.objects.create(name="Senior 1", code="S1", section=self.olevel_section)
        Class.objects.create(name="Senior 5", code="S5", section=self.alevel_section)

    def test_secondary_mode_includes_both_secondary_sections(self):
        sections = get_level_sections_queryset(active_level=SchoolSetting.EducationLevel.SECONDARY_LOWER)
        self.assertSetEqual(
            set(sections.values_list("section_name", flat=True)),
            {"O-Level", "A-Level"},
        )

    def test_secondary_mode_includes_o_level_and_a_level_classes(self):
        classes = get_level_classes_queryset(active_level=SchoolSetting.EducationLevel.SECONDARY_UPPER)
        self.assertSetEqual(set(classes.values_list("code", flat=True)), {"S1", "S5"})

    def test_primary_mode_excludes_secondary_sections(self):
        sections = get_level_sections_queryset(active_level=SchoolSetting.EducationLevel.PRIMARY)
        self.assertSetEqual(set(sections.values_list("section_name", flat=True)), {"Primary"})


class SchoolLevelActivationTests(TestCase):
    def setUp(self):
        self.school_setting = SchoolSetting.load()
        self.factory = RequestFactory()

    def _build_request(self):
        request = self.factory.get("/")
        SessionMiddleware(lambda req: None).process_request(request)
        request.session.save()
        return request

    def test_secondary_default_is_ignored_when_secondary_is_disabled(self):
        self.school_setting.offers_primary = True
        self.school_setting.offers_secondary_lower = False
        self.school_setting.offers_secondary_upper = False
        self.school_setting.education_level = SchoolSetting.EducationLevel.SECONDARY_LOWER
        self.school_setting.save()

        request = self._build_request()
        active_level = get_active_school_level(request=request, school_setting=self.school_setting)

        self.assertEqual(self.school_setting.get_enabled_levels(), [SchoolSetting.EducationLevel.PRIMARY])
        self.assertEqual(active_level, SchoolSetting.EducationLevel.PRIMARY)
        self.assertEqual(request.session.get("active_school_level"), SchoolSetting.EducationLevel.PRIMARY)

    def test_secondary_school_falls_back_to_o_level_when_primary_is_disabled(self):
        self.school_setting.offers_primary = False
        self.school_setting.offers_secondary_lower = True
        self.school_setting.offers_secondary_upper = True
        self.school_setting.education_level = SchoolSetting.EducationLevel.PRIMARY
        self.school_setting.save()

        request = self._build_request()
        active_level = get_active_school_level(request=request, school_setting=self.school_setting)

        self.assertEqual(
            self.school_setting.get_enabled_levels(),
            [
                SchoolSetting.EducationLevel.SECONDARY_LOWER,
                SchoolSetting.EducationLevel.SECONDARY_UPPER,
            ],
        )
        self.assertEqual(active_level, SchoolSetting.EducationLevel.SECONDARY_LOWER)
        self.assertEqual(request.session.get("active_school_level"), SchoolSetting.EducationLevel.SECONDARY_LOWER)


class ResultVerificationWorkflowTests(TestCase):
    def setUp(self):
        self.submitter = User.objects.create_user(username="submitter", password="pass12345")
        self.verifier = User.objects.create_user(username="verifier", password="pass12345")

        self.year = AcademicYear.objects.create(academic_year="2027", is_current=True)
        self.term = Term.objects.create(
            academic_year=self.year,
            term="1",
            start_date=date(2027, 1, 10),
            end_date=date(2027, 4, 10),
            is_current=True,
        )
        self.section = Section.objects.create(section_name="Verification Secondary")
        self.class_obj = Class.objects.create(name="Senior 2", code="S2", section=self.section)
        self.stream = Stream.objects.create(stream="B")
        self.academic_class = AcademicClass.objects.create(
            section=self.section,
            Class=self.class_obj,
            academic_year=self.year,
            term=self.term,
            fees_amount=100000,
        )

        self.class_teacher = self._make_staff("Class", "Teacher")
        self.class_stream = AcademicClassStream.objects.create(
            academic_class=self.academic_class,
            stream=self.stream,
            class_teacher=self.class_teacher,
        )

        self.subject = Subject.objects.create(
            code="MTH",
            name="Mathematics",
            description="Math",
            credit_hours=4,
            section=self.section,
            type="Core",
        )
        self.assessment_type = AssessmentType.objects.create(name="CAT", weight=Decimal("100.00"))
        self.assessment = Assessment.objects.create(
            academic_class=self.academic_class,
            assessment_type=self.assessment_type,
            subject=self.subject,
            date=date(2027, 2, 10),
            out_of=100,
        )

        self.student_one = self._make_student("Student One", "REG-001")
        self.student_two = self._make_student("Student Two", "REG-002")
        ClassRegister.objects.create(academic_class_stream=self.class_stream, student=self.student_one)
        ClassRegister.objects.create(academic_class_stream=self.class_stream, student=self.student_two)

        self.result_one = Result.objects.create(
            assessment=self.assessment,
            student=self.student_one,
            score=Decimal("55.00"),
            status="DRAFT",
        )
        self.result_two = Result.objects.create(
            assessment=self.assessment,
            student=self.student_two,
            score=Decimal("70.00"),
            status="DRAFT",
        )

        ResultVerificationSetting.objects.create(
            sample_percent=Decimal("100.00"),
            tolerance_marks=Decimal("1.00"),
        )

    def _make_staff(self, first_name, last_name):
        return Staff.objects.create(
            first_name=first_name,
            last_name=last_name,
            birth_date=date(1990, 1, 1),
            gender="M",
            address="Address",
            marital_status="U",
            contacts="0700000000",
            email=f"{first_name.lower()}.{last_name.lower()}@example.com",
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

    def _make_student(self, name, reg_no):
        return Student.objects.create(
            reg_no=reg_no,
            student_name=name,
            gender="M",
            birthdate=date(2012, 1, 1),
            nationality="Ugandan",
            religion="Muslim",
            address="Address",
            guardian="Guardian",
            relationship="Parent",
            contact="0700000000",
            academic_year=self.year,
            current_class=self.class_obj,
            stream=self.stream,
            term=self.term,
        )

    def _set_active_role(self, role_name):
        session = self.client.session
        session["active_role_name"] = role_name
        session.save()

    def _submit_pending_batch(self, user):
        batch, sample_count, ok = submit_batch_for_verification(self.assessment, user)
        self.assertTrue(ok)
        self.assertEqual(batch.status, "PENDING")
        self.assertEqual(sample_count, 2)
        return batch

    def _queue_url(self):
        return reverse("verification_queue", args=[self.assessment.id])

    def _sample_map(self, batch):
        return {
            sample.result_id: sample
            for sample in VerificationSample.objects.filter(result__batch=batch).select_related("result")
        }

    def test_cannot_finalize_with_partial_sampled_checks(self):
        batch = self._submit_pending_batch(self.submitter)
        samples = self._sample_map(batch)
        self.client.force_login(self.verifier)
        self._set_active_role("Director of Studies")

        response = self.client.post(
            self._queue_url(),
            {
                "finalize_verification": "1",
                f"dos_mark_{self.result_one.id}": "55",
            },
            follow=False,
        )

        self.assertEqual(response.status_code, 302)
        batch.refresh_from_db()
        self.assertEqual(batch.status, "PENDING")
        self.assertEqual(
            VerificationSample.objects.filter(result__batch=batch, checked_at__isnull=True).count(),
            1,
        )
        self.assertEqual(samples[self.result_two.id].matched, None)

    def test_cannot_verify_with_out_of_range_verifier_marks(self):
        batch = self._submit_pending_batch(self.submitter)
        self.client.force_login(self.verifier)
        self._set_active_role("Director of Studies")

        response = self.client.post(
            self._queue_url(),
            {
                "finalize_verification": "1",
                f"dos_mark_{self.result_one.id}": "101",
                f"dos_mark_{self.result_two.id}": "80",
            },
            follow=False,
        )

        self.assertEqual(response.status_code, 302)
        batch.refresh_from_db()
        self.assertEqual(batch.status, "PENDING")
        self.assertEqual(
            VerificationSample.objects.filter(result__batch=batch, checked_at__isnull=True).count(),
            2,
        )

    def test_submitter_cannot_verify_own_batch(self):
        batch = self._submit_pending_batch(self.submitter)
        self.client.force_login(self.submitter)
        self._set_active_role("Admin")

        response = self.client.post(
            self._queue_url(),
            {
                "finalize_verification": "1",
                f"dos_mark_{self.result_one.id}": "55",
                f"dos_mark_{self.result_two.id}": "70",
            },
            follow=False,
        )

        self.assertEqual(response.status_code, 302)
        batch.refresh_from_db()
        self.assertEqual(batch.status, "PENDING")
        self.assertEqual(
            VerificationSample.objects.filter(result__batch=batch, checked_at__isnull=True).count(),
            2,
        )

    def test_mismatch_requires_reason(self):
        batch = self._submit_pending_batch(self.submitter)
        self.client.force_login(self.verifier)
        self._set_active_role("Director of Studies")

        response = self.client.post(
            self._queue_url(),
            {
                "finalize_verification": "1",
                f"dos_mark_{self.result_one.id}": "60",
                f"dos_mark_{self.result_two.id}": "70",
            },
            follow=False,
        )

        self.assertEqual(response.status_code, 302)
        batch.refresh_from_db()
        self.assertEqual(batch.status, "PENDING")
        self.assertEqual(
            VerificationSample.objects.filter(result__batch=batch, checked_at__isnull=True).count(),
            0,
        )

    def test_correction_creates_log_and_updates_discrepancy(self):
        batch = self._submit_pending_batch(self.submitter)

        self.client.force_login(self.verifier)
        self._set_active_role("Director of Studies")
        verify_response = self.client.post(
            self._queue_url(),
            {
                "finalize_verification": "1",
                f"dos_mark_{self.result_one.id}": "60",
                f"dos_mark_{self.result_two.id}": "70",
                "rejection_reason": "Mismatch on sampled script.",
            },
            follow=False,
        )
        self.assertEqual(verify_response.status_code, 302)

        batch.refresh_from_db()
        self.assertEqual(batch.status, "FLAGGED")
        discrepancy = VerificationDiscrepancy.objects.get(batch=batch, result=self.result_one)
        self.assertEqual(discrepancy.corrected_mark, None)

        self.client.force_login(self.submitter)
        self._set_active_role("Teacher")
        correction_response = self.client.post(
            reverse("add_results", args=[self.assessment.id]),
            {
                "save_draft": "1",
                f"score_{self.student_one.id}": "60",
                f"remark_{self.student_one.id}": "Rechecked and updated from script.",
            },
            follow=False,
        )
        self.assertEqual(correction_response.status_code, 302)

        batch.refresh_from_db()
        self.assertEqual(batch.status, "DRAFT")

        correction_log = VerificationCorrectionLog.objects.filter(batch=batch, result=self.result_one).first()
        self.assertIsNotNone(correction_log)
        self.assertEqual(correction_log.old_mark, Decimal("55.00"))
        self.assertEqual(correction_log.new_mark, Decimal("60.00"))

        discrepancy.refresh_from_db()
        self.assertEqual(discrepancy.corrected_mark, Decimal("60.00"))
        self.assertIn("Corrected by", discrepancy.action_taken)

    def test_duplicate_result_creation_blocked(self):
        with self.assertRaises(IntegrityError):
            Result.objects.create(
                assessment=self.assessment,
                student=self.student_one,
                score=Decimal("80.00"),
                status="DRAFT",
            )


class AcademicClassPromotionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="promotion_admin", password="pass12345")
        self.client.force_login(self.user)

        self.section = Section.objects.create(section_name="Secondary")

        self.year_2026 = AcademicYear.objects.create(academic_year="2026")
        self.year_2027 = AcademicYear.objects.create(academic_year="2027")
        self.term_2026 = Term.objects.create(
            academic_year=self.year_2026,
            term="1",
            start_date=date(2026, 1, 10),
            end_date=date(2026, 4, 10),
            is_current=False,
        )
        self.term_2027 = Term.objects.create(
            academic_year=self.year_2027,
            term="1",
            start_date=date(2027, 1, 10),
            end_date=date(2027, 4, 10),
            is_current=True,
        )

        self.s1 = Class.objects.create(name="Senior 1", code="S1", section=self.section)
        self.s2 = Class.objects.create(name="Senior 2", code="S2", section=self.section)
        self.teacher = self._make_staff("Promotion", "Teacher")
        self.stream_a = Stream.objects.create(stream="A")
        self.stream_b = Stream.objects.create(stream="B")

        self.source_class = AcademicClass.objects.create(
            section=self.section,
            Class=self.s1,
            academic_year=self.year_2026,
            term=self.term_2026,
            fees_amount=100000,
        )
        self.target_class = AcademicClass.objects.create(
            section=self.section,
            Class=self.s2,
            academic_year=self.year_2027,
            term=self.term_2027,
            fees_amount=120000,
        )

        self.source_stream_a = AcademicClassStream.objects.create(
            academic_class=self.source_class,
            stream=self.stream_a,
            class_teacher=self.teacher,
        )
        self.source_stream_b = AcademicClassStream.objects.create(
            academic_class=self.source_class,
            stream=self.stream_b,
            class_teacher=self.teacher,
        )
        self.target_stream_a = AcademicClassStream.objects.create(
            academic_class=self.target_class,
            stream=self.stream_a,
            class_teacher=self.teacher,
        )
        self.target_stream_b = AcademicClassStream.objects.create(
            academic_class=self.target_class,
            stream=self.stream_b,
            class_teacher=self.teacher,
        )

        self.student_active_a = self._make_student(
            name="Active A",
            stream=self.stream_a,
            reg_no="REG-A",
            is_active=True,
        )
        self.student_active_b = self._make_student(
            name="Active B",
            stream=self.stream_b,
            reg_no="REG-B",
            is_active=True,
        )
        self.student_inactive_a = self._make_student(
            name="Inactive A",
            stream=self.stream_a,
            reg_no="REG-C",
            is_active=False,
        )

        ClassRegister.objects.create(
            academic_class_stream=self.source_stream_a,
            student=self.student_active_a,
        )
        ClassRegister.objects.create(
            academic_class_stream=self.source_stream_b,
            student=self.student_active_b,
        )
        ClassRegister.objects.create(
            academic_class_stream=self.source_stream_a,
            student=self.student_inactive_a,
        )

    def _make_staff(self, first_name, last_name):
        return Staff.objects.create(
            first_name=first_name,
            last_name=last_name,
            birth_date=date(1990, 1, 1),
            gender="M",
            address="Address",
            marital_status="U",
            contacts="0700000000",
            email=f"{first_name.lower()}.{last_name.lower()}@example.com",
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

    def _make_student(self, *, name, stream, reg_no, is_active):
        return Student.objects.create(
            reg_no=reg_no,
            student_name=name,
            gender="M",
            birthdate=date(2012, 1, 1),
            nationality="Ugandan",
            religion="Muslim",
            address="Address",
            guardian="Guardian",
            relationship="Parent",
            contact="0700000000",
            academic_year=self.year_2026,
            current_class=self.s1,
            stream=stream,
            term=self.term_2026,
            is_active=is_active,
        )

    def _set_active_role(self, role_name):
        session = self.client.session
        session["active_role_name"] = role_name
        session.save()

    def _promotion_url(self):
        return reverse("promote_academic_class_students", args=[self.source_class.id])

    def _post_promotion(self, data):
        return self.client.post(
            self._promotion_url(),
            data,
            follow=False,
            HTTP_HOST="localhost",
        )

    def test_promotion_workflow_page_renders_for_admin_role(self):
        self._set_active_role("Admin")
        response = self.client.get(
            reverse("student_promotion_workflow"),
            {
                "source_academic_class_id": self.source_class.id,
                "tab": "conditional",
            },
            HTTP_HOST="localhost",
            follow=False,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Student Promotion")
        self.assertContains(response, self.student_active_a.student_name)

    def test_promotion_workflow_page_renders_for_director_of_studies_role(self):
        self._set_active_role("Director of Studies")
        response = self.client.get(
            reverse("student_promotion_workflow"),
            {
                "source_academic_class_id": self.source_class.id,
                "tab": "eligible",
            },
            HTTP_HOST="localhost",
            follow=False,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Student Promotion")
        self.assertContains(response, self.student_active_b.student_name)

    def test_head_teacher_role_cannot_access_promotion_workflow(self):
        self._set_active_role("Head Teacher")
        response = self.client.get(
            reverse("student_promotion_workflow"),
            {
                "source_academic_class_id": self.source_class.id,
                "tab": "eligible",
            },
            HTTP_HOST="localhost",
            follow=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("academic_class_page"))

    def test_promote_students_creates_target_registers_and_updates_snapshots(self):
        self._set_active_role("Admin")
        response = self._post_promotion(
            {
                "target_academic_class": self.target_class.id,
                "active_students_only": "on",
            },
        )
        self.assertEqual(response.status_code, 302)

        self.assertTrue(
            ClassRegister.objects.filter(
                academic_class_stream=self.target_stream_a,
                student=self.student_active_a,
            ).exists()
        )
        self.assertTrue(
            ClassRegister.objects.filter(
                academic_class_stream=self.target_stream_b,
                student=self.student_active_b,
            ).exists()
        )
        self.assertFalse(
            ClassRegister.objects.filter(
                academic_class_stream=self.target_stream_a,
                student=self.student_inactive_a,
            ).exists()
        )

        self.student_active_a.refresh_from_db()
        self.student_active_b.refresh_from_db()
        self.assertEqual(self.student_active_a.current_class_id, self.s2.id)
        self.assertEqual(self.student_active_b.current_class_id, self.s2.id)
        self.assertEqual(self.student_active_a.academic_year_id, self.year_2027.id)
        self.assertEqual(self.student_active_b.academic_year_id, self.year_2027.id)
        self.assertEqual(self.student_active_a.term_id, self.term_2027.id)
        self.assertEqual(self.student_active_b.term_id, self.term_2027.id)

        self.student_inactive_a.refresh_from_db()
        self.assertEqual(self.student_inactive_a.current_class_id, self.s1.id)
        self.assertEqual(self.student_inactive_a.academic_year_id, self.year_2026.id)

        history = StudentPromotionHistory.objects.get()
        self.assertEqual(history.promoted_by_id, self.user.id)
        self.assertEqual(history.source_academic_class_id, self.source_class.id)
        self.assertEqual(history.target_academic_class_id, self.target_class.id)
        self.assertTrue(history.active_students_only)
        self.assertEqual(history.total_candidates, 2)
        self.assertEqual(history.promoted_count, 2)
        self.assertEqual(history.already_registered_count, 0)
        self.assertEqual(history.skipped_inactive_count, 1)
        self.assertEqual(history.updated_student_snapshots, 2)
        self.assertEqual(history.missing_stream_names, [])

    def test_submitter_role_without_permission_cannot_promote(self):
        self._set_active_role("Teacher")
        response = self._post_promotion(
            {
                "target_academic_class": self.target_class.id,
                "active_students_only": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            ClassRegister.objects.filter(
                academic_class_stream__academic_class=self.target_class
            ).count(),
            0,
        )
        self.assertEqual(StudentPromotionHistory.objects.count(), 0)

    def test_head_teacher_role_without_permission_cannot_promote(self):
        self._set_active_role("Head Teacher")
        response = self._post_promotion(
            {
                "target_academic_class": self.target_class.id,
                "active_students_only": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            ClassRegister.objects.filter(
                academic_class_stream__academic_class=self.target_class
            ).count(),
            0,
        )
        self.assertEqual(StudentPromotionHistory.objects.count(), 0)

    def test_promotion_stops_when_target_stream_is_missing(self):
        self.target_stream_b.delete()
        self._set_active_role("Admin")
        response = self._post_promotion(
            {
                "target_academic_class": self.target_class.id,
                "active_students_only": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            ClassRegister.objects.filter(
                academic_class_stream__academic_class=self.target_class
            ).count(),
            0,
        )

        self.student_active_a.refresh_from_db()
        self.assertEqual(self.student_active_a.current_class_id, self.s1.id)

        history = StudentPromotionHistory.objects.get()
        self.assertEqual(history.promoted_by_id, self.user.id)
        self.assertEqual(history.promoted_count, 0)
        self.assertEqual(history.total_candidates, 2)
        self.assertEqual(history.skipped_inactive_count, 1)
        self.assertEqual(history.missing_stream_names, ["B"])

    def test_promotion_can_be_scoped_to_one_source_stream(self):
        self._set_active_role("Admin")
        response = self._post_promotion(
            {
                "target_academic_class": self.target_class.id,
                "source_stream": self.source_stream_a.id,
                "active_students_only": "on",
            },
        )
        self.assertEqual(response.status_code, 302)

        self.assertTrue(
            ClassRegister.objects.filter(
                academic_class_stream=self.target_stream_a,
                student=self.student_active_a,
            ).exists()
        )
        self.assertFalse(
            ClassRegister.objects.filter(
                academic_class_stream=self.target_stream_b,
                student=self.student_active_b,
            ).exists()
        )

        history = StudentPromotionHistory.objects.get()
        self.assertEqual(history.source_stream_id, self.source_stream_a.id)
        self.assertEqual(history.total_candidates, 1)
        self.assertEqual(history.promoted_count, 1)


class TermActivationSyncTests(TestCase):
    def setUp(self):
        self.section = Section.objects.create(section_name="Secondary")
        self.year = AcademicYear.objects.create(academic_year="2026", is_current=True)
        self.term_one = Term.objects.create(
            academic_year=self.year,
            term="1",
            start_date=date(2026, 1, 10),
            end_date=date(2026, 4, 10),
            is_current=True,
        )
        self.class_obj = Class.objects.create(name="Senior 1", code="S1", section=self.section)
        self.stream_a = Stream.objects.create(stream="A")
        self.unused_stream = Stream.objects.create(stream="B")
        self.teacher = self._make_staff("Term", "Teacher")
        self.term_one_class = AcademicClass.objects.create(
            section=self.section,
            Class=self.class_obj,
            academic_year=self.year,
            term=self.term_one,
            fees_amount=100000,
        )
        self.term_one_stream = AcademicClassStream.objects.create(
            academic_class=self.term_one_class,
            stream=self.stream_a,
            class_teacher=self.teacher,
        )
        self.student = Student.objects.create(
            reg_no="TERM-A",
            student_name="Term Student",
            gender="M",
            birthdate=date(2012, 1, 1),
            nationality="Ugandan",
            religion="Muslim",
            address="Address",
            guardian="Guardian",
            relationship="Parent",
            contact="0700000000",
            academic_year=self.year,
            current_class=self.class_obj,
            stream=self.stream_a,
            term=self.term_one,
            is_active=True,
        )
        ClassRegister.objects.create(
            academic_class_stream=self.term_one_stream,
            student=self.student,
        )
        self.uniform_item = BillItem.objects.create(
            item_name="Uniform",
            category="Uniform",
            bill_duration="None",
            description="Uniform charge",
        )
        ClassBill.objects.create(
            academic_class=self.term_one_class,
            bill_item=self.uniform_item,
            amount=25000,
        )

    def _make_staff(self, first_name, last_name):
        return Staff.objects.create(
            first_name=first_name,
            last_name=last_name,
            birth_date=date(1990, 1, 1),
            gender="M",
            address="Address",
            marital_status="U",
            contacts="0700000000",
            email=f"{first_name.lower()}.{last_name.lower()}@example.com",
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

    def test_new_term_copies_only_existing_class_streams(self):
        term_two = Term.objects.create(
            academic_year=self.year,
            term="2",
            start_date=date(2026, 5, 1),
            end_date=date(2026, 8, 10),
            is_current=False,
        )
        term_two_class = AcademicClass.objects.get(
            academic_year=self.year,
            Class=self.class_obj,
            term=term_two,
        )

        self.assertTrue(
            AcademicClassStream.objects.filter(
                academic_class=term_two_class,
                stream=self.stream_a,
            ).exists()
        )
        self.assertFalse(
            AcademicClassStream.objects.filter(
                academic_class=term_two_class,
                stream=self.unused_stream,
            ).exists()
        )

    def test_activating_term_updates_registers_and_student_bill_items(self):
        term_two = Term.objects.create(
            academic_year=self.year,
            term="2",
            start_date=date(2026, 5, 1),
            end_date=date(2026, 8, 10),
            is_current=False,
        )
        term_two.is_current = True
        term_two.save()

        term_two_class = AcademicClass.objects.get(
            academic_year=self.year,
            Class=self.class_obj,
            term=term_two,
        )
        term_two_stream = AcademicClassStream.objects.get(
            academic_class=term_two_class,
            stream=self.stream_a,
        )
        self.assertTrue(
            ClassRegister.objects.filter(
                academic_class_stream=term_two_stream,
                student=self.student,
            ).exists()
        )
        self.student.refresh_from_db()
        self.assertEqual(self.student.term_id, term_two.id)

        student_bill = StudentBill.objects.get(
            student=self.student,
            academic_class=term_two_class,
        )
        self.assertGreater(student_bill.items.count(), 0)
        self.assertTrue(
            student_bill.items.filter(bill_item__item_name="School Fees").exists()
        )
        self.assertTrue(
            student_bill.items.filter(bill_item=self.uniform_item).exists()
        )


@override_settings(
    DATABASES={
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": ":memory:",
        }
    }
)
class RuntimeDatabaseAliasConfigTests(SimpleTestCase):
    def tearDown(self):
        unregister_database_alias("tenant_runtime_test")
        unregister_database_alias("tenant_runtime_test_2")
        super().tearDown()

    def test_register_database_alias_adds_backend_defaults(self):
        register_database_alias(
            "tenant_runtime_test",
            {
                "ENGINE": "django.db.backends.sqlite3",
                "NAME": ":memory:",
            },
        )

        alias_config = settings.DATABASES["tenant_runtime_test"]
        self.assertIn("TIME_ZONE", alias_config)
        self.assertIn("OPTIONS", alias_config)
        self.assertIn("TEST", alias_config)
        self.assertEqual(alias_config["TIME_ZONE"], None)
        self.assertEqual(alias_config["OPTIONS"], {})
        self.assertEqual(alias_config["TEST"]["MIGRATE"], True)

    def test_register_database_alias_preserves_explicit_values(self):
        register_database_alias(
            "tenant_runtime_test_2",
            {
                "ENGINE": "django.db.backends.sqlite3",
                "NAME": ":memory:",
                "TIME_ZONE": "UTC",
                "OPTIONS": {"timeout": 20},
                "TEST": {"MIRROR": "default"},
            },
        )

        alias_config = settings.DATABASES["tenant_runtime_test_2"]
        self.assertEqual(alias_config["TIME_ZONE"], "UTC")
        self.assertEqual(alias_config["OPTIONS"], {"timeout": 20})
        self.assertEqual(alias_config["TEST"]["MIRROR"], "default")
        self.assertEqual(alias_config["TEST"]["MIGRATE"], True)


class StudentPaymentLedgerTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="finance_admin", password="pass12345")
        self.client.force_login(self.user)

        self.year = AcademicYear.objects.create(academic_year="2026", is_current=True)
        self.term = Term.objects.create(
            academic_year=self.year,
            term="1",
            start_date=date(2026, 1, 10),
            end_date=date(2026, 4, 10),
            is_current=True,
        )
        self.section = Section.objects.create(section_name="Primary")
        self.class_obj = Class.objects.create(name="Grade 2", code="GD2", section=self.section)
        self.stream = Stream.objects.create(stream="A")
        self.academic_class = AcademicClass.objects.create(
            section=self.section,
            Class=self.class_obj,
            academic_year=self.year,
            term=self.term,
            fees_amount=500000,
        )

        self.student = Student.objects.create(
            reg_no="BLC-001",
            student_name="Amina Ali",
            gender="F",
            birthdate=date(2018, 1, 1),
            nationality="Ugandan",
            religion="Muslim",
            address="Kampala",
            guardian="Guardian",
            relationship="Parent",
            contact="0700000000",
            academic_year=self.year,
            current_class=self.class_obj,
            stream=self.stream,
            term=self.term,
            is_active=False,
        )
        self.assertTrue(self.student.reg_no.startswith("STD2026-"))

        self.bill = StudentBill.objects.create(
            student=self.student,
            academic_class=self.academic_class,
            status="Unpaid",
        )
        self.school_fees_item = BillItem.objects.create(
            item_name="School Fees",
            category="Tuition",
            bill_duration="Termly",
            description="Mandatory tuition",
        )
        self.uniform_item = BillItem.objects.create(
            item_name="Uniform",
            category="Uniform",
            bill_duration="None",
            description="Uniform charge",
        )
        StudentBillItem.objects.create(
            bill=self.bill,
            bill_item=self.school_fees_item,
            description="Term 1 tuition",
            amount=500000,
            charge_date=date(2026, 1, 15),
            fee_category="Tuition",
        )
        StudentBillItem.objects.create(
            bill=self.bill,
            bill_item=self.uniform_item,
            description="Uniform set",
            amount=100000,
            charge_date=date(2026, 1, 20),
            fee_category="Uniform",
        )
        Payment.objects.create(
            bill=self.bill,
            payment_date=date(2026, 7, 10),
            amount=200000,
            payment_method="Cash",
            fee_category="Tuition",
            reference_no="PMT-001",
            recorded_by="finance_admin",
            notes="Cash collection",
        )
        Payment.objects.create(
            bill=self.bill,
            payment_date=date(2026, 7, 20),
            amount=300000,
            payment_method="SchoolPay",
            fee_category="Tuition",
            reference_no="PMT-002",
            recorded_by="finance_admin",
            notes="SchoolPay settlement",
        )

    def test_inactive_student_history_remains_accessible(self):
        response = self.client.get(reverse("student_fees_history", args=[self.student.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.student.student_name)
        self.assertContains(response, self.student.reg_no)

    def test_inactive_student_can_be_reactivated(self):
        response = self.client.post(
            reverse("delete_student_page", args=[self.student.id]),
            {"action": "reactivate"},
        )
        self.assertEqual(response.status_code, 302)
        self.student.refresh_from_db()
        self.assertTrue(self.student.is_active)

    def test_student_delete_is_blocked(self):
        with self.assertRaises(ValidationError):
            self.student.delete()

    def test_student_without_reg_no_gets_generated_reg_no(self):
        generated_student = Student.objects.create(
            reg_no="",
            student_name="Generated Reg Student",
            gender="F",
            birthdate=date(2018, 3, 1),
            nationality="Ugandan",
            religion="Muslim",
            address="Kampala",
            guardian="Guardian",
            relationship="Parent",
            contact="0700000003",
            academic_year=self.year,
            current_class=self.class_obj,
            stream=self.stream,
            term=self.term,
            is_active=True,
        )

        self.assertTrue(generated_student.reg_no.startswith("STD2026-"))

    def test_ledger_page_renders_transaction_rows(self):
        response = self.client.get(
            reverse("payment_ledger"),
            {"student": self.student.id, "term": self.term.id, "year": self.year.id},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Student Payment Ledger")
        self.assertContains(response, self.student.student_name)
        self.assertContains(response, self.student.reg_no)
        self.assertContains(response, "Term 1 2026")
        self.assertContains(response, "SchoolPay")

    def test_ledger_page_highlights_insights_and_credit_adjustments(self):
        rebate_item = BillItem.objects.create(
            item_name="Transport rebate",
            category="Transport",
            bill_duration="None",
            description="Transport correction",
        )
        StudentBillItem.objects.create(
            bill=self.bill,
            bill_item=rebate_item,
            description="Transport rebate",
            amount=-34000,
            charge_date=date(2026, 1, 25),
            fee_category="Transport",
        )

        overpaid_student = Student.objects.create(
            reg_no="BLC-002",
            student_name="Yusuf Musa",
            gender="M",
            birthdate=date(2018, 2, 1),
            nationality="Ugandan",
            religion="Muslim",
            address="Kampala",
            guardian="Guardian",
            relationship="Parent",
            contact="0700000001",
            academic_year=self.year,
            current_class=self.class_obj,
            stream=self.stream,
            term=self.term,
            is_active=True,
        )
        overpaid_bill = StudentBill.objects.create(
            student=overpaid_student,
            academic_class=self.academic_class,
            status="Paid",
        )
        StudentBillItem.objects.create(
            bill=overpaid_bill,
            bill_item=self.school_fees_item,
            description="Term 1 tuition",
            amount=120000,
            charge_date=date(2026, 1, 12),
            fee_category="Tuition",
        )
        Payment.objects.create(
            bill=overpaid_bill,
            payment_date=date(2026, 1, 18),
            amount=150000,
            payment_method="Cash",
            fee_category="Tuition",
            reference_no="PMT-003",
            recorded_by="finance_admin",
            notes="Overpayment",
        )

        response = self.client.get(reverse("payment_ledger"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Top Outstanding Student")
        self.assertContains(response, "Top Credit")
        self.assertContains(response, "Largest Charge Category")
        self.assertContains(response, "Amina Ali")
        self.assertContains(response, "Yusuf Musa")
        self.assertContains(response, "Credit Adjustment")
        self.assertContains(response, "34,000")
        self.assertNotContains(response, "-34,000")

    def test_ledger_excel_export_respects_payment_method_filter(self):
        response = self.client.get(
            reverse("payment_ledger"),
            {
                "student": self.student.id,
                "payment_method": ["Cash"],
                "export": "excel",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        with ZipFile(BytesIO(response.content)) as archive:
            worksheet_xml = archive.read("xl/worksheets/sheet1.xml").decode("utf-8")

        self.assertIn("Date", worksheet_xml)
        self.assertIn("Reg. No.", worksheet_xml)
        self.assertIn("Student Name", worksheet_xml)
        self.assertIn("Amount Charged", worksheet_xml)
        self.assertIn("Amount Paid", worksheet_xml)
        self.assertIn("Notes", worksheet_xml)
        self.assertIn("Cash", worksheet_xml)
        self.assertNotIn("SchoolPay", worksheet_xml)
        self.assertNotIn("Running Balance", worksheet_xml)
        self.assertNotIn("Reference ID", worksheet_xml)
        self.assertNotIn("Description", worksheet_xml)

    def test_fees_help_page_renders_guidance(self):
        response = self.client.get(reverse("fees_help"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Fees Reporting Help")
        self.assertContains(response, "How Ledger Reports Are Generated")
        self.assertContains(response, "How Student Status Is Managed")


class CombinedAssessmentDivisionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="results_admin", password="pass12345")
        self.client.force_login(self.user)

        school_setting = SchoolSetting.load()
        school_setting.education_level = SchoolSetting.EducationLevel.PRIMARY
        school_setting.save(update_fields=["education_level"])

        session = self.client.session
        session["active_school_level"] = SchoolSetting.EducationLevel.PRIMARY
        session.save()

        self.year = AcademicYear.objects.create(academic_year="2026", is_current=True)
        self.term = Term.objects.create(
            academic_year=self.year,
            term="1",
            start_date=date(2026, 1, 10),
            end_date=date(2026, 4, 10),
            is_current=True,
        )
        self.section = Section.objects.create(section_name="Primary")
        self.class_obj = Class.objects.create(name="Grade 5", code="GD5", section=self.section)
        self.stream = Stream.objects.create(stream="A")
        self.academic_class = AcademicClass.objects.create(
            section=self.section,
            Class=self.class_obj,
            academic_year=self.year,
            term=self.term,
            fees_amount=500000,
        )

        self.teacher = Staff.objects.create(
            first_name="Primary",
            last_name="Teacher",
            birth_date=date(1990, 1, 1),
            gender="M",
            address="Kampala",
            marital_status="U",
            contacts="0700000000",
            email="teacher@example.com",
            qualification="Degree",
            nin_no="CFX1234567890A",
            hire_date=date(2020, 1, 1),
            department="Academic",
            salary="1000000.00",
            is_academic_staff=True,
            is_administrator_staff=False,
            is_support_staff=False,
            staff_status="Active",
            staff_photo=SimpleUploadedFile("teacher.jpg", b"fake-image-bytes", content_type="image/jpeg"),
        )
        self.class_stream = AcademicClassStream.objects.create(
            academic_class=self.academic_class,
            stream=self.stream,
            class_teacher=self.teacher,
        )

        self.student = Student.objects.create(
            reg_no="STD2026-29",
            student_name="Aayan Haroun Mugagga",
            gender="M",
            birthdate=date(2015, 1, 1),
            nationality="Ugandan",
            religion="Muslim",
            address="Kampala",
            guardian="Guardian",
            relationship="Parent",
            contact="0700000001",
            academic_year=self.year,
            current_class=self.class_obj,
            stream=self.stream,
            term=self.term,
            is_active=True,
        )
        ClassRegister.objects.create(
            academic_class_stream=self.class_stream,
            student=self.student,
            payment_status="Paid",
        )

        grading_rows = [
            ("90.00", "100.00", "D1", "1.00"),
            ("80.00", "89.00", "D2", "2.00"),
            ("70.00", "79.00", "C3", "3.00"),
            ("60.00", "69.00", "C4", "4.00"),
            ("55.00", "59.00", "C5", "5.00"),
            ("50.00", "54.00", "C6", "6.00"),
            ("45.00", "49.00", "P7", "7.00"),
            ("40.00", "44.00", "P8", "8.00"),
            ("0.00", "39.00", "F9", "9.00"),
        ]
        for min_score, max_score, grade, points in grading_rows:
            GradingSystem.objects.create(
                min_score=Decimal(min_score),
                max_score=Decimal(max_score),
                grade=grade,
                points=Decimal(points),
            )

        self.bot = AssessmentType.objects.create(name="BEGINNING OF TERM", weight=Decimal("1.00"))
        self.mid = AssessmentType.objects.create(name="MID TERM EXAM", weight=Decimal("1.00"))

        subjects = [
            ("ENG", "ENGLISH"),
            ("MTC", "MATHEMATICS"),
            ("SCI", "SCIENCE"),
            ("SST", "SOCIAL STUDIES"),
        ]
        score_map = {
            "ENGLISH": {"BEGINNING OF TERM": "59.00", "MID TERM EXAM": "80.00"},
            "MATHEMATICS": {"BEGINNING OF TERM": "59.00", "MID TERM EXAM": "50.00"},
            "SCIENCE": {"BEGINNING OF TERM": "47.00", "MID TERM EXAM": "55.00"},
            "SOCIAL STUDIES": {"BEGINNING OF TERM": "51.00", "MID TERM EXAM": "66.00"},
        }

        for code, name in subjects:
            subject = Subject.objects.create(
                code=code,
                name=name,
                description=name,
                credit_hours=1,
                section=self.section,
                type="Core",
            )
            for assessment_type in [self.bot, self.mid]:
                assessment = Assessment.objects.create(
                    academic_class=self.academic_class,
                    assessment_type=assessment_type,
                    subject=subject,
                    date=date(2026, 2, 1),
                    out_of=100,
                    is_done=True,
                )
                Result.objects.create(
                    assessment=assessment,
                    student=self.student,
                    score=Decimal(score_map[name][assessment_type.name]),
                    status="VERIFIED",
                )

    def test_combined_assessment_print_uses_combined_subject_points_for_division(self):
        response = self.client.get(
            reverse("class_assessment_combined_print"),
            {
                "academic_year_id": self.year.id,
                "term_id": self.term.id,
                "class_id": self.class_obj.id,
                "report_format": "standard",
                "assessment_type_ids": [self.bot.id, self.mid.id],
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.student.student_name)
        self.assertContains(response, "Division 2")
        self.assertContains(response, "TERM 1 2026 REPORT CARD")
        self.assertContains(response, 'colspan="5"', html=False)

    def test_tahfiz_combined_preview_and_print_only_include_tahfiz_subjects(self):
        tahfiz_subject = Subject.objects.create(
            code="FIQH",
            name="الفِقْه",
            description="Fiqh",
            credit_hours=1,
            section=self.section,
            type="Core",
        )
        for assessment_type, score in (
            (self.bot, Decimal("78.00")),
            (self.mid, Decimal("82.00")),
        ):
            assessment = Assessment.objects.create(
                academic_class=self.academic_class,
                assessment_type=assessment_type,
                subject=tahfiz_subject,
                date=date(2026, 2, 2),
                out_of=100,
                is_done=True,
            )
            Result.objects.create(
                assessment=assessment,
                student=self.student,
                score=score,
                status="VERIFIED",
            )

        params = {
            "academic_year_id": self.year.id,
            "term_id": self.term.id,
            "class_id": self.class_obj.id,
            "report_format": "tahfiz",
            "assessment_type_ids": [self.bot.id, self.mid.id],
        }

        response = self.client.get(reverse("class_assessment_combined"), params)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["subjects"], ["الفِقْه"])

        print_response = self.client.get(reverse("class_assessment_combined_print"), params)
        self.assertEqual(print_response.status_code, 200)
        report_rows = print_response.context["reports"][0]["report_data"]
        self.assertEqual([row["subject"] for row in report_rows], ["الفِقْه"])
