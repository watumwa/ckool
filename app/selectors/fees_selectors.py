from app.models.fees_payment import *
from django.shortcuts import get_object_or_404
from app.models.students import *
from app.models.classes import *


def get_student_bills():
    return StudentBill.objects.all()

def get_student_bill(id):
    return get_object_or_404(StudentBill, pk=id)

def get_academic_class_bills(academic_class):
    return StudentBill.objects.filter(
        academic_class=academic_class,
    )

def get_academic_class_bill_item(academic_class):
    academic_class_bills = get_academic_class_bills(academic_class)
    
    bill_item = StudentBillItem.objects.filter(bill__in = academic_class_bills)
    
    return bill_item

def get_bill_items():
    return BillItem.objects.all()

def get_bill_item(id):
    return BillItem.objects.get(pk=id)

def get_bill_item_by_name(item_name):
    return BillItem.objects.get(item_name=item_name)

def get_student_bill_details(bill_id):
    student_bill = get_object_or_404(StudentBill, id=bill_id)

    total_amount = student_bill.total_amount or 0 
    amount_paid = student_bill.amount_paid or 0
    balance = total_amount - amount_paid
    if total_amount > 0:
        amount_paid_percentage = (amount_paid / total_amount) * 100
        balance_percentage = (balance / total_amount) * 100
    else:
        amount_paid_percentage = 0
        balance_percentage = 0

    # Determine payment status
    if amount_paid > total_amount:
        payment_status = "CR"  # Overpaid
    elif amount_paid < total_amount:
        payment_status = "DR"  # Underpaid
    else:
        payment_status = "Balanced"

    context = {
        "student_bill": student_bill,
        "amount_paid_percentage": amount_paid_percentage,
        "balance_percentage": balance_percentage,
        "payment_status": payment_status,
        "balance": balance,
    }
    
    return context
