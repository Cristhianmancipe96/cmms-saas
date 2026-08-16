#!/bin/sh
# Container entrypoint: migrate, then serve. Brief 11.
#
# `set -e` is the whole point of migrating here rather than in a start command:
# if a migration fails the container exits instead of starting a web server on
# top of a half-migrated database.
set -e

echo "Aplicando migraciones..."
python manage.py migrate --noinput

# --access-logfile - and --error-logfile - send gunicorn's own logs to stdout,
# where Django's logging already writes (config/settings.py). The platform's
# log viewer is the only place any of this is visible.
#
# The timeout is generous on purpose: rendering a work-order PDF with photos
# takes seconds, and gunicorn kills a worker that has not answered in time.
echo "Iniciando gunicorn en el puerto ${PORT:-8000}..."
exec gunicorn config.wsgi:application \
    --bind "0.0.0.0:${PORT:-8000}" \
    --workers "${WEB_CONCURRENCY:-3}" \
    --timeout "${GUNICORN_TIMEOUT:-120}" \
    --access-logfile - \
    --error-logfile - \
    "$@"
