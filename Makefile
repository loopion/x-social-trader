.PHONY: help sync lint format typecheck test cov migrate migrate-new migrate-down seed dev docker-up docker-down

help:
	@echo "Common targets:"
	@echo "  make sync           install deps via uv"
	@echo "  make lint           ruff check"
	@echo "  make format         ruff format"
	@echo "  make typecheck      mypy --strict"
	@echo "  make test           pytest with coverage"
	@echo "  make migrate        alembic upgrade head"
	@echo "  make migrate-new msg='...'   alembic revision --autogenerate -m '<msg>'"
	@echo "  make migrate-down   alembic downgrade -1"
	@echo "  make seed           run scripts/seed.py (idempotent)"
	@echo "  make dev            uvicorn --reload"
	@echo "  make docker-up      docker compose up --build"
	@echo "  make docker-down    docker compose down"

sync:
	uv sync --all-groups

lint:
	uv run ruff check .

format:
	uv run ruff format .

typecheck:
	uv run mypy backend/

test:
	uv run pytest

cov:
	uv run pytest --cov=backend --cov-report=term-missing

migrate:
	uv run alembic upgrade head

migrate-new:
	@if [ -z "$(msg)" ]; then echo "Usage: make migrate-new msg='<message>'"; exit 1; fi
	uv run alembic revision --autogenerate -m "$(msg)"

migrate-down:
	uv run alembic downgrade -1

seed:
	uv run python scripts/seed.py

dev:
	uv run uvicorn backend.api.main:app --reload

docker-up:
	docker compose up --build

docker-down:
	docker compose down
