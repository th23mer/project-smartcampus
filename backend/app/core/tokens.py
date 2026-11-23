"""Jetons d'authentification (SA-28) : accès JWT signé + renouvellement opaque.

- **Jeton d'accès** (`Authorization: Bearer`) : JWT HS256, 15 min, claims `sub`,
  `account_type`, `roles`, `candidate_id`, `institution_id` (SA-5 §1.2). Il n'est pas relu
  en base à chaque requête : les rôles sont relus à chaque renouvellement, donc un retrait
  de rôle prend effet en 15 min au plus (SA-5 §4).
- **Jeton de renouvellement** (cookie `sc_refresh`) : chaîne aléatoire opaque ; seul son
  hachage SHA-256 est stocké (table `refresh_token`).
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

from app.core.config import Settings
from app.core.errors import AppError, ErrorCode

JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_TYPE = "access"


@dataclass(frozen=True)
class AccessClaims:
    """Contenu utile d'un jeton d'accès vérifié."""

    user_id: uuid.UUID
    account_type: str
    roles: tuple[str, ...]
    candidate_id: uuid.UUID | None
    institution_id: uuid.UUID | None


def _secret(settings: Settings) -> str:
    if settings.jwt_secret is None:
        raise AppError(
            ErrorCode.SERVICE_UNAVAILABLE,
            message="L'authentification n'est pas configurée (JWT_SECRET absent).",
            details={"checks": {"jwt_secret": "missing"}},
        )
    return settings.jwt_secret.get_secret_value()


def create_access_token(
    settings: Settings,
    *,
    user_id: uuid.UUID,
    account_type: str,
    roles: list[str],
    candidate_id: uuid.UUID | None,
    institution_id: uuid.UUID | None,
    now: datetime | None = None,
) -> str:
    now = now or datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "typ": ACCESS_TOKEN_TYPE,
        "iss": settings.jwt_issuer,
        "iat": now,
        "exp": now + timedelta(seconds=settings.access_token_ttl_s),
        "account_type": account_type,
        "roles": sorted(roles),
        "candidate_id": str(candidate_id) if candidate_id else None,
        "institution_id": str(institution_id) if institution_id else None,
    }
    return jwt.encode(payload, _secret(settings), algorithm=JWT_ALGORITHM)


def decode_access_token(settings: Settings, token: str) -> AccessClaims:
    """Vérifie signature, émetteur, expiration et type ; 401 UNAUTHENTICATED sinon."""
    if settings.jwt_secret is None:
        raise AppError(ErrorCode.UNAUTHENTICATED, details={"reason": "auth_not_configured"})
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[JWT_ALGORITHM],
            issuer=settings.jwt_issuer,
            options={"require": ["sub", "exp", "iat", "iss", "typ"]},
        )
        if payload.get("typ") != ACCESS_TOKEN_TYPE:
            raise jwt.InvalidTokenError("type")
        roles = payload.get("roles")
        if not isinstance(roles, list) or not all(isinstance(r, str) for r in roles):
            raise jwt.InvalidTokenError("roles")
        return AccessClaims(
            user_id=uuid.UUID(payload["sub"]),
            account_type=str(payload.get("account_type")),
            roles=tuple(roles),
            candidate_id=_opt_uuid(payload.get("candidate_id")),
            institution_id=_opt_uuid(payload.get("institution_id")),
        )
    except jwt.ExpiredSignatureError as exc:
        raise AppError(ErrorCode.UNAUTHENTICATED, details={"reason": "token_expired"}) from exc
    except (jwt.InvalidTokenError, ValueError, TypeError, KeyError) as exc:
        raise AppError(ErrorCode.UNAUTHENTICATED, details={"reason": "invalid_token"}) from exc


def _opt_uuid(value: Any) -> uuid.UUID | None:
    return uuid.UUID(value) if value else None


def new_opaque_token() -> str:
    """Jeton aléatoire (256 bits) pour un cookie : session visiteur ou renouvellement."""
    return secrets.token_urlsafe(32)


def hash_opaque_token(token: str) -> bytes:
    """Hachage stocké en base (SHA-256) ; le jeton lui-même n'est jamais conservé."""
    return hashlib.sha256(token.encode("utf-8")).digest()
