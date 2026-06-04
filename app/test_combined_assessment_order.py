from decimal import Decimal

from django.test import TestCase

from app.models.results import AssessmentType
from app.views.results import _assessment_type_order_case


class CombinedAssessmentOrderTests(TestCase):
    def test_mid_term_exam_follows_beginning_and_end_of_term_comes_last(self):
        beginning = AssessmentType.objects.create(name="BEGINNING OF TERM", weight=Decimal("1.00"))
        end_external = AssessmentType.objects.create(name="END OF TERM EXTERNAL", weight=Decimal("1.00"))
        end_internal_exam = AssessmentType.objects.create(name="END OF TERM INTERNAL EXAM", weight=Decimal("1.00"))
        mid_term_exam = AssessmentType.objects.create(name="MID TERM EXAM", weight=Decimal("1.00"))

        ordered_names = list(
            AssessmentType.objects.filter(
                id__in=[beginning.id, end_external.id, end_internal_exam.id, mid_term_exam.id]
            )
            .order_by(_assessment_type_order_case(), "name")
            .values_list("name", flat=True)
        )

        self.assertEqual(
            ordered_names,
            [
                "BEGINNING OF TERM",
                "MID TERM EXAM",
                "END OF TERM INTERNAL EXAM",
                "END OF TERM EXTERNAL",
            ],
        )
