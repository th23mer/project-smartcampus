"""Point d'entrée FastAPI de SmartCampus AI (SA-7).

Lancement en dev : `uv run uvicorn app.main:app --reload --port 8000`
Swagger : http://localhost:8000/docs · OpenAPI : http://localhost:8000/api/v1/openapi.json
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import Settings, get_settings
from app.core.db import dispose_engine
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging
from app.core.request_id import REQUEST_ID_HEADER, RequestIdMiddleware

DESCRIPTION = """
API de **SmartCampus AI**, plateforme conversationnelle et agentique d'orientation
universitaire (IIT Sfax · ISB).

* Toutes les routes sont sous `/api/v1` ; JSON en `snake_case`, identifiants UUID.
* **Format d'erreur unique** : `{"error": {"code", "message", "details", "request_id"}}`.
* Chaque réponse porte l'en-tête `X-Request-ID` (à citer au support).
* Listes paginées : `?page=1&page_size=20` (max 100).
* **Authentification simulée en dev/test** : en-têtes `X-Dev-User-Id` (UUID),
  `X-Dev-Roles` (ex. `candidate` ou `iit_academic_lead,interview_lead`) et
  `X-Dev-Institution-Id` (facultatif). Elle sera remplacée par l'authentification
  JWT d'E3 sans changer les routes.

Contrats de référence : SA-5 (spécification OpenAPI sur `/api/v1/openapi.json`).
"""

OPENAPI_TAGS = [
    {"name": "Système", "description": "Sondes de santé et de disponibilité."},
]


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await dispose_engine()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Fabrique de l'application (les tests passent leurs propres réglages)."""
    settings = settings or get_settings()

    app = FastAPI(
        title=f"{settings.app_name} — API",
        description=DESCRIPTION,
        version=settings.app_version,
        openapi_url=f"{settings.api_prefix}/openapi.json",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_tags=OPENAPI_TAGS,
        lifespan=lifespan,
        swagger_ui_parameters={"defaultModelsExpandDepth": 0},
    )
    app.dependency_overrides[get_settings] = lambda: settings
    app.state.settings = settings

    register_error_handlers(app)
    # Ordre : le dernier ajouté est le plus externe. CORS enveloppe RequestId pour que
    # même les 500 produites par RequestIdMiddleware reçoivent les en-têtes CORS.
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[REQUEST_ID_HEADER, "ETag", "Retry-After"],
    )

    app.include_router(api_router, prefix=settings.api_prefix)
    return app


_settings = get_settings()
configure_logging(_settings.log_level, json_output=_settings.log_json)
app = create_app(_settings)
