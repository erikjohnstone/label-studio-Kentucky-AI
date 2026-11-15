#!/bin/bash
# Kentucky AI training orchestrator: claims queued jobs, supervises providers, bills always-on hosting.
set -euo pipefail
export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-core.settings.label_studio}"
cd "$(dirname "$0")/../../label_studio"
python manage.py migrate --noinput
exec python manage.py ka_worker
