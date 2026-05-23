# flowprov — convenience targets
# Use `make help` to list everything.

SHELL := /bin/bash
PYTHON ?= python3
VENV   ?= .venv
PIP     = $(VENV)/bin/pip
PY      = $(VENV)/bin/python

.DEFAULT_GOAL := help

.PHONY: help
help: ## Show this help
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

.PHONY: venv
venv: ## Create a Python 3.11+ virtualenv
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip wheel setuptools

.PHONY: install
install: venv ## Install all dependencies (incl. dev)
	$(PIP) install -e ".[dev]"

.PHONY: db-up
db-up: ## Start Postgres+pgvector via docker compose
	docker compose up -d postgres
	@echo "Waiting for Postgres to become ready..."
	@until docker compose exec -T postgres pg_isready -U flowprov -d flowprov >/dev/null 2>&1; do sleep 1; done
	@echo "✔ Postgres ready on localhost:5433"

.PHONY: db-down
db-down: ## Stop Postgres
	docker compose down

.PHONY: db-reset
db-reset: ## DESTROY and recreate the database volume
	docker compose down -v
	$(MAKE) db-up
	$(MAKE) migrate

.PHONY: migrate
migrate: ## Apply DB migrations
	$(VENV)/bin/alembic upgrade head

.PHONY: migration-new
migration-new: ## Create a new auto migration: make migration-new M="message"
	$(VENV)/bin/alembic revision --autogenerate -m "$(M)"

.PHONY: api
api: ## Run the FastAPI server (http://localhost:8000)
	$(VENV)/bin/uvicorn flowprov.api.app:app --host 0.0.0.0 --port 8000 --reload

.PHONY: demo
demo: ## Run the end-to-end demo (simulator → drift injection → replay)
	$(PY) -m examples.flow_simulator.run

.PHONY: demo-drift
demo-drift: ## Inject a prompt regression mid-run to trigger drift alerts
	$(PY) -m examples.flow_simulator.inject_drift

.PHONY: n8n-up
n8n-up: ## Start the optional n8n container (http://localhost:5678)
	docker compose --profile n8n up -d

.PHONY: n8n-down
n8n-down: ## Stop n8n
	docker compose --profile n8n down

.PHONY: test
test: ## Run unit tests
	$(VENV)/bin/pytest

.PHONY: lint
lint: ## Lint with ruff
	$(VENV)/bin/ruff check flowprov tests examples

.PHONY: format
format: ## Format with ruff
	$(VENV)/bin/ruff format flowprov tests examples

.PHONY: clean
clean: ## Remove caches and build artifacts
	rm -rf build/ dist/ *.egg-info .pytest_cache .ruff_cache .mypy_cache
	find . -type d -name __pycache__ -exec rm -rf {} +
