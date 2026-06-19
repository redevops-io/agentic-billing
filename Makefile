.PHONY: help up down logs build agents-shell lint

help:
	@echo "Available targets:"
	@echo "  up            Start services with docker compose up -d"
	@echo "  down          Stop services with docker compose down"
	@echo "  logs          Show logs with docker compose logs -f"
	@echo "  build         Build services with docker compose build"
	@echo "  agents-shell  Exec into agents service: docker compose exec agents /bin/sh"
	@echo "  lint          Run python -m compileall agents"

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f

build:
	docker compose build

agents-shell:
	docker compose exec agents /bin/sh

lint:
	python -m compileall agents
