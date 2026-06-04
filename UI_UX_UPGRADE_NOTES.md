# UI/UX Upgrade Notes

This upgrade adds a safe, production-focused interface layer to the Django School MIS without changing business logic, models, URLs, migrations, or database behavior.

## What changed

- Added `static/css/senior_ui.css`
  - Professional dark-blue design system
  - Better typography, spacing, cards, buttons, forms, alerts, badges, tables, modals, dashboards, mobile behavior, print safety, and accessibility focus states
- Added `static/js/senior_ui.js`
  - Active sidebar state detection
  - Automatic responsive table wrapping
  - Submit-button loading feedback
  - Destructive-action confirmation for delete/remove/trash actions
  - Accessibility labels for icon-only actions
- Updated `templates/base.html`
  - Loads the new design system CSS and JS
  - Adds a keyboard-accessible “Skip to main content” link
  - Uses a semantic `<main>` landmark around page content
- Improved `templates/includes/scripts.html`
  - Stronger default DataTables configuration
  - Search placeholder, pagination text, responsive mode, fixed headers, and export buttons for Copy/CSV/Excel/Print
- Improved `templates/accounts/login.html`
  - Modern premium login screen
  - Better spacing, contrast, mobile responsiveness, focus states, and stronger visual hierarchy

## Deployment notes

1. Upload the changed project files.
2. Run Django collectstatic if your hosting uses collected static files:

   ```bash
   python manage.py collectstatic --noinput
   ```

3. Restart the app/server if required by your hosting panel.
4. Clear browser cache or test in a private window.

## Safety

The upgrade is intentionally a shared UI layer. It avoids touching core models, views, migrations, and data logic so existing school data should remain safe.
