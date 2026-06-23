# --- club-manager dev workflow -----------------------------------------------
# Single-command dev orchestration for backend (Django + Postgres + Q2) and
# frontend (Expo + Metro). Backend lives in docker-compose.yml; frontend lives
# in docker-compose.frontend.yml. Both join the same `club_default` network
# because we pin --project-name club on every invocation.
#
# Usage:
#   make help            # list all targets
#   make up              # full stack (backend + frontend)
#   make up-backend      # backend only
#   make up-frontend     # frontend only (backend must be up)
#   make down            # stop everything, preserve volumes
#   make logs            # tail all service logs
#   make pnpm-approve    # one-time ritual (only if pnpm prompts)
#   make shell-frontend  # shell into the frontend container

PROJECT       := club
COMPOSE_BOTH  := docker compose --project-name $(PROJECT) -f docker-compose.yml -f docker-compose.frontend.yml
COMPOSE_BE    := docker compose --project-name $(PROJECT) -f docker-compose.yml
COMPOSE_FE    := docker compose --project-name $(PROJECT) -f docker-compose.frontend.yml

.PHONY: help up up-backend up-frontend down logs logs-backend logs-frontend pnpm-approve shell-backend shell-frontend migrate

help:           ## show this help
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

up:             ## start full stack (backend + frontend)
	$(COMPOSE_BOTH) up -d --build

up-backend:     ## start backend only (db, web, qcluster)
	$(COMPOSE_BE) up -d --build

up-frontend:    ## start frontend only (backend must be up and healthy)
	$(COMPOSE_FE) up -d --build

down:           ## stop everything (preserves named volumes)
	$(COMPOSE_BOTH) down

logs:           ## tail all service logs
	$(COMPOSE_BOTH) logs -f --tail=100

logs-backend:   ## tail backend logs only
	$(COMPOSE_BE) logs -f --tail=100

logs-frontend:  ## tail frontend logs only
	$(COMPOSE_FE) logs -f --tail=100

pnpm-approve:   ## one-time: run pnpm approve-builds on host (interactive, usually a no-op)
	cd mobile && pnpm approve-builds

shell-backend:  ## shell into the backend web container
	$(COMPOSE_BE) exec web bash

shell-frontend: ## shell into the frontend container
	$(COMPOSE_FE) exec frontend sh

migrate:        ## run Django migrations in the web container
	$(COMPOSE_BE) exec web python manage.py migrate

# TODO: make test — run backend pytest
# Deferred until we have >10 backend tests needing CI-style runs.
# For now, run from your dev container:
#   cd backend && source .venv/bin/activate && pytest