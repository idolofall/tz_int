.PHONY: up down logs test lint migrate

up:
	docker compose up --build -d

down:
	docker compose down -v

logs:
	docker compose logs -f app

migrate:
	docker compose exec app alembic upgrade head

lint:
	ruff check src tests

test:
	pytest -q
