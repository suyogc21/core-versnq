#!/bin/sh
# The API brings the database up to date before it starts; the worker just starts.
set -e
if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
  alembic upgrade head
fi
exec "$@"
