#!/bin/sh
set -eu

APP_PORT="${PORT:-5000}"

exec gunicorn app:app \
    --workers="${WEB_CONCURRENCY:-1}" \
    --threads="${GUNICORN_THREADS:-2}" \
    --timeout="${GUNICORN_TIMEOUT:-120}" \
    --bind="0.0.0.0:${APP_PORT}" \
    --log-level="${GUNICORN_LOG_LEVEL:-info}" \
    --access-logfile=-
