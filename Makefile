# Python 3.12 matches the Docker image; 3.13 is accepted where 3.12 is not installed.
PYTHON ?= $(shell command -v python3.12 || command -v python3.13 || echo python3)
VENV := .venv
BIN := $(VENV)/bin
PY_SRC := backend/src backend/tests backend/scripts sdk/src sdk/tests demo-app/src demo-app/tests scripts

.DEFAULT_GOAL := help

.PHONY: help
help: ## List targets
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

$(BIN)/python:
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install --upgrade pip

.PHONY: install
install: $(BIN)/python ## Install Python packages (editable) and web dependencies
	$(BIN)/pip install -e "sdk[fastapi]" -e "backend[dev]" -e demo-app
	cd web && pnpm install --frozen-lockfile
	@test -f .env || cp .env.example .env
	@test -f web/.env.local || cp web/.env.example web/.env.local

.PHONY: services
services: ## Start local Postgres (5506) and Redis (6406) without Docker
	./scripts/services.sh up

.PHONY: services-down
services-down: ## Stop local Postgres and Redis
	./scripts/services.sh down

.PHONY: migrate
migrate: ## Apply database migrations
	cd backend && ../$(BIN)/alembic upgrade head

.PHONY: seed
seed: ## Rebuild demo stores, tuples, the Workspaces dataset and a day of decisions
	$(BIN)/python scripts/seed.py --reset

.PHONY: api
api: ## Run the Warden API on :8106
	$(BIN)/warden

.PHONY: demo
demo: ## Run the Workspaces demo API on :27106
	$(BIN)/python -m workspaces

.PHONY: web
web: ## Run the console on :3106
	cd web && pnpm dev

.PHONY: dev
dev: ## Run API, demo app and console together
	@trap 'kill 0' INT TERM EXIT; \
	$(MAKE) --no-print-directory api & \
	$(MAKE) --no-print-directory demo & \
	$(MAKE) --no-print-directory web & \
	wait

.PHONY: test
test: test-py test-web ## Run every test suite

.PHONY: test-py
test-py: ## Python tests (integration tests need Postgres on 5506)
	cd backend && ../$(BIN)/pytest -q
	cd sdk && ../$(BIN)/pytest -q
	cd demo-app && ../$(BIN)/pytest -q

.PHONY: test-web
test-web:
	cd web && pnpm test

.PHONY: lint
lint: ## Ruff and ESLint
	$(BIN)/ruff check .
	$(BIN)/ruff format --check .
	cd web && pnpm lint

.PHONY: typecheck
typecheck: ## mypy --strict and tsc
	$(BIN)/mypy $(PY_SRC)
	cd web && pnpm typecheck

.PHONY: format
format: ## Apply ruff formatting and autofixes
	$(BIN)/ruff check --fix .
	$(BIN)/ruff format .

.PHONY: check
check: lint typecheck test ## Lint, typecheck and every test suite

.PHONY: build
build: ## Production build of the console
	cd web && pnpm build

.PHONY: bench
bench: ## Benchmark check/list throughput on a synthetic store
	$(BIN)/python backend/scripts/bench.py

.PHONY: up
up: ## Run the whole stack with Docker Compose
	docker compose up --build

.PHONY: clean
clean: ## Remove caches and build output
	rm -rf .mypy_cache .ruff_cache backend/.hypothesis web/.next web/public/monaco
	find backend sdk demo-app -name .pytest_cache -prune -exec rm -rf {} +
