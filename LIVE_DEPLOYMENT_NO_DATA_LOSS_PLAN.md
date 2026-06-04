# Live Deployment Plan Without Data Loss

Use this when the school is already using the system.

## 1. Before deployment

1. Put the current code aside as a rollback copy.
2. Export the live database from cPanel/phpMyAdmin or with `mysqldump`.
3. Back up uploaded media files.
4. Deploy to staging first and test using a copy of the live database.

## 2. What this deployment does NOT do

- It does not erase learners.
- It does not erase payments.
- It does not change existing database primary keys.
- It does not replace existing fee summaries.
- It does not force the school to stop using old reports immediately.

## 3. What the migration does

The new migration adds a nullable unique `student_number` field and fills it for existing students. It keeps existing `reg_no` values untouched so older result imports, receipts, and references continue working.

## 4. Post-deployment checks

After migration, confirm:

- Student list opens.
- Existing payments still appear.
- Payment ledger opens.
- Excel ledger exports correctly.
- A known student has a 6-digit Student ID.
- Deactivate/reactivate works.
- Quick payment still records payments.
- Reports still show balances correctly.

## 5. Rollback guidance

If a problem appears, restore the previous code immediately and restore the database backup only if the migration caused an actual database issue. Do not panic-delete records.
