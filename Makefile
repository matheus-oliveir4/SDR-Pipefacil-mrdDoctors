PYTHON := .venv/bin/python
PIP := .venv/bin/pip
RUFF := .venv/bin/ruff
PYTEST := .venv/bin/pytest
UVICORN := .venv/bin/uvicorn
LANGGRAPH := .venv/bin/langgraph
PRE_COMMIT := .venv/bin/pre-commit
DOCKER_COMPOSE ?= $(shell docker compose version >/dev/null 2>&1 && printf 'docker compose' || printf 'docker-compose')
ENV_FILE ?= .env.prod
ENV_LOCAL_FILE := $(ENV_FILE).local
COMPOSE_ENV_FILES := --env-file $(ENV_FILE)
ifneq ("$(wildcard $(ENV_LOCAL_FILE))","")
COMPOSE_ENV_FILES += --env-file $(ENV_LOCAL_FILE)
endif

.PHONY: install agent-config agent-config-check dev staging staging-app prod test test-cov lint format pre-commit-install compose-up compose-down db-setup openapi golden-dataset-validate golden-dataset-sync

install:
	python3 -m venv .venv
	$(PIP) install -e ".[dev]"

agent-config:
	$(PYTHON) scripts/generate_agent_config.py

agent-config-check:
	$(PYTHON) scripts/generate_agent_config.py --check

dev:
	./scripts/run_langgraph_dev.sh

staging:
	./scripts/run_staging_stack.sh

staging-app:
	$(UVICORN) app.main:app --env-file .env.staging $(if $(wildcard .env.staging.local),--env-file .env.staging.local) --reload --reload-include '.env*'

prod: compose-up

test:
	$(PYTEST)

test-cov:
	$(PYTEST) --cov=app --cov-report=term-missing

lint:
	$(RUFF) check .

format:
	$(RUFF) format .

pre-commit-install:
	$(PRE_COMMIT) install

compose-up:
	COMPOSE_ENV_FILE=$(ENV_FILE) COMPOSE_ENV_LOCAL_FILE=$(ENV_LOCAL_FILE) $(DOCKER_COMPOSE) $(COMPOSE_ENV_FILES) up --build -d

compose-down:
	$(DOCKER_COMPOSE) down --remove-orphans

db-setup:
	$(PYTHON) scripts/bootstrap_postgres_checkpointer.py --env-file $(ENV_FILE) $(if $(wildcard $(ENV_LOCAL_FILE)),--env-file $(ENV_LOCAL_FILE))

openapi:
	APP_ENV=development $(PYTHON) scripts/export_openapi.py

golden-dataset-validate:
	$(PYTHON) scripts/validate_golden_dataset.py

golden-dataset-sync:
	$(PYTHON) scripts/sync_langfuse_golden_dataset.py
