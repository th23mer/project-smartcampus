"""Fixtures communes. Les tests n'utilisent ni `.env` ni base réelle (sauf marqueur `db`)."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated

# Avant tout import de l'application : environnement de test, sans base configurée.
os.environ["APP_ENV"] = "test"
os.environ.pop("DATABASE_URL", None)

import psycopg
import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.core.config import Settings
from app.core.errors import AppError, ErrorCode
from app.core.pagination import Page, PageParamsDep
from app.core.security import CurrentUser, CurrentUserDep, Role, require_roles
from app.main import create_app

TEST_JWT_SECRET = "test-only-jwt-secret-for-pytest-0123456789abcdef"


def make_settings(**overrides) -> Settings:
    base = {
        "app_env": "test",
        "database_url": None,
        "log_json": False,
        # Secret factice des tests (SA-28) : jamais utilisé hors de pytest.
        "jwt_secret": TEST_JWT_SECRET,
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)  # type: ignore[call-arg]


class Payload(BaseModel):
    name: str
    age: int


def _test_router() -> APIRouter:
    """Routes réservées aux tests (erreurs, auth, pagination)."""
    router = APIRouter(prefix="/_test")

    @router.get("/boom")
    async def boom() -> None:
        raise RuntimeError("secret interne : mot_de_passe=xyz")

    @router.get("/app-error")
    async def app_error() -> None:
        raise AppError(
            ErrorCode.INVALID_STATUS_TRANSITION,
            details={"current_status": "draft", "allowed": ["submitted", "withdrawn"]},
        )

    @router.post("/echo")
    async def echo(payload: Payload) -> Payload:
        return payload

    @router.get("/me")
    async def me(user: CurrentUserDep) -> dict:
        return {"id": str(user.id), "roles": sorted(user.roles), "account_type": user.account_type}

    @router.get("/staff-only")
    async def staff_only(
        user: Annotated[
            CurrentUser, Depends(require_roles(Role.IIT_ACADEMIC_LEAD, Role.DIRECTION))
        ],
    ) -> dict:
        return {"ok": True, "institution_id": str(user.institution_id)}

    @router.get("/items")
    async def items(params: PageParamsDep) -> Page[int]:
        data = list(range(1, 46))
        return Page[int].build(
            data[params.offset : params.offset + params.limit], len(data), params
        )

    return router


def build_app(settings: Settings):
    app = create_app(settings)
    app.include_router(_test_router(), prefix=settings.api_prefix)
    return app


_SHARED_APPS: dict[str, tuple[FastAPI, dict]] = {}


def shared_app(app_env: str = "test") -> FastAPI:
    """Application de test **partagée** par environnement (SA-22, performance).

    Construire l'application coûte ~0,6 s (FastAPI reconstruit la centaine de routes du
    catalogue à chaque `include_router`) : on la construit une fois par session et on remet ses
    surcharges de dépendances à l'état initial avant chaque usage. Les tests qui ajoutent des
    routes ou modifient l'application gardent `build_app(...)` (application neuve).
    """
    if app_env not in _SHARED_APPS:
        app = build_app(make_settings(app_env=app_env))
        _SHARED_APPS[app_env] = (app, dict(app.dependency_overrides))
    app, base_overrides = _SHARED_APPS[app_env]
    app.dependency_overrides.clear()
    app.dependency_overrides.update(base_overrides)
    return app


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(shared_app()) as c:
        yield c


@pytest.fixture
def prod_client() -> Iterator[TestClient]:
    with TestClient(shared_app("prod")) as c:
        yield c


def dev_headers(
    *roles: str, user_id: uuid.UUID | None = None, institution_id: uuid.UUID | None = None
) -> dict[str, str]:
    headers = {"X-Dev-User-Id": str(user_id or uuid.uuid4()), "X-Dev-Roles": ",".join(roles)}
    if institution_id:
        headers["X-Dev-Institution-Id"] = str(institution_id)
    return headers


# --- Base de test partagée (SA-22, performance) -------------------------------------------------
# Une seule remise à zéro du schéma par session, un seul chargement du seed de démo : les
# modules qui en ont besoin demandent ces fixtures au lieu de refaire downgrade / upgrade / seed.

BACKEND_DIR = Path(__file__).resolve().parents[1]
SEED_SCRIPT = BACKEND_DIR / "scripts" / "seed.py"


def db_test_env(name: str) -> str:
    """Variable de la base de test (SA-16) ; test sauté si elle manque."""
    value = os.environ.get(name)
    if not value:
        pytest.skip(f"{name} non définie (base de test SA-16 requise)")
    return value


def plain_url(url: str) -> str:
    """URL SQLAlchemy (`postgresql+asyncpg://`, `postgresql+psycopg://`) → URL libpq."""
    scheme, rest = url.split("://", 1)
    return "postgresql://" + rest if scheme.startswith("postgresql") else url


def run_python(args: list[str], **env: str) -> subprocess.CompletedProcess[str]:
    """Lance `python <args>` depuis backend/ (alembic, seed : réglages isolés)."""
    return subprocess.run(
        [sys.executable, *args],
        cwd=BACKEND_DIR,
        env={**os.environ, **env},
        capture_output=True,
        text=True,
        check=False,
    )


def reset_schema() -> None:
    """db-test vide puis `upgrade head` (rôle propriétaire)."""
    url = db_test_env("TEST_MIGRATION_DATABASE_URL")
    for step in (("downgrade", "base"), ("upgrade", "head")):
        res = run_python(["-m", "alembic", *step], MIGRATION_DATABASE_URL=url)
        assert res.returncode == 0, res.stderr


def table_counts(url: str) -> dict[str, int]:
    """Nombre de lignes de chaque table du schéma public."""
    with psycopg.connect(url) as conn:
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
                " AND tablename <> 'alembic_version' ORDER BY 1"
            )
        ]
        return {t: conn.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] for t in tables}


@pytest.fixture(scope="session")
def test_db_schema() -> str:
    """Schéma remis à zéro **une fois par session** ; chaque test s'isole ensuite par une
    transaction annulée. Renvoie l'URL du rôle propriétaire."""
    reset_schema()
    return db_test_env("TEST_MIGRATION_DATABASE_URL")


@pytest.fixture(scope="session")
def demo_seed(test_db_schema: str) -> Iterator[dict]:
    """Seed de démo SA-18 chargé **une fois par session** (deux passes pour l'idempotence).

    Utilisé par `tests/test_seed.py` et `tests/verification/test_bout_en_bout_demo.py`. Les
    lignes publiées étant figées, db-test est remise à vide en fin de session.
    """
    app_url = db_test_env("TEST_DATABASE_URL")
    url = plain_url(app_url)
    if any(table_counts(url).values()):  # base non vide (autre module) : on repart de zéro
        reset_schema()
    try:
        first = run_python([str(SEED_SCRIPT), "--database-url", app_url])
        assert first.returncode == 0, first.stderr
        counts_1 = table_counts(url)
        second = run_python([str(SEED_SCRIPT), "--database-url", app_url])
        assert second.returncode == 0, second.stderr
        counts_2 = table_counts(url)
        yield {
            "first": first.stdout,
            "second": second.stdout,
            "counts_1": counts_1,
            "counts_2": counts_2,
            "url": url,
        }
    finally:
        reset_schema()
