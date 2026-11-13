# Versnq Core — developer commands. Run `make help`.
SHELL := /bin/bash
export PATH := $(HOME)/.local/bin:$(PATH)
UV := cd backend && uv run --env-file ../.env

.PHONY: help setup up down dev worker migrate test lint requirements secrets-scan create-staff openapi fe-setup fe-dev admin-dev fe-check demo-seed demo-reset e2e-db e2e

help: ## List commands
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-14s %s\n", $$1, $$2}'

setup: ## Create .env from the example (if missing) and install dependencies
	@test -f .env || cp .env.example .env
	cd backend && uv sync

up: ## Start Postgres and Redis; fails clearly if a port is taken
	@for p in 5433 6380; do \
	  if lsof -iTCP:$$p -sTCP:LISTEN -n -P -Fc 2>/dev/null | grep '^c' | grep -qvi docker; then \
	    echo "Port $$p is already used by another program. Free it or change docker-compose.yml."; exit 1; fi; done
	docker compose up -d --wait

down: ## Stop Postgres and Redis (data is kept)
	docker compose down

dev: ## Run the API with auto-reload on http://localhost:8000
	$(UV) uvicorn app.main:app --reload

worker: ## Run the background worker
	$(UV) arq app.workers.main.WorkerSettings

migrate: ## Apply database migrations to the dev database
	$(UV) alembic upgrade head

test: ## Run the test suite against the versnq_test database
	$(UV) pytest

lint: ## Check code style and common bugs (and that the production requirements match uv.lock)
	cd backend && uv run ruff check . && uv run ruff format --check .
	cd backend && uv export --frozen --no-dev --no-emit-project --format requirements-txt --no-header --quiet | diff -q - requirements.lock.txt >/dev/null || { echo 'requirements.lock.txt is out of date: run make requirements'; exit 1; }

requirements: ## Export backend/requirements.lock.txt from uv.lock (the production image installs it)
	cd backend && uv export --frozen --no-dev --no-emit-project --format requirements-txt --no-header -o requirements.lock.txt --quiet

secrets-scan: ## Scan the repository for committed secrets
	docker run --rm -v "$(CURDIR)":/repo zricethezav/gitleaks:latest detect --source /repo --no-banner

create-staff: ## Create a Versnq staff (platform admin) account
	$(UV) python -m app.platform.cli create-staff

openapi: ## Write the API spec to docs/api/openapi.json (commit it with API changes)
	@mkdir -p docs/api
	$(UV) python -c "import json; from app.main import app; print(json.dumps(app.openapi(), indent=2, sort_keys=True))" > $(CURDIR)/docs/api/openapi.json

fe-setup: ## Install frontend dependencies (client app + staff console)
	cd frontend && npm ci
	cd frontend-admin && npm ci

fe-dev: ## Run the client app on http://<slug>.localhost:3000
	cd frontend && npm run dev

admin-dev: ## Run the staff console on http://admincore.localhost:3001
	cd frontend-admin && npm run dev

fe-check: ## Typecheck, lint and verify the API client is up to date (both apps)
	@for app in frontend frontend-admin; do \
	  (cd $$app && npm run -s gen:api >/dev/null && git diff --quiet -- lib/api/schema.d.ts \
	    || { echo "$$app: API client out of date - run 'make openapi' then 'npm run gen:api'"; exit 1; }) || exit 1; \
	  (cd $$app && npm run -s typecheck && npm run -s lint) || exit 1; \
	done
	@echo "frontend checks passed"

extension: ## Build the WhatsApp Chrome extension into extension/dist (load it in chrome://extensions)
	cd extension && ../frontend/node_modules/.bin/tsc -p . && cp manifest.json src/panel.html dist/

.PHONY: extension

demo-seed: ## Add the demo companies (dev only; prints the shared password once)
	$(UV) python -m app.platform.demo

demo-reset: ## Wipe the dev database, rebuild it, then add fresh demo companies (dev only)
	$(UV) python -m app.platform.demo --reset

e2e-db: ## Create the end-to-end test database on an existing Postgres volume (once)
	./scripts/e2e-db.sh

e2e: ## Gate 1 browser test: own API, database and app builds; never touches dev data
	cd frontend && npx playwright test
