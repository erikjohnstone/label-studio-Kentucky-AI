#!/bin/bash
# Kentucky AI web process: migrate, collect static files, serve with gunicorn on $PORT (Railway/Render/Fly set it).
set -euo pipefail
export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-core.settings.label_studio}"
cd "$(dirname "$0")/../../label_studio"
python manage.py migrate --noinput
python manage.py collectstatic --noinput >/dev/null
exec gunicorn core.wsgi:application --bind "0.0.0.0:${PORT:-8080}" --workers "${WEB_CONCURRENCY:-3}" --threads 4 \
  --timeout 300 --access-logfile - --forwarded-allow-ips '*'
