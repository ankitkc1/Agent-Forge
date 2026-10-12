.PHONY: bootstrap dev test lint typecheck build up down logs migrate

bootstrap:
	npm --prefix apps/web ci
	python -m pip install -e "services/api[dev]"

dev:
	docker compose up --build

test:
	npm --prefix apps/web test -- --run
	python -m pytest services/api/tests -q

lint:
	npm --prefix apps/web run lint
	python -m ruff check services/api

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

