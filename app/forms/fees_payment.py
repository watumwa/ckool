from django import forms
from django.forms import ModelForm, HiddenInput, DateInput, Textarea
from crispy_forms.helper import FormHelper
from app.models.fees_payment import BillItem, StudentBillItem, Payment,ClassBill

class BillItemForm(ModelForm):
    
    class Meta:
        model = BillItem
        fields = ("__all__")


class StudentBillItemForm(ModelForm):
    
    class Meta:
        model = StudentBillItem
        fields = ("bill", "bill_item", "description", "amount", "fee_category", "charge_date", "notes")
        
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.Helper = FormHelper()
        self.fields["bill"].widget = HiddenInput()
        self.fields["charge_date"].widget = DateInput(attrs={"type": "date"})
        self.fields["notes"].widget = Textarea(attrs={"rows": 2})



class ClassBillForm(ModelForm):
    class Meta:
        model = ClassBill
        fields = ['bill_item','amount']


class PaymentForm(ModelForm):
    def __init__(self, *args, bill=None, **kwargs):
        self.bill = bill
        super().__init__(*args, **kwargs)
        self.Helper = FormHelper()

        if "reference_no" in self.fields:
            self.fields["reference_no"].required = False
            self.fields["reference_no"].help_text = "This will be auto-filled by the system if left blank."

        self.fields["fee_category"].required = False
        self.fields["fee_category"].help_text = "Leave blank to use the bill's main charge category."
        self.fields["payment_date"].widget = DateInput(attrs={"type": "date"})
        self.fields["notes"].widget = Textarea(attrs={"rows": 3})

    class Meta:
        model = Payment
        fields = ["payment_date", "fee_category", "amount", "payment_method", "reference_no", "notes"]

    def clean(self):
        cleaned_data = super().clean()
        amount = cleaned_data.get("amount")

        if self.bill and amount is not None:
            balance = self.bill.balance or 0
            if balance <= 0:
                raise forms.ValidationError("This bill has no outstanding balance.")
            if amount > balance:
                raise forms.ValidationError(
                    f"Amount exceeds the outstanding balance of UGX {balance:,.0f}."
                )

        if self.bill and not cleaned_data.get("fee_category"):
            categories = [
                category for category in self.bill.items.values_list("fee_category", flat=True).distinct() if category
            ]
            if len(categories) == 1:
                cleaned_data["fee_category"] = categories[0]
            elif categories:
                cleaned_data["fee_category"] = "Other"

        return cleaned_data
