.PHONY: bootstrap runtime dev dev-api dev-web test test-sandbox generated lint typecheck build up down logs migrate

PYTHON ?= python
CONTROL_VENV ?= .venv
RUNTIME_VENV ?= .venv-agent-runtime

ifeq ($(OS),Windows_NT)
CONTROL_PYTHON := $(CONTROL_VENV)/Scripts/python.exe
RUNTIME_PYTHON := $(RUNTIME_VENV)/Scripts/python.exe
else
CONTROL_PYTHON := $(CONTROL_VENV)/bin/python
RUNTIME_PYTHON := $(RUNTIME_VENV)/bin/python
endif

bootstrap:
	$(PYTHON) -m venv $(CONTROL_VENV)
	$(CONTROL_PYTHON) -m pip install -e "services/api[dev]"
	npm --prefix apps/web ci
	$(MAKE) runtime

runtime:
	$(PYTHON) -m venv $(RUNTIME_VENV)
	$(RUNTIME_PYTHON) -m pip install --require-hashes --no-deps -r services/api/app/generator/runtime/requirements-dev.lock

dev:
	docker compose up --build

dev-api:
	cd services/api && AGENTFORGE_BUILD_DISPATCH=inline AGENTFORGE_SANDBOX_PYTHON=$(abspath $(RUNTIME_PYTHON)) AGENTFORGE_DATABASE_URL=sqlite:///./agentforge.db ../../$(CONTROL_PYTHON) -m alembic upgrade head
	cd services/api && AGENTFORGE_BUILD_DISPATCH=inline AGENTFORGE_SANDBOX_PYTHON=$(abspath $(RUNTIME_PYTHON)) AGENTFORGE_DATABASE_URL=sqlite:///./agentforge.db ../../$(CONTROL_PYTHON) -m uvicorn app.main:app --reload --port 8000

dev-web:
	npm --prefix apps/web run dev

test:
	npm --prefix apps/web test -- --run
	$(CONTROL_PYTHON) -m pytest services/api/tests -q

test-sandbox:
	AGENTFORGE_SANDBOX_PYTHON=$(abspath $(RUNTIME_PYTHON)) $(CONTROL_PYTHON) -m pytest services/api/tests -q -m sandbox

generated:
	$(CONTROL_PYTHON) scripts/verify_templates.py --runtime $(RUNTIME_PYTHON)

lint:
	npm --prefix apps/web run lint
	$(CONTROL_PYTHON) -m ruff check services/api
	$(CONTROL_PYTHON) -m ruff format --check services/api

typecheck:
	npm --prefix apps/web run typecheck

build:
	npm --prefix apps/web run build

up:
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f --tail=200

migrate:
	docker compose run --rm api alembic upgrade head

