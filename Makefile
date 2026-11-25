# Developer shortcuts. Run `make help`.
PY ?= python3
# Local-only value (>= 32 characters is required by backend/app/auth.py). Never use it in production.
SECRET ?= local-dev-secret-change-me-at-least-32-chars
UNIT_ENV = PYTHONPATH=backend DATABASE_URL=sqlite:////tmp/nuqati_unit.db NUQATI_AUTH_SECRET=$(SECRET)

.DEFAULT_GOAL := help
.PHONY: help install up down test test-pg hygiene lint web

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-9s %s\n", $$1, $$2}'

install: ## Install backend runtime + test dependencies into the active virtualenv
	$(PY) -m pip install -r backend/requirements-test.txt

# NOTE: plain `docker compose up` would pick compose.yml (the PRODUCTION file) because Compose
# prefers that name. Always name the local file explicitly.
up: ## Start PostgreSQL + API locally (http://127.0.0.1:8000, interactive docs at /docs)
	docker compose -f docker-compose.yml up --build

down: ## Stop the local stack (the database volume is kept)
	docker compose -f docker-compose.yml down

test: ## Backend unit/contract/layout tests (SQLite, no server needed)
	$(UNIT_ENV) $(PY) -m pytest -q --ignore=backend/test_auth_runtime_postgres.py --ignore=backend/test_security_audit_postgres.py --ignore=backend/test_concept_reports.py backend
	$(UNIT_ENV) $(PY) -m unittest backend.test_concept_reports

test-pg: ## API integration tests; needs NUQATI_TEST_DATABASE_URL (a DISPOSABLE db whose name contains "test")
	@test -n "$$NUQATI_TEST_DATABASE_URL" || { echo "Set NUQATI_TEST_DATABASE_URL, e.g. postgresql+psycopg2://user:pass@localhost:5432/nuqati_test"; exit 1; }
	PYTHONPATH=backend NUQATI_AUTH_SECRET=$(SECRET) $(PY) -m pytest -q backend/test_auth_runtime_postgres.py backend/test_security_audit_postgres.py

hygiene: ## Fast repository-layout checks only
	$(UNIT_ENV) $(PY) -m pytest -q backend/test_repo_hygiene.py

lint: ## Ruff on the backend (needs: pip install ruff)
	ruff check backend

web: ## Install, type-check and build the dashboard
	cd web && npm install --no-audit --no-fund && npm run build
