"""Format d'erreur unique de l'API (SA-5 §1.4).

Toute réponse d'erreur a exactement la forme :

    {"error": {"code": "...", "message": "...", "details": ..., "request_id": "..."}}

- `code` : stable, MAJUSCULES_SNAKE, testé par le front ;
- `message` : en français, sans trace technique ;
- `details` : null, un objet, ou une liste `[{"field": ..., "issue": ...}]` ;
- `request_id` : identique à l'en-tête `X-Request-ID`.
"""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.request_id import get_request_id

logger = logging.getLogger("app.errors")


class ErrorCode(StrEnum):
    """Catalogue des codes d'erreur de SA-5 §1.4 (+ 2 codes techniques signalés en fin)."""

    VALIDATION_ERROR = "VALIDATION_ERROR"
    INVALID_TOKEN = "INVALID_TOKEN"
    CONSENT_REQUIRED = "CONSENT_REQUIRED"
    TRANSCRIPTION_FAILED = "TRANSCRIPTION_FAILED"
    UNAUTHENTICATED = "UNAUTHENTICATED"
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    FORBIDDEN = "FORBIDDEN"
    FOUR_EYES_REQUIRED = "FOUR_EYES_REQUIRED"
    CONSENT_NOT_GIVEN = "CONSENT_NOT_GIVEN"
    ACCOUNT_DISABLED = "ACCOUNT_DISABLED"
    ACCOUNT_NOT_VERIFIED = "ACCOUNT_NOT_VERIFIED"
    SESSION_NOT_OWNED = "SESSION_NOT_OWNED"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    EMAIL_ALREADY_USED = "EMAIL_ALREADY_USED"
    ALREADY_ATTACHED = "ALREADY_ATTACHED"
    INVALID_STATUS_TRANSITION = "INVALID_STATUS_TRANSITION"
    ACADEMIC_YEAR_REQUIRED = "ACADEMIC_YEAR_REQUIRED"
    CAMPAIGN_CLOSED = "CAMPAIGN_CLOSED"
    DUPLICATE_PREREGISTRATION = "DUPLICATE_PREREGISTRATION"
    SLOT_UNAVAILABLE = "SLOT_UNAVAILABLE"
    VALIDITY_OVERLAP = "VALIDITY_OVERLAP"
    NOT_INDEXED_YET = "NOT_INDEXED_YET"
    CONVERSATION_CLOSED = "CONVERSATION_CLOSED"
    QCM_NOT_AVAILABLE = "QCM_NOT_AVAILABLE"
    DOCUMENT_LOCKED = "DOCUMENT_LOCKED"
    IDEMPOTENCY_KEY_CONFLICT = "IDEMPOTENCY_KEY_CONFLICT"
    SESSION_EXPIRED = "SESSION_EXPIRED"
    QCM_EXPIRED = "QCM_EXPIRED"
    PRECONDITION_FAILED = "PRECONDITION_FAILED"
    PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE"
    UNSUPPORTED_MEDIA_TYPE = "UNSUPPORTED_MEDIA_TYPE"
    PRECONDITION_REQUIRED = "PRECONDITION_REQUIRED"
    VISITOR_QUOTA_EXCEEDED = "VISITOR_QUOTA_EXCEEDED"
    RATE_LIMITED = "RATE_LIMITED"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    LLM_UNAVAILABLE = "LLM_UNAVAILABLE"
    STT_UNAVAILABLE = "STT_UNAVAILABLE"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    LLM_TIMEOUT = "LLM_TIMEOUT"
    # Codes techniques ajoutés par SA-7 (absents du catalogue SA-5, à valider) :
    # réponses génériques de Starlette quand aucune route ne gère le cas.
    BAD_REQUEST = "BAD_REQUEST"
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"


#: Statut HTTP et message français par défaut de chaque code (SA-5 §1.4).
ERROR_CATALOGUE: dict[ErrorCode, tuple[int, str]] = {
    ErrorCode.VALIDATION_ERROR: (422, "Les données envoyées sont invalides."),
    ErrorCode.INVALID_TOKEN: (422, "Le jeton fourni est invalide ou expiré."),
    ErrorCode.CONSENT_REQUIRED: (422, "Un consentement explicite est requis."),
    ErrorCode.TRANSCRIPTION_FAILED: (422, "Le message vocal n'a pas pu être compris."),
    ErrorCode.UNAUTHENTICATED: (401, "Authentification requise."),
    ErrorCode.INVALID_CREDENTIALS: (401, "E-mail ou mot de passe incorrect."),
    ErrorCode.FORBIDDEN: (403, "Vous n'avez pas les droits pour cette action."),
    ErrorCode.FOUR_EYES_REQUIRED: (
        403,
        "La publication doit être faite par une autre personne que celle qui a soumis.",
    ),
    ErrorCode.CONSENT_NOT_GIVEN: (403, "Le candidat n'a pas autorisé cet accès."),
    ErrorCode.ACCOUNT_DISABLED: (403, "Ce compte est désactivé."),
    ErrorCode.ACCOUNT_NOT_VERIFIED: (403, "Vérifiez votre adresse e-mail pour continuer."),
    ErrorCode.SESSION_NOT_OWNED: (
        403,
        "Cette session visiteur n'appartient pas à ce navigateur.",
    ),
    ErrorCode.NOT_FOUND: (404, "Ressource introuvable."),
    ErrorCode.CONFLICT: (409, "La ressource est dans un état incompatible."),
    ErrorCode.EMAIL_ALREADY_USED: (409, "Un compte existe déjà avec cet e-mail."),
    ErrorCode.ALREADY_ATTACHED: (409, "Cette session est déjà rattachée à un compte."),
    ErrorCode.INVALID_STATUS_TRANSITION: (409, "Cette transition de statut n'est pas autorisée."),
    ErrorCode.ACADEMIC_YEAR_REQUIRED: (422, "Précisez l'année universitaire."),
    ErrorCode.CAMPAIGN_CLOSED: (
        409,
        "Aucune campagne d'admission ouverte pour cette formation.",
    ),
    ErrorCode.DUPLICATE_PREREGISTRATION: (
        409,
        "Une pré-inscription active existe déjà pour cette formation.",
    ),
    ErrorCode.SLOT_UNAVAILABLE: (409, "Ce créneau n'est plus disponible."),
    ErrorCode.VALIDITY_OVERLAP: (
        409,
        "La période de validité chevauche une donnée déjà publiée.",
    ),
    ErrorCode.NOT_INDEXED_YET: (
        409,
        "Cette version n'est pas encore indexée : publication impossible.",
    ),
    ErrorCode.CONVERSATION_CLOSED: (409, "Cette conversation est fermée."),
    ErrorCode.QCM_NOT_AVAILABLE: (409, "Le QCM n'est pas disponible dans cet état."),
    ErrorCode.DOCUMENT_LOCKED: (409, "Ce document ne peut plus être modifié."),
    ErrorCode.IDEMPOTENCY_KEY_CONFLICT: (
        409,
        "Cette clé d'idempotence a déjà servi pour une autre requête.",
    ),
    ErrorCode.SESSION_EXPIRED: (410, "Votre session visiteur a expiré."),
    ErrorCode.QCM_EXPIRED: (410, "Le délai du QCM est dépassé."),
    ErrorCode.PRECONDITION_FAILED: (412, "La ressource a été modifiée entre-temps."),
    ErrorCode.PAYLOAD_TOO_LARGE: (413, "Fichier trop volumineux."),
    ErrorCode.UNSUPPORTED_MEDIA_TYPE: (415, "Format de fichier non pris en charge."),
    ErrorCode.PRECONDITION_REQUIRED: (428, "L'en-tête If-Match est obligatoire."),
    ErrorCode.VISITOR_QUOTA_EXCEEDED: (
        429,
        "Limite de messages atteinte pour une session visiteur.",
    ),
    ErrorCode.RATE_LIMITED: (429, "Trop de requêtes, réessayez plus tard."),
    ErrorCode.INTERNAL_ERROR: (500, "Erreur interne. Référence : request_id."),
    ErrorCode.LLM_UNAVAILABLE: (503, "L'assistant est momentanément indisponible."),
    ErrorCode.STT_UNAVAILABLE: (
        503,
        "La transcription vocale est momentanément indisponible.",
    ),
    ErrorCode.SERVICE_UNAVAILABLE: (503, "Service momentanément indisponible."),
    ErrorCode.LLM_TIMEOUT: (504, "L'assistant a mis trop de temps à répondre."),
    ErrorCode.BAD_REQUEST: (400, "Requête invalide."),
    ErrorCode.METHOD_NOT_ALLOWED: (405, "Méthode non autorisée pour cette ressource."),
}

#: Statut HTTP brut (levé par Starlette/FastAPI) → code SA-5.
_STATUS_TO_CODE: dict[int, ErrorCode] = {
    400: ErrorCode.BAD_REQUEST,
    401: ErrorCode.UNAUTHENTICATED,
    403: ErrorCode.FORBIDDEN,
    404: ErrorCode.NOT_FOUND,
    405: ErrorCode.METHOD_NOT_ALLOWED,
    409: ErrorCode.CONFLICT,
    412: ErrorCode.PRECONDITION_FAILED,
    413: ErrorCode.PAYLOAD_TOO_LARGE,
    415: ErrorCode.UNSUPPORTED_MEDIA_TYPE,
    422: ErrorCode.VALIDATION_ERROR,
    428: ErrorCode.PRECONDITION_REQUIRED,
    429: ErrorCode.RATE_LIMITED,
    503: ErrorCode.SERVICE_UNAVAILABLE,
    504: ErrorCode.LLM_TIMEOUT,
}

Details = dict[str, Any] | list[dict[str, Any]] | None


class AppError(Exception):
    """Erreur métier ou technique prévue, rendue au format SA-5.

    Exemple :
        raise AppError(ErrorCode.INVALID_STATUS_TRANSITION,
                       details={"current_status": "draft", "allowed": ["submitted"]})
    """

    def __init__(
        self,
        code: ErrorCode | str,
        http_status: int | None = None,
        message: str | None = None,
        details: Details = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.code = ErrorCode(code)
        default_status, default_message = ERROR_CATALOGUE[self.code]
        self.http_status = http_status or default_status
        self.message = message or default_message
        self.details = details
        self.headers = headers
        super().__init__(f"{self.code}: {self.message}")


def error_body(code: ErrorCode | str, message: str, details: Details = None) -> dict[str, Any]:
    """Construit le corps JSON SA-5 avec le request_id courant."""
    return {
        "error": {
            "code": str(code),
            "message": message,
            "details": details,
            "request_id": get_request_id(),
        }
    }


def error_response(
    code: ErrorCode,
    http_status: int | None = None,
    message: str | None = None,
    details: Details = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Réponse JSON d'erreur au format SA-5."""
    default_status, default_message = ERROR_CATALOGUE[code]
    return JSONResponse(
        status_code=http_status or default_status,
        content=error_body(code, message or default_message, details),
        headers=headers,
    )


# Correspondance des types d'erreurs Pydantic vers les « issue » de SA-5.
_ISSUE_ALIASES: dict[str, str] = {"missing": "required"}
_LOCATIONS = {"body", "query", "path", "header", "cookie"}


def _validation_details(exc: RequestValidationError) -> list[dict[str, Any]]:
    """Réécrit les erreurs Pydantic en `[{"field", "issue", "location"}]` (sans valeur saisie)."""
    details: list[dict[str, Any]] = []
    for err in exc.errors():
        loc = [str(part) for part in err.get("loc", ())]
        location = loc[0] if loc and loc[0] in _LOCATIONS else None
        field_parts = loc[1:] if location else loc
        error_type = str(err.get("type", "invalid"))
        details.append(
            {
                "field": ".".join(field_parts) or None,
                "issue": _ISSUE_ALIASES.get(error_type, error_type),
                "location": location,
            }
        )
    return details


async def _app_error_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    return error_response(exc.code, exc.http_status, exc.message, exc.details, exc.headers)


async def _validation_error_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    return error_response(ErrorCode.VALIDATION_ERROR, details=_validation_details(exc))


async def _http_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    code = _STATUS_TO_CODE.get(exc.status_code)
    headers = getattr(exc, "headers", None)
    if code is None:
        # Statut non prévu : on garde le statut, avec un code générique sans fuite du détail.
        code = ErrorCode.INTERNAL_ERROR if exc.status_code >= 500 else ErrorCode.BAD_REQUEST
        return error_response(code, http_status=exc.status_code, headers=headers)
    return error_response(code, http_status=exc.status_code, headers=headers)


def unhandled_error_response(exc: BaseException) -> JSONResponse:
    """500 INTERNAL_ERROR : la trace va dans les journaux, jamais dans la réponse."""
    logger.error("Erreur non gérée", exc_info=exc)
    return error_response(ErrorCode.INTERNAL_ERROR)


def register_error_handlers(app: FastAPI) -> None:
    """Branche les gestionnaires globaux. Les exceptions non prévues (500) sont
    interceptées par `RequestIdMiddleware` pour garder l'en-tête X-Request-ID."""
    app.add_exception_handler(AppError, _app_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)
