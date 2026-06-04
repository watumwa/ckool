from app.models.finance import *

def get_expenditure_items(expenditure):
    return ExpenditureItem.objects.filter(expenditure=expenditure)

def get_budget_items(budget):
    return BudgetItem.objects.filter(budget=budget)
