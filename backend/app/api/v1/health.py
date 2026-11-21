"""Sondes de santé (SA-5 §5.1, SA-4 §9.4)."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.config import Settings, get_settings
from app.core.db import get_engine, ping_database
from app.core.errors import AppError, ErrorCode
from app.schemas.common import ErrorResponse, Health, Readiness

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health", tags=["Système"])


@router.get(
    "",
    response_model=Health,
    summary="État du service (sonde de vie)",
    description="Accès : tous (public). Ne touche à aucune dépendance externe.",
    operation_id="get_health",
)
async def get_health(settings: Annotated[Settings, Depends(get_settings)]) -> Health:
    return Health(status="ok", version=settings.app_version, time=datetime.now(UTC))


@router.get(
    "/ready",
    response_model=Readiness,
    summary="Disponibilité des dépendances (sonde de disponibilité)",
    description=(
        "Accès : tous (public). Vérifie que la base PostgreSQL répond (`SELECT 1`). "
        "Renvoie 503 SERVICE_UNAVAILABLE sinon. Le stockage de fichiers et le LLM "
        "seront ajoutés par SA-9 et E4."
    ),
    operation_id="get_health_ready",
    responses={503: {"model": ErrorResponse, "description": "Dépendance indisponible."}},
)
async def get_health_ready(settings: Annotated[Settings, Depends(get_settings)]) -> Readiness:
    if not settings.database_url:
        raise AppError(
            ErrorCode.SERVICE_UNAVAILABLE,
            details={"checks": {"database": "not_configured"}},
        )
    try:
        await asyncio.wait_for(ping_database(get_engine()), timeout=settings.db_ready_timeout_s)
    except Exception as exc:
        logger.warning("Base de données injoignable : %s", type(exc).__name__)
        raise AppError(
            ErrorCode.SERVICE_UNAVAILABLE,
            details={"checks": {"database": "unreachable"}},
            headers={"Retry-After": "5"},
        ) from exc
    return Readiness(status="ok", checks={"database": "ok"})
