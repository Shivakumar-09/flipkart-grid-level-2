#!/bin/sh
set -eu

APP_PORT="${PORT:-8080}"

exec gunicorn app:app -c gunicorn.conf.py
