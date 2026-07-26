.PHONY: dev up down logs migrate seed seed-platforms seed-demo seed-news-sources import-rules seed-generation seed-automations test lint format smoke

dev:
	docker compose up --build

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f --tail=200

migrate:
	docker compose run --rm api sh -lc "cd apps/api && alembic upgrade head"

seed:
	docker compose run --rm api python -m app.cli bootstrap-admin

seed-platforms:
	docker compose run --rm api python -m app.cli seed-platforms

seed-demo:
	docker compose run --rm api python -m app.cli seed-demo-monitoring

seed-news-sources:
	docker compose run --rm api python -m app.cli seed-news-sources

import-rules:
	@test -n "$(FILE)" || (echo "FILE is required, for example FILE=data/rules/ELITE_..._FULL.txt" && exit 1)
	docker compose run --rm api python -m app.cli import-rules --file "$(FILE)"

seed-generation:
	docker compose run --rm api python -m app.cli seed-generation

seed-automations:
	docker compose run --rm api python -m app.cli seed-automations

test:
	docker compose run --rm api sh -lc "cd apps/api && pytest"
	docker compose run --rm web pnpm --filter @sio/web test

lint:
	docker compose run --rm api sh -lc "cd apps/api && ruff check --no-cache app tests"
	docker compose run --rm api sh -lc "cd apps/api && mypy --cache-dir /tmp/mypy app"
	docker compose run --rm web pnpm --filter @sio/web lint
	docker compose run --rm web pnpm --filter @sio/web typecheck

format:
	docker compose run --rm api sh -lc "cd apps/api && ruff format app tests"
	docker compose run --rm api sh -lc "cd apps/api && ruff check --fix app tests"
	docker compose run --rm web pnpm format

smoke:
	python scripts/acceptance_smoke.py --base-url http://localhost:8080
