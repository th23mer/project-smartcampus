# SmartCampus AI : commandes de l'environnement de développement local (SA-9).
# Tout passe par Docker Compose (docker-compose.yml) et le fichier .env de la racine.
# `make help` liste les commandes. Sans `make` : voir le guide SA-9 (commandes équivalentes).

SHELL := /bin/bash
.DEFAULT_GOAL := help

DC := docker compose
# Les fichiers créés par le backend dans le volume monté appartiennent au développeur.
export APP_UID := $(shell id -u)
export APP_GID := $(shell id -g)

# Service visé par `make logs SERVICE=backend` (vide = tous).
SERVICE ?=
SEED_SCRIPT := backend/scripts/seed.py
DB_VOLUME := smartcampus_db_data

.PHONY: help env check-env build up down stop ps logs migrate migrate-status seed \
        test test-backend test-frontend lint reset-db shell-backend psql worker

help: ## Affiche cette aide
	@echo "SmartCampus AI : environnement de dev (SA-9)"
	@grep -hE '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-16s %s\n", $$1, $$2}'

env: ## Crée .env depuis .env.example s'il n'existe pas (valeurs factices de dev)
	@if [ -f .env ]; then echo ".env existe déjà : rien à faire."; \
	else cp .env.example .env && echo ".env créé depuis .env.example. Adaptez les ports si besoin."; fi

check-env:
	@[ -f .env ] || { echo "ERREUR : fichier .env absent. Lancez : make env  (ou cp .env.example .env)"; exit 1; }
	@docker info >/dev/null 2>&1 || { echo "ERREUR : le démon Docker ne répond pas (docker info). Démarrez Docker."; exit 1; }

build: check-env ## Construit les images backend et frontend
	$(DC) build

up: check-env ## Démarre db, db-test, backend, frontend, mailpit et attend qu'ils soient sains
	$(DC) up -d --build --renew-anon-volumes --wait
	@set -a; . ./.env; set +a; \
	echo ""; \
	echo "API       : http://localhost:$${BACKEND_HOST_PORT:-8000}/api/v1/health/ready  (Swagger : /docs)"; \
	echo "Frontend  : http://localhost:$${FRONTEND_HOST_PORT:-3000}"; \
	echo "Mailpit   : http://localhost:$${MAILPIT_UI_HOST_PORT:-8025}"; \
	echo "PostgreSQL: localhost:$${DB_HOST_PORT:-5432} (dev), localhost:$${DB_TEST_HOST_PORT:-5433} (test)"

stop: ## Arrête les conteneurs sans les supprimer (données conservées)
	$(DC) --profile worker --profile seaweedfs --profile mlflow stop

down: ## Arrête et supprime les conteneurs (le volume de la base de dev est CONSERVÉ)
	$(DC) --profile worker --profile seaweedfs --profile mlflow down

ps: ## État des services
	$(DC) ps

logs: ## Journaux en continu (make logs SERVICE=backend)
	$(DC) logs -f --tail=200 $(SERVICE)

migrate: check-env ## Applique les migrations Alembic (alembic upgrade head, rôle smartcampus_owner)
	$(DC) run --rm --no-TTY backend uv run --frozen alembic upgrade head

migrate-status: check-env ## Révision Alembic courante de la base de dev (alembic current)
	$(DC) run --rm --no-TTY backend uv run --frozen alembic current

seed: check-env ## Charge les données synthétiques de démo (script de SA-18)
	@if [ -f $(SEED_SCRIPT) ]; then \
	  $(DC) run --rm --no-TTY backend uv run --frozen python scripts/seed.py; \
	else \
	  echo "Pas encore de données de démo : $(SEED_SCRIPT) sera livré par SA-18."; \
	  echo "Cette cible l'appellera automatiquement dès qu'il existera (après make migrate)."; \
	fi

test: test-backend test-frontend ## Lance tous les tests (backend + frontend)

# Les tests vérifient les valeurs par défaut (config/app.yaml) : on retire du conteneur les
# surcharges propres au poste (CORS calculé depuis FRONTEND_HOST_PORT, journaux).
TEST_UNSET := -u CORS_ORIGINS -u LOG_JSON -u LOG_LEVEL
# SA-22 (performance) : bytecode du code monté mis en cache hors du volume (/tmp, dans le
# conteneur) au lieu d'être recompilé par chaque processus ; `--no-sync` : l'image contient
# déjà l'environnement figé par uv.lock (reconstruire l'image après un changement de dépendances).
TEST_ENV := -u PYTHONDONTWRITEBYTECODE PYTHONPYCACHEPREFIX=/tmp/pycache

test-backend: check-env ## Tests pytest du backend (base de test db-test)
	$(DC) up -d --wait db-test
	$(DC) run --rm --no-deps --no-TTY backend env $(TEST_UNSET) $(TEST_ENV) uv run --frozen --no-sync pytest

test-frontend: check-env ## Tests vitest du frontend
	$(DC) run --rm --no-deps --no-TTY frontend npm test

lint: check-env ## ruff (backend) + eslint et tsc (frontend)
	$(DC) run --rm --no-deps --no-TTY backend sh -c "uv run --frozen ruff check . && uv run --frozen ruff format --check ."
	$(DC) run --rm --no-deps --no-TTY frontend sh -c "npm run lint && npm run typecheck"

reset-db: ## SUPPRIME la base de dev (volume) après confirmation ; CONFIRM=oui pour ne pas demander
	@if [ "$(CONFIRM)" != "oui" ]; then \
	  read -r -p "Supprimer DÉFINITIVEMENT la base de dev (volume $(DB_VOLUME)) ? Tapez oui : " rep; \
	  [ "$$rep" = "oui" ] || { echo "Annulé."; exit 1; }; \
	fi
	$(DC) rm --stop --force db
	-docker volume rm $(DB_VOLUME)
	@echo "Base supprimée. Relancez : make up && make migrate && make seed"

shell-backend: ## Ouvre un shell dans le conteneur backend
	$(DC) exec backend bash

psql: ## Console psql sur la base de dev (rôle applicatif)
	@set -a; . ./.env; set +a; \
	$(DC) exec -e PGPASSWORD="$$SMARTCAMPUS_APP_PASSWORD" db psql -U smartcampus_app -d "$${POSTGRES_DB:-smartcampus}"

worker: check-env ## Démarre le worker de jobs (profil worker ; provisoire tant qu'ADR-06 n'est pas codé)
	$(DC) --profile worker up worker
