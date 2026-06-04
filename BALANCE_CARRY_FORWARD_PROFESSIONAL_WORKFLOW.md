# Professional Handling of Previous-Term Balances

## Recommended principle
Previous-term balances should not be hidden, edited away, or mixed silently into the new term's normal school fees. They should be moved into the new term as a clearly labelled arrears line called **Balance Brought Forward**, while keeping an auditable adjustment on the old bill.

## Correct workflow
1. Close or finish the source term.
2. Make sure the target term and class setup exists.
3. Open **Fees → Carry Forward Balances**.
4. Select the source term, target term, class scope, and active/inactive learner scope.
5. Preview all learners with unpaid balances.
6. Confirm the preview.
7. Post the carry-forward balances.
8. Review the current term fees status and ledger.

## Accounting treatment implemented in this project
When posted, the system creates:

- A negative adjustment on the old bill so the old term is not still shown as actively unpaid.
- A matching positive charge on the new term bill named **Balance Brought Forward**.
- Marker notes linking the source bill and target bill, making the posting auditable.

This means:

- Old term records remain traceable.
- New term total reflects both current fees and arrears.
- Parents can see what belongs to the new term and what came from a previous term.
- The bursar can report previous balances separately from current term billing.

## Important controls
- Only Admin, Bursar, Head Teacher, or Finance roles should post balances.
- The system should preview before posting.
- The user must confirm before posting.
- Reposting the same balance should update the existing carry-forward row, not duplicate it.
- Skipped learners should be shown when the target class/term is not yet set up.

## Reporting recommendation
Reports should separate:

- Opening balance / Balance brought forward
- Current term charges
- Payments received
- Closing balance

A professional statement should look like this:

Opening balance: UGX 200,000
Current term fees: UGX 800,000
Total due: UGX 1,000,000
Payments: UGX 600,000
Closing balance: UGX 400,000
