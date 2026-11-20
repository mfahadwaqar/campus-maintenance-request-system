#!/bin/sh
# Start command for Render (free plan). Runs on every start, and every step is safe to repeat.
set -e

python manage.py migrate --noinput
python manage.py collectstatic --noinput
python manage.py seed_reference_data
python manage.py seed_campus_reference_data

# Admin account: only if the three DJANGO_SUPERUSER_* variables are set. Already existing is fine.
if [ -n "$DJANGO_SUPERUSER_USERNAME" ] && [ -n "$DJANGO_SUPERUSER_PASSWORD" ]; then
    python manage.py createsuperuser --noinput || echo "Admin account already exists."
fi

# Presentation accounts: only if a password is set.
if [ -n "$PRESENTATION_USER_PASSWORD" ]; then
    python manage.py seed_presentation_accounts
fi

# Optional demo tickets and accounts (needs DEMO_USER_PASSWORD).
if [ -n "$DEMO_USER_PASSWORD" ]; then
    python manage.py seed_demo_data || echo "Demo data was already loaded."
fi

exec gunicorn campus_maintainance_request_system.wsgi:application \
    --bind "0.0.0.0:${PORT:-8000}" \
    --workers "${WEB_CONCURRENCY:-2}" \
    --timeout 60
