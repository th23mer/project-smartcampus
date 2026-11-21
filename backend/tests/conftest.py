"""Fixtures communes. Les tests n'utilisent ni `.env` ni base réelle (sauf marqueur `db`)."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from typing import Annotated

# Avant tout import de l'application : environnement de test, sans base configurée.
os.environ["APP_ENV"] = "test"
os.environ.pop("DATABASE_URL", None)

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.core.config import Settings
from app.core.errors import AppError, ErrorCode
from app.core.pagination import Page, PageParamsDep
from app.core.security import CurrentUser, CurrentUserDep, Role, require_roles
from app.main import create_app


def make_settings(**overrides) -> Settings:
    base = {"app_env": "test", "database_url": None, "log_json": False}
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
