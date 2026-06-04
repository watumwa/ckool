# Bayan Learning Center Requirements Implementation

This package implements the client-requested payment-system improvements without replacing or resetting the existing school database.

## Implemented safely

1. **Transaction-level ledger export**
   - Existing summary reports remain unchanged.
   - A separate Transaction Ledger page/export shows one row per charge or payment transaction.
   - Excel columns include Date, Student ID, Student Name, Classroom, Term, Category, Payment Method, Amount Charged, Amount Paid, and Notes.

2. **Term association**
   - Payments are reported under the term of the bill/charge they settle, not merely by the payment date.

3. **Ledger filters**
   - Filters are available for student, academic year, term, classroom code/group, date range, category, and payment method.
   - Supported categories: Tuition, Transport, Uniform, Other.
   - Supported payment methods: Cash, SchoolPay, Bank, Other.

4. **Student record preservation**
   - Student deletion is replaced with activation/deactivation in the UI.
   - Admin deletion is disabled to protect historical payment and academic data.
   - Inactive learners remain available in reports/history.

5. **6-digit Student ID**
   - Added `student_number`, a client-facing 6-digit numeric ID.
   - Existing internal database IDs and `reg_no` values are not changed.
   - Existing learners are backfilled starting at 100001.
   - New learners automatically receive a 6-digit ID if one is not provided.

6. **Help/tutorial support**
   - The fees help page explains ledger export, summaries, filters, and student active/inactive status.

7. **Balance carry-forward**
   - Added a Carry Forward Balances workflow for Admin/Bursar/Finance users.
   - The page previews previous-term arrears before posting.
   - Posting creates a negative adjustment on the old bill and a matching Balance Brought Forward charge on the target term bill.
   - Running the workflow again updates existing carry-forward rows instead of duplicating them.

## Deployment safety rules

- Do not run `flush`.
- Do not replace the live database.
- Do not delete old migrations.
- Back up the live database before running migrations.
- Test this package on staging before live deployment.

## Deployment commands

```bash
python manage.py check --settings=core.settings.production
python manage.py migrate --settings=core.settings.production
python manage.py collectstatic --noinput --settings=core.settings.production
mkdir -p tmp
touch tmp/restart.txt
```

If any old learner remains without a student number after deployment, run:

```bash
python manage.py backfill_student_numbers --settings=core.settings.production
```

## Files changed

- `app/models/students.py`
- `app/migrations/0103_student_number_backfill.py`
- `app/management/commands/backfill_student_numbers.py`
- `app/services/fees_ledger.py`
- `app/services/fees_carry_forward.py`
- `app/views/fees_view.py`
- `app/views/student.py`
- `app/views/ux.py`
- `app/views/index_views.py`
- `app/forms/student.py`
- finance/student/fees templates using Student ID labels
- `templates/fees/carry_forward_balances.html`
- `templates/fees/help.html`
