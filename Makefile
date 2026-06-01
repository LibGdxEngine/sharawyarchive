.PHONY: help up down build restart ps logs logs-backend logs-frontend shell backend-shell frontend-shell makemigrations migrate createsuperuser test-backend test-frontend clean prod-up prod-down prod-build

# Default target: show help
help:
	@echo "======================================================================="
	@echo "                 Dockerized Next.js & Django Template                  "
	@echo "======================================================================="
	@echo "Usage: make <target>"
	@echo ""
	@echo "Development Stack:"
	@echo "  up                - Start development containers in background"
	@echo "  down              - Stop and remove development containers"
	@echo "  build             - Build or rebuild development containers"
	@echo "  restart           - Restart development containers"
	@echo "  ps                - List running development containers"
	@echo "  logs              - Tail all container logs"
	@echo "  logs-backend      - Tail backend container logs"
	@echo "  logs-frontend     - Tail frontend container logs"
	@echo ""
	@echo "Django Operations:"
	@echo "  migrate           - Apply database migrations"
	@echo "  makemigrations    - Create new database migrations"
	@echo "  createsuperuser   - Create a superuser interactively"
	@echo "  shell             - Open Django interactive Python shell"
	@echo "  backend-shell     - Open bash shell inside backend container"
	@echo ""
	@echo "Frontend Operations:"
	@echo "  frontend-shell    - Open sh shell inside frontend container"
	@echo ""
	@echo "Testing & Quality:"
	@echo "  test-backend      - Run Django unit tests"
	@echo "  test-frontend     - Run Next.js linting and type checks"
	@echo ""
	@echo "Production Stack:"
	@echo "  prod-up           - Start production containers in background"
	@echo "  prod-down         - Stop and remove production containers"
	@echo "  prod-build        - Build or rebuild production containers"
	@echo ""
	@echo "Maintenance:"
	@echo "  clean             - Stop containers, remove volumes and temporary caches"
	@echo "======================================================================="

# Development Commands
up:
	docker compose up -d

down:
	docker compose down

build:
	docker compose build

restart:
	docker compose restart

ps:
	docker compose ps

logs:
	docker compose logs -f

logs-backend:
	docker compose logs -f backend

logs-frontend:
	docker compose logs -f frontend

# Django Commands
migrate:
	docker compose exec backend python manage.py migrate

makemigrations:
	docker compose exec backend python manage.py makemigrations

createsuperuser:
	docker compose exec backend python manage.py createsuperuser

shell:
	docker compose exec backend python manage.py shell

backend-shell:
	docker compose exec backend bash

# Frontend Commands
frontend-shell:
	docker compose exec frontend sh

# Testing Commands
test-backend:
	docker compose exec backend python manage.py test

test-frontend:
	docker compose exec frontend npm run lint

# Production Commands
prod-up:
	docker compose -f docker-compose.prod.yml up -d

prod-down:
	docker compose -f docker-compose.prod.yml down

prod-build:
	docker compose -f docker-compose.prod.yml build

# Clean caching and volumes
clean:
	docker compose down -v
	docker compose rm -f
	find . -type d -name "__pycache__" -exec rm -r {} + 2>/dev/null || true
	find . -type d -name ".next" -exec rm -r {} + 2>/dev/null || true
	find . -type d -name "node_modules" -exec rm -r {} + 2>/dev/null || true
