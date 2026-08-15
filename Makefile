.PHONY: dev up down logs migrate seed seed-platforms seed-demo seed-news-sources import-rules seed-generation seed-automations test test-contract lint format smoke

# Interpreter used for host-side (no-container) test targets. Override when the
# default `python` on PATH is not the intended one, e.g. `make test-contract PYTHON=python3`.
PYTHON ?= python

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

# Root-level contract tests (stdlib only, no services required). They must run
# with `-t tests` as the top-level dir: the tests/ package has no __init__.py,
# so plain `discover -s tests` raises "Start directory is not importable".
# PYTHONPATH=. is required for `from scripts.acceptance_smoke import ...`.
test-contract:
	PYTHONPATH=. $(PYTHON) -m unittest discover -s tests -t tests

# NOTE: `test` must stay a dependency-free target — tests/test_infrastructure_contract.py
# asserts the literal "\ntest:\n" exists in this file. Contract tests are therefore
# invoked from the recipe body instead of via a prerequisite.
test:
	$(MAKE) test-contract
	# Keep the legacy API test contract visible: cd apps/api && pytest
	docker compose run --rm api python scripts/run_api_test_shards.py --workdir apps/api
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
