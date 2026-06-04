from django.db import models
from django.urls import reverse
from app.constants import MEASUREMENTS,PAYMENT_STATUS

class BankAccount(models.Model):
    bank_name = models.CharField(max_length=100)
    account_number = models.CharField(max_length=50, unique=True)
    account_name = models.CharField(max_length=100)
    account_type = models.CharField(max_length=50)
    balance = models.IntegerField()

    def __str__(self):
        return f'{self.account_name} - {self.bank_name}'

class Vendor(models.Model):
    name = models.CharField(max_length=100)
    contact = models.CharField(max_length=255)
    address = models.CharField(max_length=255)
    email = models.EmailField(blank=True, null=True)

    def __str__(self):
        return self.name
    
class Expense(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.name
class Budget(models.Model):
    academic_year = models.ForeignKey("app.AcademicYear", on_delete=models.CASCADE)
    term = models.ForeignKey("app.Term", on_delete=models.CASCADE)
    status = models.CharField(max_length=10, choices=[("Open", "Open"), ("Closed", "Closed")])

    class Meta:
        verbose_name = ("budget")
        verbose_name_plural = ("budgets")
        unique_together = ("academic_year", "term")
        ordering = ("-id",)

    def __str__(self):
        return f"Budget for {self.academic_year} - {self.term}"

    def get_absolute_url(self):
        return reverse("budget_detail", kwargs={"pk": self.pk})

    @property
    def budget_total(self):
        """Calculate the budget total by summing related items."""
        total = sum(item.allocated_amount for item in self.budget_items.all())
        return round(total, 2)


class BudgetItem(models.Model):
    budget = models.ForeignKey("app.Budget", on_delete=models.CASCADE, related_name="budget_items")
    department = models.ForeignKey("app.Department", on_delete=models.CASCADE, related_name='budgets')
    expense = models.ForeignKey("app.Expense", on_delete=models.CASCADE, related_name='budgets')
    allocated_amount = models.IntegerField()

    class Meta:
        unique_together = ('budget', 'department', 'expense')

    @property
    def amount_spent(self):
        budget_expenditures = self.budget_expenditures.all()
        total = sum(item.amount for item in budget_expenditures)
        
        return total or 0

    @property
    def remaining_amount(self):
        return self.allocated_amount - self.amount_spent

    def __str__(self):
        return f'{self.department} - {self.expense}'

class Expenditure(models.Model):
    budget_item = models.ForeignKey("app.BudgetItem", on_delete=models.CASCADE, related_name='budget_expenditures')
    vendor = models.ForeignKey("app.Vendor", on_delete=models.SET_NULL, null=True, blank=True, related_name='expenses')
    description = models.TextField()
    vat = models.DecimalField(max_digits=10, decimal_places=2)
    date_incurred = models.DateField()
    date_recorded = models.DateField(auto_now_add=True)
    approved_by = models.CharField(max_length=100, null=True, blank=True,)
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS, default='Pending')
    attachment = models.FileField(upload_to='attachments/', blank=True, null=True)
    
    def __str__(self):
        return f'{self.description} '
    
    @property
    def amount(self):
        items = self.items.all()
        total = sum(item.amount for item in items)
        
        return total + self.vat
        

class ExpenditureItem(models.Model):
    
    expenditure = models.ForeignKey("app.Expenditure", on_delete=models.CASCADE, related_name="items")
    item_name = models.CharField(max_length=100)
    quantity = models.DecimalField(max_digits=5, decimal_places=2)
    units = models.CharField(max_length=50, choices=MEASUREMENTS)
    unit_cost = models.IntegerField()

    class Meta:
        verbose_name = ("expenditureitem")
        verbose_name_plural = ("expenditureitems")

    def __str__(self):
        return self.item_name
    
    @property
    def amount(self):
        return self.quantity * self.unit_cost

    def get_absolute_url(self):
        return reverse("expenditureitem_detail", kwargs={"pk": self.pk})


class IncomeSource(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.name

class Transaction(models.Model):
    TRANSACTION_TYPE_CHOICES = [
        ('Income', 'Income'),
        ('Expense', 'Expense')
    ]
    date = models.DateField()
    transaction_type = models.CharField(max_length=10, choices=TRANSACTION_TYPE_CHOICES)
    description = models.TextField()
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    
    related_income_source = models.ForeignKey("app.IncomeSource", on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return f'{self.transaction_type} - {self.description} - {self.amount}'

    @property
    def is_income(self):
        return self.transaction_type == 'Income'

    @property
    def is_expense(self):
        return self.transaction_type == 'Expense'

class BankStatement(models.Model):
    bank_account = models.ForeignKey(BankAccount, on_delete=models.CASCADE, related_name='statements')
    statement_date = models.DateField()
    opening_balance = models.DecimalField(max_digits=15, decimal_places=2)
    closing_balance = models.DecimalField(max_digits=15, decimal_places=2)
    uploaded_by = models.ForeignKey('app.Staff', on_delete=models.SET_NULL, null=True)
    upload_date = models.DateTimeField(auto_now_add=True)
    file = models.FileField(upload_to='bank_statements/', blank=True, null=True)

    def __str__(self):
        return f'{self.bank_account} - {self.statement_date}'

class BankTransaction(models.Model):
    bank_statement = models.ForeignKey(BankStatement, on_delete=models.CASCADE, related_name='transactions')
    transaction_date = models.DateField()
    description = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    transaction_type = models.CharField(max_length=10, choices=[('Credit', 'Credit'), ('Debit', 'Debit')])
    reference = models.CharField(max_length=100, blank=True, null=True)
    reconciled = models.BooleanField(default=False)
    reconciled_with = models.ForeignKey('app.Payment', on_delete=models.SET_NULL, null=True, blank=True)
    reconciliation_date = models.DateTimeField(blank=True, null=True)
    notes = models.TextField(blank=True, null=True)

    def __str__(self):
        return f'{self.transaction_date} - {self.description} - {self.amount}'

class CashFlowStatement(models.Model):
    start_date = models.DateField()
    end_date = models.DateField()
    generated_on = models.DateField(auto_now_add=True)

    @property
    def total_income(self):
        return Transaction.objects.filter(transaction_type='Income', date__range=(self.start_date, self.end_date)).aggregate(total=models.Sum('amount'))['total'] or 0

    @property
    def total_expenses(self):
        return Transaction.objects.filter(transaction_type='Expense', date__range=(self.start_date, self.end_date)).aggregate(total=models.Sum('amount'))['total'] or 0

    @property
    def net_cash_flow(self):
        return self.total_income - self.total_expenses

    def __str__(self):
        return f'Cash Flow Statement from {self.start_date} to {self.end_date}'

class FinancialNotification(models.Model):
    NOTIFICATION_TYPES = [
        ('payment_reminder', 'Payment Reminder'),
        ('overdue_notice', 'Overdue Notice'),
        ('fee_deadline', 'Fee Deadline'),
        ('budget_alert', 'Budget Alert'),
        ('expenditure_approval', 'Expenditure Approval Required'),
        ('bank_reconciliation', 'Bank Reconciliation Required'),
    ]

    recipient = models.ForeignKey('app.Student', on_delete=models.CASCADE, related_name='financial_notifications')
    notification_type = models.CharField(max_length=50, choices=NOTIFICATION_TYPES)
    title = models.CharField(max_length=255)
    message = models.TextField()
    sent_date = models.DateTimeField(auto_now_add=True)
    read_date = models.DateTimeField(blank=True, null=True)
    read = models.BooleanField(default=False)
    action_required = models.BooleanField(default=False)
    related_object_type = models.CharField(max_length=50, blank=True, null=True)  # e.g., 'StudentBill', 'Expenditure'
    related_object_id = models.IntegerField(blank=True, null=True)

    def __str__(self):
        return f'{self.notification_type} - {self.recipient} - {self.sent_date}'

class ApprovalWorkflow(models.Model):
    APPROVAL_STATUS = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('escalated', 'Escalated'),
    ]

    expenditure = models.OneToOneField(Expenditure, on_delete=models.CASCADE, related_name='approval_workflow')
    current_approver = models.ForeignKey('app.Staff', on_delete=models.SET_NULL, null=True, related_name='pending_approvals')
    approval_level = models.IntegerField(default=1)
    max_approval_level = models.IntegerField(default=2)
    status = models.CharField(max_length=20, choices=APPROVAL_STATUS, default='pending')
    created_date = models.DateTimeField(auto_now_add=True)
    approved_date = models.DateTimeField(blank=True, null=True)
    approved_by = models.ForeignKey('app.Staff', on_delete=models.SET_NULL, null=True, related_name='approved_expenditures')
    rejection_reason = models.TextField(blank=True, null=True)
    comments = models.TextField(blank=True, null=True)

    def __str__(self):
        return f'Approval for {self.expenditure} - Level {self.approval_level}'

class FinancialDashboard(models.Model):
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    dashboard_type = models.CharField(max_length=50, choices=[
        ('summary', 'Financial Summary'),
        ('collection', 'Fee Collection'),
        ('expenditure', 'Expenditure Analysis'),
        ('budget', 'Budget Performance'),
        ('forecast', 'Financial Forecast'),
    ])
    is_default = models.BooleanField(default=False)
    created_by = models.ForeignKey('app.Staff', on_delete=models.SET_NULL, null=True)
    created_date = models.DateTimeField(auto_now_add=True)
    config = models.JSONField(default=dict)  # Store dashboard configuration

    def __str__(self):
        return self.title

class FeeAutomationRule(models.Model):
    RULE_TYPES = [
        ('fee_update', 'Fee Structure Update'),
        ('discount_apply', 'Automatic Discount Application'),
        ('late_fee', 'Late Fee Assessment'),
        ('reminder_schedule', 'Reminder Schedule'),
    ]

    name = models.CharField(max_length=255)
    rule_type = models.CharField(max_length=50, choices=RULE_TYPES)
    is_active = models.BooleanField(default=True)
    conditions = models.JSONField()  # Store rule conditions
    actions = models.JSONField()  # Store rule actions
    execution_schedule = models.CharField(max_length=100, blank=True, null=True)  # Cron expression
    last_execution = models.DateTimeField(blank=True, null=True)
    next_execution = models.DateTimeField(blank=True, null=True)
    created_by = models.ForeignKey('app.Staff', on_delete=models.SET_NULL, null=True)
    created_date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.name} ({self.rule_type})'
    