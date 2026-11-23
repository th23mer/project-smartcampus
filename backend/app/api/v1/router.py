"""Routeur racine `/api/v1` : chaque domaine y ajoute son routeur.

Pour ajouter un domaine (ex. catalogue, SA-20/21) : créer `app/api/v1/<domaine>.py`
avec `router = APIRouter(prefix="/<chemin>", tags=["<Tag SA-5>"])`, puis l'inclure ici.
"""

from fastapi import APIRouter

from app.api.v1 import (  # SA-20 : catalogue  # SA-21 : frais et conditions
    auth,
    catalogue_admission,
    catalogue_curricula,
    catalogue_fees,
    catalogue_programmes,
    conversations,
    health,
    visitor_sessions,
)
from app.schemas.common import ErrorResponse

#: Réponses d'erreur documentées pour toutes les routes (format SA-5 §1.4).
COMMON_ERROR_RESPONSES: dict[int | str, dict] = {
    422: {"model": ErrorResponse, "description": "Données invalides (VALIDATION_ERROR)."},
    500: {"model": ErrorResponse, "description": "Erreur interne (INTERNAL_ERROR)."},
}

api_router = APIRouter(responses=COMMON_ERROR_RESPONSES)
api_router.include_router(health.router)
api_router.include_router(auth.router)  # SA-28, SA-29
api_router.include_router(visitor_sessions.router)  # SA-25
api_router.include_router(conversations.router)  # SA-26
api_router.include_router(catalogue_programmes.router)  # SA-20
api_router.include_router(catalogue_curricula.router)  # SA-20
api_router.include_router(catalogue_fees.router)  # SA-21
api_router.include_router(catalogue_admission.router)  # SA-21
