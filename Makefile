# Versnq Core — developer commands. Run `make help`.
SHELL := /bin/bash
export PATH := $(HOME)/.local/bin:$(PATH)
UV := cd backend && uv run --env-file ../.env

.PHONY: help setup up down dev worker migrate test lint secrets-scan create-staff openapi fe-setup fe-dev admin-dev fe-check

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

lint: ## Check code style and common bugs
	cd backend && uv run ruff check . && uv run ruff format --check .

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
