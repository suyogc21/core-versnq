#!/bin/sh
# Starts a throwaway API for the end-to-end test: fresh versnq_e2e database, its own Redis
# database and a file outbox, on port 8100. Never touches the dev or test databases.
set -e
ROOT=$(cd "$(dirname "$0")/.." && pwd)
export PATH="$HOME/.local/bin:$PATH"
set -a; . "$ROOT/.env"; set +a

export DATABASE_URL="${DATABASE_URL%/*}/versnq_e2e"
export MIGRATION_DATABASE_URL="${MIGRATION_DATABASE_URL%/*}/versnq_e2e"
export REDIS_URL="${REDIS_URL%/*}/13"
export MAIL_OUTBOX_DIR="$ROOT/frontend/e2e/.state/outbox"
export ENVIRONMENT=dev
export TRUST_PROXY_HEADERS=true
export DEMO_SKIP_2FA=false  # the end-to-end test checks the real 2FA flow
case "$MIGRATION_DATABASE_URL" in *"/versnq_e2e") ;; *) echo "refusing: not versnq_e2e"; exit 1;; esac

rm -rf "$MAIL_OUTBOX_DIR" && mkdir -p "$MAIL_OUTBOX_DIR"
cd "$ROOT/backend"
uv run alembic downgrade base >/dev/null
uv run alembic upgrade head >/dev/null
uv run python - <<'PY'
import asyncio, os
import redis
from app.platform.cli import _create_staff
redis.Redis.from_url(os.environ["REDIS_URL"]).flushdb()
asyncio.run(_create_staff("e2e-staff@versnq.in", "E2E Staff", os.environ["E2E_STAFF_PASSWORD"]))
PY
exec uv run uvicorn app.main:app --port 8100
