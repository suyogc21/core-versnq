# Phase 0 — Project Setup Implementation Plan

> **Execution:** inline in this session, task by task (see CLAUDE.md "Project skills"). Steps use checkbox (`- [ ]`) syntax. Tick each roadmap item in `docs/plans/ROADMAP.md` only after its tests pass.

**Goal:** A clean clone of the repo starts Postgres + Redis, runs the backend and worker, and runs a green test suite against real Postgres — with one command each.

**Architecture:** Postgres 16 and Redis 7 run in Docker Compose. The FastAPI backend and the arq worker run on the host through `uv` with a pinned Python 3.12. Tests use pytest against a separate `versnq_test` database in the same Postgres container.

**Tech Stack:** Python 3.12 · uv · FastAPI · uvicorn · pydantic-settings · SQLAlchemy 2.0 (async) + asyncpg · Alembic · redis-py · arq · pytest + pytest-asyncio + httpx · ruff · Docker Compose (postgres:16-alpine, redis:7-alpine) · gitleaks (run via Docker image, not installed)

**Spec:** `docs/specs/Versnq Core — Product & Feature Spec (v0).md` + `CLAUDE.md` (tech stack, secrets rule) + `docs/plans/ROADMAP.md` Phase 0.

## Global Constraints

- PostgreSQL only — dev and tests. No SQLite anywhere.
- Python 3.12, pinned in `.python-version` and `pyproject.toml` (`requires-python = ">=3.12,<3.13"`).
- Secrets come from environment variables only. `.env` is git-ignored; `.env.example` lists every variable with a safe placeholder.
- Dependencies: only those in Tech Stack above (approved with this plan). Any other dependency needs approval.
- Host ports: Postgres **5433**, Redis **6380** (avoids clashing with other local projects such as AMS on 5432/6379).
- Databases: `versnq` (dev), `versnq_test` (tests). DB user `versnq`.

## Review Focus

1. Tests pointed at the dev database by mistake would wipe dev data → the test harness refuses to run unless the database name ends in `_test` (Task 2).
2. A missing or misspelt env variable → the app fails at startup with an error naming the variable, not a stack trace later (Task 2).
3. Redis or Postgres down → `/health` answers **503** with which dependency failed, within 3 seconds, never hangs or 500s (Task 4).
4. A migration that upgrades but cannot downgrade → caught by an upgrade → downgrade → upgrade test (Task 3).
5. Ports already in use on the Mac → compose uses 5433/6380 and `make up` prints a clear message if the port is taken (Task 1).

---

### Task 1: Tooling, Docker services, env and Makefile

Roadmap: 0.2, 0.3, 0.4, 0.9 (first half), 0.10

**Files:**
- Create: `.python-version` (`3.12`), `backend/pyproject.toml`, `docker-compose.yml`, `docker/postgres/init/01-test-db.sql`, `.env.example`, `Makefile`
- Create empty packages: `backend/app/{__init__,core/__init__,platform/__init__,modules/__init__,events/__init__,workers/__init__}.py`, `backend/tests/__init__.py`

- [x] **Step 1:** Install uv (done via a user-local venv at `~/.local/share/uv-tool`, linked to `~/.local/bin/uv`, because Homebrew belongs to another macOS user), then `uv python install 3.12`. Verify: `uv run --python 3.12 python -V` → `Python 3.12.x`.
- [x] **Step 2:** `docker-compose.yml`: services `postgres` (postgres:16-alpine, port `5433:5432`, volume `pgdata`, healthcheck `pg_isready`) and `redis` (redis:7-alpine, port `6380:6379`, healthcheck `redis-cli ping`). Init script creates database `versnq_test` owned by `versnq`.
- [x] **Step 3:** `.env.example` with: `ENVIRONMENT=dev`, `DATABASE_URL=postgresql+asyncpg://versnq:changeme@localhost:5433/versnq`, `TEST_DATABASE_URL=postgresql+asyncpg://versnq:changeme@localhost:5433/versnq_test`, `REDIS_URL=redis://localhost:6380/0`, `POSTGRES_PASSWORD=changeme`.
- [x] **Step 4:** `Makefile` targets: `help`, `setup` (copy `.env.example` → `.env` if missing, `uv sync`), `up`, `down`, `dev` (uvicorn reload), `worker`, `migrate`, `test`, `lint`, `secrets-scan`.
- [x] **Step 5 (verify):** `make setup && make up` then `docker compose ps` → both services `healthy`; `psql`-free check: `docker compose exec postgres psql -U versnq -lqt | cut -d'|' -f1 | grep -w versnq_test` → match.
- [x] **Step 6:** Commit `chore(setup): docker services, uv project, env example and makefile`.

### Task 2: Settings and test harness

Roadmap: 0.7 (part)

**Files:**
- Create: `backend/app/core/config.py`, `backend/tests/conftest.py`, `backend/tests/core/test_config.py`

**Interfaces:**
- Produces: `class Settings(BaseSettings)` with `environment: Literal["dev","test","prod"]`, `database_url: str`, `test_database_url: str`, `redis_url: str`; `get_settings() -> Settings` (cached). Fixture `settings` in conftest.

- [x] **Step 1: Failing tests** in `test_config.py`:
  - `test_settings_read_from_env` — monkeypatch the four vars → `get_settings()` returns them.
  - `test_missing_database_url_names_the_variable` — unset `DATABASE_URL` → `ValidationError` whose message contains `database_url`.
  - `test_harness_refuses_non_test_database` — call `assert_test_database("postgresql+asyncpg://u:p@h/versnq")` → raises `RuntimeError` containing `"_test"`.
- [x] **Step 2:** `cd backend && uv run pytest tests/core/test_config.py -v` → FAIL (module missing).
- [x] **Step 3:** Implement `Settings`, `get_settings()`, and `assert_test_database(url: str) -> None` (in `conftest.py`, called at session start before any DB work).
- [x] **Step 4:** Same command → 3 PASS.
- [x] **Step 5:** Commit `feat(core): env-based settings and test database guard`.

### Task 3: Database engine and Alembic baseline

Roadmap: 0.6

**Files:**
- Create: `backend/app/core/db.py`, `backend/alembic.ini`, `backend/migrations/env.py` (async), `backend/migrations/versions/0001_baseline.py` (empty), `backend/tests/core/test_migrations.py`

**Interfaces:**
- Produces: `engine: AsyncEngine`, `async def get_session() -> AsyncIterator[AsyncSession]` (FastAPI dependency), `class Base(DeclarativeBase)`. Migrations read the URL from `Settings`, never from `alembic.ini`.

- [x] **Step 1: Failing test** `test_upgrade_downgrade_upgrade` — runs `alembic upgrade head`, `downgrade base`, `upgrade head` against `TEST_DATABASE_URL`; asserts `alembic_version` holds `0001`.
- [x] **Step 2:** Run → FAIL.
- [x] **Step 3:** Implement `db.py`, async `env.py`, baseline revision `0001` (no tables).
- [x] **Step 4:** Run → PASS. Also `make migrate` on dev DB succeeds.
- [x] **Step 5:** Commit `feat(core): async database engine and alembic baseline`.

### Task 4: FastAPI app and `/health`

Roadmap: 0.5

**Files:**
- Create: `backend/app/main.py`, `backend/app/core/health.py`, `backend/tests/core/test_health.py`

**Interfaces:**
- Consumes: `get_session`, `get_settings`.
- Produces: `app: FastAPI` (in `app.main`); `GET /health` → `200 {"status":"ok","db":"ok","redis":"ok"}` or `503 {"status":"degraded","db":"ok|down","redis":"ok|down"}`. Each check times out after 2 s.

- [x] **Step 1: Failing tests** (httpx `AsyncClient` on `app`):
  - `test_health_ok` → 200, body exactly as above.
  - `test_health_db_down` → override DB check to raise → 503, `db == "down"`, `redis == "ok"`.
  - `test_health_redis_down` → point Redis at an unused port → 503, `redis == "down"`, response time < 3 s.
- [x] **Step 2:** Run → FAIL.
- [x] **Step 3:** Implement `main.py` and `health.py` (`SELECT 1` and Redis `PING`, each wrapped in `asyncio.wait_for(..., 2)`).
- [x] **Step 4:** Run → 3 PASS. Manual: `make dev`, open `http://localhost:8000/health` and `/docs`.
- [x] **Step 5:** Commit `feat(core): fastapi app with db and redis health check`.

### Task 5: Worker skeleton

Roadmap: 0.8

**Files:**
- Create: `backend/app/workers/main.py`, `backend/app/workers/jobs.py`, `backend/tests/workers/test_ping_job.py`

**Interfaces:**
- Produces: `async def ping_job(ctx: dict) -> str` returning `"pong"`; `class WorkerSettings` (arq) with `functions = [ping_job]`, `redis_settings` from `Settings.redis_url`.

- [x] **Step 1: Failing test** `test_ping_job_runs_through_queue` — enqueue `ping_job` on Redis DB 15, run an arq worker in burst mode, assert job result `== "pong"`.
- [x] **Step 2:** Run → FAIL.
- [x] **Step 3:** Implement `jobs.py` and `main.py`.
- [x] **Step 4:** Run → PASS. Manual: `make worker` starts and logs the registered function.
- [x] **Step 5:** Commit `feat(workers): arq worker skeleton with ping job`.

### Task 6: Lint, secret scan and clean-clone check

Roadmap: 0.9 (second half), Gate 0

**Files:**
- Modify: `backend/pyproject.toml` (ruff config: line length 100, rules `E,F,I,B,UP`), `Makefile` (`lint`, `secrets-scan` via `docker run --rm -v "$PWD":/repo zricethezav/gitleaks:latest detect --source /repo --no-banner`)

- [x] **Step 1:** `make lint` → no findings (fix any).
- [x] **Step 2:** `make secrets-scan` → `no leaks found`.
- [x] **Step 3 (clean-clone test):** `git clone . <scratch>/core-clone && cd <scratch>/core-clone && make setup && make test` → all tests pass (uses the running containers).
- [x] **Step 4:** Tick roadmap 0.2–0.10, log in Progress table, commit `chore(setup): lint, secret scan; phase 0 complete`.
- [ ] **Step 5 (Gate 0):** Show Suyog the results; wait for approval before Phase 1.
