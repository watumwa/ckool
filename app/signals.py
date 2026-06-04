from django.db.models.signals import post_save, pre_save, post_delete, pre_delete
from django.dispatch import receiver
from django.db import transaction
from django.core.exceptions import ValidationError
from app.models.students import Student, ClassRegister
from app.models.fees_payment import StudentBill, StudentBillItem, BillItem, ClassBill, Payment, StudentCredit
from app.models.classes import AcademicClass, AcademicClassStream, Class, Term
from app.models.school_settings import AcademicYear
from app.models.finance import Transaction, IncomeSource, Expenditure, ExpenditureItem

 
def _get_or_create_student_bill(student, academic_class):
    student_bill = (
        StudentBill.objects.filter(student=student, academic_class=academic_class)
        .order_by("id")
        .first()
    )
    if student_bill:
        return student_bill, False
    return StudentBill.objects.create(
        student=student,
        academic_class=academic_class,
        status="Unpaid",
    ), True


def _ensure_student_bill_items(student, academic_class):
    student_bill, bill_created = _get_or_create_student_bill(student, academic_class)
    created_or_updated = bill_created

    for class_bill in ClassBill.objects.filter(academic_class=academic_class).select_related("bill_item"):
        qs = StudentBillItem.objects.filter(
            bill=student_bill,
            bill_item=class_bill.bill_item,
        ).order_by("id")
        if qs.exists():
            student_bill_item = qs.first()
            if qs.count() > 1:
                qs.exclude(pk=student_bill_item.pk).delete()
            if (
                student_bill_item.description != class_bill.bill_item.description
                or student_bill_item.amount != class_bill.amount
            ):
                student_bill_item.description = class_bill.bill_item.description
                student_bill_item.amount = class_bill.amount
                student_bill_item.save()
                created_or_updated = True
        else:
            StudentBillItem.objects.create(
                bill=student_bill,
                bill_item=class_bill.bill_item,
                description=class_bill.bill_item.description,
                amount=class_bill.amount,
            )
            created_or_updated = True

    return student_bill, created_or_updated


def _copy_class_bills(source_academic_class, target_academic_class):
    if not source_academic_class:
        return

    for source_bill in ClassBill.objects.filter(
        academic_class=source_academic_class
    ).select_related("bill_item"):
        ClassBill.objects.get_or_create(
            academic_class=target_academic_class,
            bill_item=source_bill.bill_item,
            defaults={"amount": source_bill.amount},
        )


def _previous_term_for(term):
    previous = (
        Term.objects.filter(
            academic_year=term.academic_year,
            end_date__lt=term.start_date,
        )
        .exclude(id=term.id)
        .order_by("-end_date", "-id")
        .first()
    )
    if previous:
        return previous
    return (
        Term.objects.filter(academic_year=term.academic_year)
        .exclude(id=term.id)
        .order_by("-end_date", "-id")
        .first()
    )


def _previous_academic_class_for(academic_class):
    return (
        AcademicClass.objects.filter(
            academic_year=academic_class.academic_year,
            Class=academic_class.Class,
            section=academic_class.section,
            term__end_date__lt=academic_class.term.start_date,
        )
        .exclude(id=academic_class.id)
        .order_by("-term__end_date", "-id")
        .first()
    ) or (
        AcademicClass.objects.filter(
            academic_year=academic_class.academic_year,
            Class=academic_class.Class,
            section=academic_class.section,
        )
        .exclude(id=academic_class.id)
        .order_by("-term__end_date", "-id")
        .first()
    )


def _ensure_class_stream_from_source(target_academic_class, source_class_stream):
    class_stream, created = AcademicClassStream.objects.get_or_create(
        academic_class=target_academic_class,
        stream=source_class_stream.stream,
        defaults={
            "class_teacher": source_class_stream.class_teacher,
            "class_teacher_signature": source_class_stream.class_teacher_signature,
        },
    )
    if not created and not class_stream.class_teacher_id:
        class_stream.class_teacher = source_class_stream.class_teacher
        class_stream.save(update_fields=["class_teacher"])
    return class_stream, created


def _class_streams_to_copy(source_academic_class):
    registered_stream_ids = (
        ClassRegister.objects.filter(
            academic_class_stream__academic_class=source_academic_class,
            student__is_active=True,
        )
        .values_list("academic_class_stream_id", flat=True)
        .distinct()
    )
    registered_streams = AcademicClassStream.objects.filter(
        id__in=registered_stream_ids,
    ).select_related("stream", "class_teacher")
    if registered_streams.exists():
        return registered_streams

    return AcademicClassStream.objects.filter(
        academic_class=source_academic_class,
    ).select_related("stream", "class_teacher")


@receiver(pre_save, sender=AcademicClass)
def track_fees_amount_change(sender, instance, **kwargs):
    """
    Track the original fees_amount before saving to detect changes
    """
    if instance.pk:  
        try:
            original = AcademicClass.objects.get(pk=instance.pk)
            instance._original_fees_amount = original.fees_amount
        except AcademicClass.DoesNotExist:
            pass


@receiver(post_save, sender=AcademicClass)
def create_class_bill(sender, instance, created, **kwargs):
    # Handle both creation and updates to fees_amount
    if created or hasattr(instance, '_original_fees_amount'):
        # Check if fees_amount has changed (for updates)
        fees_changed = False
        if hasattr(instance, '_original_fees_amount'):
            fees_changed = instance._original_fees_amount != instance.fees_amount
        else:
            fees_changed = True  # For new instances

        if created or fees_changed:
            bill_item, _ = BillItem.objects.get_or_create(
                item_name="School Fees",
                defaults={
                    "category": "Tuition",
                    "bill_duration": "Termly",
                    "description": "Mandatory school fees"
                }
            )

            # Update or create ClassBill
            class_bill, created = ClassBill.objects.get_or_create(
                academic_class=instance,
                bill_item=bill_item,
                defaults={"amount": instance.fees_amount}
            )

            # Update existing ClassBill amount
            if not created:
                class_bill.amount = instance.fees_amount
                class_bill.save()

            # Update all existing StudentBillItem for this class
            if not created:  # Only for updates, not new creations
                student_bills = StudentBill.objects.filter(academic_class=instance)
                for student_bill in student_bills:
                    # Ensure a single StudentBillItem per (bill, bill_item); clean up duplicates if any
                    qs = StudentBillItem.objects.filter(
                        bill=student_bill,
                        bill_item=bill_item
                    ).order_by('id')
                    if qs.exists():
                        student_bill_item = qs.first()
                        # Remove any duplicates to enforce one item per bill/bill_item
                        if qs.count() > 1:
                            qs.exclude(pk=student_bill_item.pk).delete()
                        # Update description and amount to reflect current class fees
                        student_bill_item.description = f'School Fees - {instance}'
                        student_bill_item.amount = instance.fees_amount
                        student_bill_item.save()
                    else:
                        StudentBillItem.objects.create(
                            bill=student_bill,
                            bill_item=bill_item,
                            description=f'School Fees - {instance}',
                            amount=instance.fees_amount
                        )

@receiver(post_save, sender=Student)
def create_student_bill(sender, instance, created, **kwargs):
    if created:
        academic_class = AcademicClass.objects.filter(
            academic_year=instance.academic_year,
            Class=instance.current_class,
            term=instance.term,
        ).first()
        if not academic_class:
            return

        _ensure_student_bill_items(instance, academic_class)


@receiver(pre_delete, sender=Student)
def prevent_student_deletion(sender, instance, **kwargs):
    raise ValidationError("Students cannot be deleted. Mark the student inactive instead.")

        

@receiver(post_save, sender=AcademicYear)
def ensure_single_current_academic_year(sender, instance, created, **kwargs):
    """
    Ensure only one AcademicYear is marked as current.
    """
    if instance.is_current:
        # Set all other AcademicYears to is_current=False
        other_current_years = AcademicYear.objects.filter(is_current=True).exclude(id=instance.id)
        if other_current_years.exists():
            other_current_years.update(is_current=False)


@receiver(post_save, sender=Term)
def move_students_on_term_change(sender, instance, created, **kwargs):
    """
    Automatically move students to the new current term when a term is marked as current.
    This includes maintaining their class/stream assignments and creating new bills.
    Enhanced to handle edge cases and provide better logging.
    """
    if instance.is_current:

        # Ensure only one term is marked as current
        other_current_terms = Term.objects.filter(is_current=True).exclude(id=instance.id)
        if other_current_terms.exists():
            other_current_terms.update(is_current=False)

        previous_term = _previous_term_for(instance)

        if previous_term:
            previous_registers = (
                ClassRegister.objects.filter(
                    academic_class_stream__academic_class__academic_year=instance.academic_year,
                    academic_class_stream__academic_class__term=previous_term,
                    student__is_active=True,
                )
                .select_related(
                    "student",
                    "student__current_class",
                    "student__stream",
                    "academic_class_stream",
                    "academic_class_stream__stream",
                    "academic_class_stream__class_teacher",
                    "academic_class_stream__academic_class",
                    "academic_class_stream__academic_class__Class",
                    "academic_class_stream__academic_class__section",
                )
                .order_by("student_id", "id")
            )

            if previous_registers.exists():

                moved_count = 0
                registered_count = 0
                bills_created_count = 0
                errors_count = 0
                seen_students = set()

                with transaction.atomic():
                    for previous_register in previous_registers:
                        student = previous_register.student
                        if student.id in seen_students:
                            continue
                        seen_students.add(student.id)
                        source_stream = previous_register.academic_class_stream
                        source_academic_class = source_stream.academic_class
                        try:
                            # Move student to new term
                            student.term = instance
                            student.academic_year = instance.academic_year
                            student.current_class = source_academic_class.Class
                            student.stream = source_stream.stream
                            student.save(
                                update_fields=[
                                    "term",
                                    "academic_year",
                                    "current_class",
                                    "stream",
                                ]
                            )
                            moved_count += 1

                            # Get the correct AcademicClass for the new term
                            academic_class, _ = AcademicClass.objects.get_or_create(
                                academic_year=instance.academic_year,
                                Class=source_academic_class.Class,
                                term=instance,
                                defaults={
                                    "section": source_academic_class.section,
                                    "fees_amount": source_academic_class.fees_amount,
                                },
                            )
                            _copy_class_bills(source_academic_class, academic_class)

                            class_stream, _ = _ensure_class_stream_from_source(
                                academic_class,
                                source_stream,
                            )
                            _, register_created = ClassRegister.objects.get_or_create(
                                academic_class_stream=class_stream,
                                student=student,
                            )
                            if register_created:
                                registered_count += 1

                            _, bill_changed = _ensure_student_bill_items(student, academic_class)
                            if bill_changed:
                                bills_created_count += 1

                            previous_term_bills = StudentBill.objects.filter(
                                student=student,
                                academic_class__academic_year=instance.academic_year
                            ).exclude(academic_class__term=instance)

                            for prev_bill in previous_term_bills:
                                unused_credits = StudentCredit.objects.filter(
                                    student=student,
                                    original_bill=prev_bill,
                                    is_applied=False
                                )

                                for credit in unused_credits:
                                    existing_carry_forward = StudentCredit.objects.filter(
                                        student=student,
                                        description__icontains=f'Carried forward from {previous_term.term}',
                                        original_bill=credit.original_bill,
                                        is_applied=False
                                    ).exists()

                                    if not existing_carry_forward:
                                        StudentCredit.objects.create(
                                            student=student,
                                            amount=credit.amount,
                                            description=f'Carried forward from {previous_term.term}: {credit.description}',
                                            original_bill=credit.original_bill,
                                            applied_to_bill=None,
                                            is_applied=False
                                        )

                        except Exception as e:
                            # Log error but continue with other students
                            errors_count += 1
                            continue

                # Summary message
                pass
            else:
                pass
        else:
            pass


@receiver(post_save, sender=Term)
def auto_create_academic_classes(sender, instance, created, **kwargs):
    """
    Automatically create AcademicClass records when a new Term is created
    """
    if created:
        # Get all classes
        classes = Class.objects.all()
        academic_year = instance.academic_year

        # Get the previous term to copy fees from
        previous_term = _previous_term_for(instance)

        for class_obj in classes:
            # Check if AcademicClass already exists
            if not AcademicClass.objects.filter(
                academic_year=academic_year,
                Class=class_obj,
                term=instance
            ).exists():
                # Get fees amount from previous term's class
                fees_amount = 0
                if previous_term:
                    previous_academic_class = AcademicClass.objects.filter(
                        academic_year=academic_year,
                        Class=class_obj,
                        term=previous_term
                    ).first()
                    if previous_academic_class:
                        fees_amount = previous_academic_class.fees_amount

                # Create AcademicClass with copied fee amount
                AcademicClass.objects.create(
                    academic_year=academic_year,
                    Class=class_obj,
                    term=instance,
                    section=class_obj.section,
                    fees_amount=fees_amount
                )


@receiver(post_save, sender=AcademicClass)
def auto_create_academic_class_streams(sender, instance, created, **kwargs):
    """
    Copy class streams from the previous matching academic class.
    """
    if created:
        previous_academic_class = _previous_academic_class_for(instance)
        if not previous_academic_class:
            return

        previous_streams = _class_streams_to_copy(previous_academic_class)
        for previous_stream in previous_streams:
            _ensure_class_stream_from_source(instance, previous_stream)


@receiver([post_save, post_delete], sender=Payment)
def update_bill_status_on_payment(sender, instance, **kwargs):
    """
    Automatically update StudentBill status when payments are added, updated, or deleted
    """
    bill = instance.bill

    # Refresh the bill from database to get updated payment calculations
    bill.refresh_from_db()

    # Update status based on payment status
    if bill.balance <= 0:
        bill.status = 'Paid'
    elif bill.amount_paid > 0:
        bill.status = 'Unpaid'  # Partial payment
    else:
        bill.status = 'Unpaid'

    bill.save(update_fields=['status'])


@receiver([post_save, post_delete], sender=Payment)
def handle_overpayment_credit(sender, instance, **kwargs):
    """
    Automatically detect overpayments and create credit records
    """
    bill = instance.bill

    # Refresh the bill from database to get updated payment calculations
    bill.refresh_from_db()

    # Check if there's an overpayment (amount paid > total amount)
    if bill.amount_paid > bill.total_amount:
        overpayment_amount = bill.amount_paid - bill.total_amount

        # Check if credit already exists for this overpayment
        existing_credit = StudentCredit.objects.filter(
            student=bill.student,
            original_bill=bill,
            description__icontains='overpayment',
            is_applied=False
        ).first()

        if not existing_credit:
            # Create credit for overpayment
            StudentCredit.objects.create(
                student=bill.student,
                amount=overpayment_amount,
                description=f'Overpayment credit from bill #{bill.id}',
                original_bill=bill,
                is_applied=False
            )
        else:
            # Update existing credit if amount changed
            if existing_credit.amount != overpayment_amount:
                existing_credit.amount = overpayment_amount
                existing_credit.save()


@receiver(post_save, sender=StudentBill)
def apply_available_credits(sender, instance, created, **kwargs):
    """
    Automatically apply available credits to new bills
    """
    if created and instance.balance > 0:
        # Get available credits for this student
        available_credits = instance.available_credits

        if available_credits > 0:
            # Apply credits to reduce the bill balance
            credit_applied = instance.apply_credit(instance.balance)

            if credit_applied > 0:
                # Update bill status after applying credit
                instance.refresh_from_db()
                if instance.balance <= 0:
                    instance.status = 'Paid'
                    instance.save(update_fields=['status'])


@receiver(post_save, sender=Payment)
def update_bill_after_payment(sender, instance, created, **kwargs):
    """
    Additional check to ensure bill is updated after any payment
    """
    if created:
        bill = instance.bill
        bill.refresh_from_db()

        # Force recalculation of balance and status
        if bill.balance <= 0:
            bill.status = 'Paid'
        elif bill.amount_paid > 0:
            bill.status = 'Unpaid'  # Partial payment
        else:
            bill.status = 'Unpaid'

        bill.save(update_fields=['status'])


# === Mirror Student Payments and Expenditures into Transaction model ===
# This keeps the Income Statement (which reads Transaction) in sync with operational data.

def _payment_tx_description(payment):
    return f"Student payment bill#{payment.bill_id} ref {payment.reference_no}"


@receiver(post_save, sender=Payment)
def mirror_payment_to_transaction(sender, instance, **kwargs):
    """
    Ensure each Payment creates/updates a corresponding Income Transaction.
    Using reference_no in the description to provide idempotency on update.
    """
    try:
        desc = _payment_tx_description(instance)
        source, _ = IncomeSource.objects.get_or_create(
            name="School fees",
            defaults={"description": "Payments collected from student bills"},
        )
        Transaction.objects.update_or_create(
            description=desc,
            defaults={
                "date": instance.payment_date,
                "transaction_type": "Income",
                "amount": instance.amount,
                "related_income_source": source,
            },
        )
    except Exception:
        # Avoid breaking save flow if mirroring fails
        pass


@receiver(post_delete, sender=Payment)
def delete_payment_transaction(sender, instance, **kwargs):
    """
    Remove mirrored Transaction when a Payment is deleted.
    """
    try:
        desc = _payment_tx_description(instance)
        Transaction.objects.filter(description=desc).delete()
    except Exception:
        pass


def _expenditure_tx_description(exp):
    vendor = exp.vendor.name if getattr(exp, "vendor", None) else "No vendor"
    return f"Expenditure#{exp.id} {vendor}"


def _upsert_expenditure_transaction(exp):
    try:
        desc = _expenditure_tx_description(exp)
        Transaction.objects.update_or_create(
            description=desc,
            defaults={
                "date": exp.date_incurred,
                "transaction_type": "Expense",
                "amount": exp.amount,  # includes items total + VAT (via property)
                "related_income_source": None,
            },
        )
    except Exception:
        pass


@receiver(post_save, sender=Expenditure)
def mirror_expenditure_to_transaction(sender, instance, **kwargs):
    """
    Create/update an Expense Transaction for each Expenditure.
    """
    _upsert_expenditure_transaction(instance)


@receiver(post_delete, sender=Expenditure)
def delete_expenditure_transaction(sender, instance, **kwargs):
    """
    Remove mirrored Transaction when an Expenditure is deleted.
    """
    try:
        desc = _expenditure_tx_description(instance)
        Transaction.objects.filter(description=desc).delete()
    except Exception:
        pass


@receiver([post_save, post_delete], sender=ExpenditureItem)
def sync_expenditure_item_change(sender, instance, **kwargs):
    """
    Keep the mirrored Expense Transaction amount in sync when ExpenditureItems change.
    """
    exp = instance.expenditure
    if exp:
        _upsert_expenditure_transaction(exp)
