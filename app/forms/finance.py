from django.forms import ModelForm, HiddenInput, DateInput
from crispy_forms.helper import FormHelper

from app.models.finance import *
from app.models.classes import Term
from app.models.school_settings import AcademicYear

class IncomeSourceForm(ModelForm):
    
    class Meta:
        model = IncomeSource
        fields = ("__all__")

class VendorForm(ModelForm):
    
    class Meta:
        model = Vendor
        fields = ("__all__")


class BudgetForm(ModelForm):
    
    class Meta:
        model = Budget
        fields = ("__all__")

class BudgetItemForm(ModelForm):
    
    class Meta:
        model = BudgetItem
        fields = ("__all__")
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.Helper = FormHelper()
        self.fields["budget"].widget = HiddenInput()

class ExpenseForm(ModelForm):
    
    class Meta:
        model = Expense
        fields = ("__all__")

class ExpenditureForm(ModelForm):
    
    class Meta:
        model = Expenditure
        fields = ("__all__")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.Helper = FormHelper()
        self.fields["date_incurred"].widget = DateInput(attrs={
            "type": "date",
        })
        # Limit selectable Budget Items to the currently active academic year and term
        try:
            current_year = AcademicYear.objects.filter(is_current=True).first()
            current_term = Term.objects.filter(is_current=True, academic_year=current_year).first() if current_year else Term.objects.filter(is_current=True).first()
            if 'budget_item' in self.fields and current_year and current_term:
                self.fields['budget_item'].queryset = BudgetItem.objects.filter(
                    budget__academic_year=current_year,
                    budget__term=current_term
                )
        except Exception:
            # Fail-safe: do not block form rendering if anything goes wrong
            pass
        
class ExpenditureItemForm(ModelForm):
    
    class Meta:
        model = ExpenditureItem
        fields = ("__all__")
        
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.Helper = FormHelper()
        self.fields["expenditure"].widget = HiddenInput()
        # self.fields["expenditure"].widget = HiddenInput()


class TransactionForm(ModelForm):
    
    class Meta:
        model = Transaction
        fields = ("__all__")
