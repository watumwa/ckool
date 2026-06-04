# Professional Receipts Workflow

## Key rule
The system must not treat a bill statement as an official receipt.

A professional school fees module should separate:

1. **Official Payment Receipt**
   - Printed for one actual payment transaction.
   - Shows receipt number / payment reference.
   - Shows amount received, method, cashier/recorded by, date, and balance after payment.
   - Used by parent/student as proof of payment.

2. **Fees Account Statement**
   - Shows the whole bill, all payments, carried-forward balances, credits, and outstanding balance.
   - Used by bursar/admin to explain the learner's full financial position.
   - Not the same as proof that a specific payment was made.

## What was added

- New route: `/payment-receipt/<payment_id>/`
- New URL name: `student_payment_receipt`
- New template: `templates/fees/payment_receipt.html`
- Payment rows now include a **Receipt** button.
- After recording a payment through the standard bill page or quick payment page, the user is redirected to the official receipt page.
- The bill details print button is now a **Print Statement** action instead of pretending to be a receipt.
- The old all-years PDF is relabelled as a **Fees Account Statement**.

## Recommended receipt control

For stronger financial control later, add these enhancements:

- A `ReceiptSequence` model for strict serial receipt numbers per financial year.
- A `printed_count` field on payments.
- A `printed_by` and `last_printed_at` audit trail.
- A “Reprint” watermark after the first print.
- A void/reversal workflow instead of deleting payments.
- A daily cashier receipt summary that reconciles cash, bank, SchoolPay, and mobile money.

## Carry-forward balances on receipts

Previous-term balances should appear on statements and bills as a separate item:

`Balance Brought Forward - Term X`

Receipts should then show that the payment has reduced the total bill position, while the statement still explains where the debt came from.
