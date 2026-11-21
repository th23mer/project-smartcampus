"""Schémas communs à toute l'API : erreur (SA-5 §1.4) et santé (SA-5 §5.1)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ErrorBody(BaseModel):
    code: str = Field(description="Code stable en MAJUSCULES_SNAKE (catalogue SA-5).")
    message: str = Field(description="Message lisible en français, sans détail technique.")
    details: dict[str, Any] | list[dict[str, Any]] | None = Field(
        default=None, description="Précisions : champs invalides, transitions possibles…"
    )
    request_id: str | None = Field(description="Identique à l'en-tête X-Request-ID.")


class ErrorResponse(BaseModel):
    """Format d'erreur unique de l'API."""

    error: ErrorBody

    model_config = {
        "json_schema_extra": {
            "example": {
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Les données envoyées sont invalides.",
                    "details": [
                        {"field": "page_size", "issue": "less_than_equal", "location": "query"}
                    ],
                    "request_id": "req_3f2c9a7d1b8e4c6a9f0e2d4b6a8c0e1f",
                }
            }
        }
    }


class Health(BaseModel):
    """État du service (sonde de vie)."""

    status: Literal["ok", "degraded"]
    version: str
    time: datetime


class Readiness(BaseModel):
    """État des dépendances (sonde de disponibilité)."""

    status: Literal["ok"]
    checks: dict[str, str]
