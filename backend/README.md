# Backend SmartCampus AI (SA-7)

FastAPI + SQLAlchemy 2 async (asyncpg) + Alembic (psycopg 3), Python 3.12 géré par **uv**.

## Démarrer

```bash
# Depuis la racine : base PostgreSQL (SA-16), après `cp .env.example .env`
docker compose up -d db db-test

cd backend
~/.local/bin/uv sync                                   # crée .venv depuis uv.lock
~/.local/bin/uv run uvicorn app.main:app --reload --port 8000
```

- Santé : `GET http://localhost:8000/api/v1/health` · base : `GET /api/v1/health/ready`
- Swagger : http://localhost:8000/docs · OpenAPI : `/api/v1/openapi.json`

## Configuration

Priorité : variables d'environnement > `backend/.env` > `.env` racine > `config/app.yaml` >
défauts du code. Secrets uniquement dans `.env` (jamais commité). Voir `.env.example`.

## Tests et qualité

```bash
~/.local/bin/uv run pytest            # le test « db » est sauté sans TEST_DATABASE_URL
set -a; . ../.env; set +a; ~/.local/bin/uv run pytest   # avec la base de test (port 5433)
~/.local/bin/uv run ruff check . && ~/.local/bin/uv run ruff format --check .
```

## Migrations

```bash
~/.local/bin/uv run alembic revision --autogenerate -m "catalogue"   # SA-17
~/.local/bin/uv run alembic upgrade head
```

## Authentification simulée (dev/test seulement)

En-têtes `X-Dev-User-Id: <uuid>`, `X-Dev-Roles: iit_academic_lead,interview_lead`,
`X-Dev-Institution-Id: <uuid>` (facultatif). Les routes utilisent seulement
`get_current_user`, `get_optional_user` et `require_roles(...)` de `app/core/security.py` ;
E3 remplacera l'implémentation via `set_auth_backend(...)`.

```python
from typing import Annotated
from fastapi import APIRouter, Depends
from app.core.security import CurrentUser, Role, require_roles

router = APIRouter(prefix="/staff/catalogue", tags=["Catalogue : écriture et publication (staff)"])


@router.post("/programmes/{programme_id}/publish")
async def publish(
    user: Annotated[CurrentUser, Depends(require_roles(Role.IIT_ACADEMIC_LEAD, Role.DIRECTION))],
): ...
```

Erreurs métier : `raise AppError(ErrorCode.VALIDITY_OVERLAP, details={...})` (format SA-5).
