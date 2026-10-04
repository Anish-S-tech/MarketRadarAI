COMPOSE := docker compose
SCENARIO ?= acme-price-hike

.PHONY: help up down logs ps models migrate seed demo-reset demo-mutate check-all brief test test-backend test-frontend lint api-client observability

help:
	@echo "make up            build + start the full stack (http://localhost:8080)"
	@echo "make models        pull the Ollama models the agents use"
	@echo "make seed          create the demo org, users, competitors and sources"
	@echo "make demo-mutate SCENARIO=acme-price-hike|globex-partnership|initech-launch|noise"
	@echo "make check-all     make every source due now (the scheduler picks them up within a minute)"
	@echo "make brief         generate today's daily brief for the demo org"
	@echo "make test          backend + frontend test suites"

up:
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f api worker beat

ps:
	$(COMPOSE) ps

models:
	ollama pull llama3.2
	ollama pull nomic-embed-text

migrate:
	$(COMPOSE) run --rm migrate

seed:
	$(COMPOSE) exec api python -m app.cli seed-demo

demo-reset:
	python scripts/demo_mutate.py reset

demo-mutate:
	python scripts/demo_mutate.py $(SCENARIO)

check-all:
	$(COMPOSE) exec -T postgres psql -U marketradar -d marketradar -c "update sources set next_check_at = now()"

brief:
	$(COMPOSE) exec api python -m app.cli brief northwind

observability:
	$(COMPOSE) --profile observability up -d prometheus grafana

test: test-backend test-frontend

test-backend:
	cd backend && uv run pytest -q

test-frontend:
	cd frontend && npm test

lint:
	cd backend && uv run ruff check app tests && uv run mypy app
	cd frontend && npm run lint && npm run typecheck

api-client:
	cd backend && uv run python -m app.export_openapi ../frontend/openapi.json
	cd frontend && npm run gen:api
