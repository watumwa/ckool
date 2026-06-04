# Deployment Checklist

Use this before replacing a live school system.

1. Backup the production database.
2. Backup the production `media/` folder.
3. Upload only the clean project files, not `.venv`, logs, local database files or temporary MySQL folders.
4. Copy `.env.example` to `.env` and fill in the real values.
5. Confirm `SECRET_KEY`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `ALLOWED_HOSTS`, and email settings.
6. Run:

```bash
python manage.py check --settings=core.settings.production
python manage.py migrate --settings=core.settings.production
python manage.py collectstatic --noinput --settings=core.settings.production
mkdir -p tmp
touch tmp/restart.txt
```

7. Restart the Python app in cPanel.
8. Test these pages:
   - `/`
   - `/operations/`
   - `/setup-checklist/`
   - `/fees/quick-payment/`
   - `/students/`
   - `/attendance/`
   - `/add_results/`
9. Create a test payment only after confirming database backup exists.
10. Rotate any secrets that were ever shared in chats, screenshots or ZIP files.
