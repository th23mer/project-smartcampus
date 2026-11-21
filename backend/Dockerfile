# syntax=docker/dockerfile:1
# Image du backend SmartCampus AI (SA-9) : FastAPI + uv, Python 3.12.
# Une seule image sert au service `backend` (API) et au service `worker` (file de jobs, ADR-06).
#
# Cibles :
#   dev  (par défaut dans docker-compose.yml) : dépendances + groupe dev (pytest, ruff),
#        le code est monté en volume et uvicorn tourne avec --reload ;
#   prod : dépendances d'exécution seulement, code copié dans l'image, sans --reload.

ARG PYTHON_IMAGE=python:3.12.16-slim-bookworm

FROM ${PYTHON_IMAGE} AS base

# uv installé depuis PyPI (registre officiel), même version que sur les postes de l'équipe.
ARG UV_VERSION=0.13.8
# Utilisateur non root dont l'UID correspond en général à celui du développeur sous Linux :
# les fichiers créés dans le volume monté (migrations Alembic, caches) lui appartiennent.
ARG APP_UID=1000
ARG APP_GID=1000

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # L'environnement virtuel vit HORS du dossier monté : le .venv de l'hôte n'est jamais utilisé.
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    # SA-22 : dépendances précompilées en bytecode à l'installation (sinon chaque processus
    # Python, y compris les sous-processus alembic / seed des tests, recompile tout).
    UV_COMPILE_BYTECODE=1 \
    UV_CACHE_DIR=/tmp/uv-cache \
    TZ=Africa/Tunis \
    PATH=/opt/venv/bin:$PATH

RUN pip install "uv==${UV_VERSION}" \
 && groupadd --gid "${APP_GID}" app \
 && useradd --uid "${APP_UID}" --gid "${APP_GID}" --create-home --shell /bin/bash app \
 && mkdir -p /opt/venv /app \
 && chown app:app /opt/venv /app

WORKDIR /app
USER app

# --- Cible dev : dépendances (y compris le groupe dev) figées par uv.lock -------------------
FROM base AS dev
COPY --chown=app:app pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-install-project
# Copie du code pour que l'image fonctionne aussi sans volume ; en dev, le volume la masque.
COPY --chown=app:app . .
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=6 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=2).status == 200 else 1)"
CMD ["uv", "run", "--frozen", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload", "--reload-dir", "app", "--reload-dir", "config"]

# --- Cible prod : sans outils de dev, sans rechargement -------------------------------------
FROM base AS prod
COPY --chown=app:app pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-install-project --no-dev
COPY --chown=app:app . .
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=6 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=2).status == 200 else 1)"
CMD ["uv", "run", "--frozen", "--no-dev", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
