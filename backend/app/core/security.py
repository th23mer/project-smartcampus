"""Interface d'authentification et de contrôle des rôles (SA-7, implémentation SA-28).

**Interface stable** utilisée par les routes :

- `CurrentUser` : utilisateur authentifié (id, rôles, institution_id, candidate_id) ;
- `get_current_user` : dépendance, 401 UNAUTHENTICATED si personne n'est identifié ;
- `get_optional_user` : dépendance, `None` si anonyme (routes publiques personnalisables) ;
- `require_roles(*roles)` : dépendance, 403 FORBIDDEN si aucun des rôles n'est détenu.

**Implémentation (SA-28, E3)** : `JwtAuthBackend` lit `Authorization: Bearer <jeton>`
(JWT HS256 signé avec `JWT_SECRET`, 15 min ; voir `app/core/tokens.py`). Sans cet en-tête :

- en `dev` et `test`, l'authentification simulée `DevHeaderAuthBackend` reste disponible
  (en-têtes `X-Dev-User-Id`, `X-Dev-Roles`, `X-Dev-Institution-Id`) pour les tests et le
  sélecteur de rôle du front ;
- ailleurs, l'appelant est anonyme.

`set_auth_backend(...)` permet toujours de brancher une autre stratégie (tests).
Les visiteurs sans compte (cookie `sc_visitor`) sont identifiés par `app/core/visitor.py`.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Coroutine
from enum import StrEnum
from typing import Annotated, Any, Protocol

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict

from app.core.config import Settings, get_settings
from app.core.errors import AppError, ErrorCode


class Role(StrEnum):
    """Codes de rôle (SA-3 §0.2 `account_type` + `staff_role`, SA-5 §4)."""

    CANDIDATE = "candidate"
    IIT_ACADEMIC_LEAD = "iit_academic_lead"
    ISB_ACADEMIC_LEAD = "isb_academic_lead"
    INTERVIEW_LEAD = "interview_lead"
    DIRECTION = "direction"
    PLATFORM_ADMIN = "platform_admin"


#: Sous-rôles staff (cumulables, SA-3 D15).
STAFF_ROLES: frozenset[Role] = frozenset(Role) - {Role.CANDIDATE}


class CurrentUser(BaseModel):
    """Utilisateur authentifié, transmis aux services et aux outils d'agent."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    roles: frozenset[Role]
    #: Périmètre institutionnel (IIT/ISB) des responsables ; None = tous / sans objet.
    institution_id: uuid.UUID | None = None
    #: Profil candidat (`candidate_profile.id`) s'il existe déjà ; None sinon.
    candidate_id: uuid.UUID | None = None

    @property
    def account_type(self) -> str:
        """`candidate` ou `staff` (SA-3 `account_type`)."""
        return "staff" if self.roles & STAFF_ROLES else "candidate"

    @property
    def is_staff(self) -> bool:
        return bool(self.roles & STAFF_ROLES)

    def has_any_role(self, *roles: Role | str) -> bool:
        return bool(self.roles & {Role(r) for r in roles})


class AuthBackend(Protocol):
    """Stratégie d'authentification. E3 fournit l'implémentation JWT réelle."""

    async def authenticate(self, request: Request) -> CurrentUser | None:
        """Renvoie l'utilisateur, `None` si anonyme ; lève `AppError` si l'identité
        présentée est invalide (jeton expiré, en-têtes mal formés…)."""
        ...


class NoAuthBackend:
    """Aucune authentification disponible : tout le monde est anonyme."""

    async def authenticate(self, request: Request) -> CurrentUser | None:
        return None


class DevHeaderAuthBackend:
    """Authentification simulée par en-têtes `X-Dev-*` (dev et test uniquement)."""

    USER_HEADER = "X-Dev-User-Id"
    ROLES_HEADER = "X-Dev-Roles"
    INSTITUTION_HEADER = "X-Dev-Institution-Id"

    async def authenticate(self, request: Request) -> CurrentUser | None:
        raw_id = request.headers.get(self.USER_HEADER)
        if raw_id is None:
            return None
        try:
            user_id = uuid.UUID(raw_id)
        except ValueError as exc:
            raise _unauthenticated({"header": self.USER_HEADER, "issue": "invalid_uuid"}) from exc

        raw_roles = request.headers.get(self.ROLES_HEADER, "")
        names = [part.strip() for part in raw_roles.split(",") if part.strip()]
        unknown = [name for name in names if name not in Role._value2member_map_]
        if not names or unknown:
            raise _unauthenticated(
                {"header": self.ROLES_HEADER, "issue": "invalid_roles", "unknown": unknown}
            )

        institution_id = None
        raw_inst = request.headers.get(self.INSTITUTION_HEADER)
        if raw_inst:
            try:
                institution_id = uuid.UUID(raw_inst)
            except ValueError as exc:
                raise _unauthenticated(
                    {"header": self.INSTITUTION_HEADER, "issue": "invalid_uuid"}
                ) from exc

        return CurrentUser(
            id=user_id, roles=frozenset(Role(n) for n in names), institution_id=institution_id
        )


class JwtAuthBackend:
    """Jeton d'accès `Authorization: Bearer` (SA-28) ; sans en-tête, délègue à `fallback`."""

    def __init__(self, settings: Settings, fallback: AuthBackend | None = None) -> None:
        self.settings = settings
        self.fallback = fallback

    async def authenticate(self, request: Request) -> CurrentUser | None:
        header = request.headers.get("Authorization")
        if header is None:
            return await self.fallback.authenticate(request) if self.fallback else None
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            raise _unauthenticated({"header": "Authorization", "issue": "invalid_scheme"})
        from app.core.tokens import decode_access_token

        claims = decode_access_token(self.settings, token.strip())
        try:
            roles = frozenset(Role(name) for name in claims.roles)
        except ValueError as exc:
            raise _unauthenticated({"reason": "invalid_token"}) from exc
        if not roles:
            raise _unauthenticated({"reason": "invalid_token"})
        return CurrentUser(
            id=claims.user_id,
            roles=roles,
            institution_id=claims.institution_id,
            candidate_id=claims.candidate_id,
        )


def _unauthenticated(details: dict[str, Any] | None = None) -> AppError:
    return AppError(ErrorCode.UNAUTHENTICATED, details=details)


_auth_backend_override: AuthBackend | None = None


def set_auth_backend(backend: AuthBackend | None) -> None:
    """Branche une autre implémentation (tests). `None` = retour au défaut."""
    global _auth_backend_override
    _auth_backend_override = backend


def resolve_auth_backend(settings: Settings) -> AuthBackend:
    """Backend actif : celui branché par `set_auth_backend`, sinon JWT (+ en-têtes simulés
    en dev/test)."""
    if _auth_backend_override is not None:
        return _auth_backend_override
    fallback = DevHeaderAuthBackend() if settings.dev_auth_enabled else None
    return JwtAuthBackend(settings, fallback)


#: Déclare le schéma « Bearer » dans OpenAPI (bouton Authorize de Swagger). La vérification
#: est faite par le backend d'authentification, pas par cet objet.
bearer_scheme = HTTPBearer(
    auto_error=False,
    scheme_name="bearerAuth",
    description="Jeton d'accès renvoyé par POST /auth/login (15 min).",
)


async def get_optional_user(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    _bearer: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
) -> CurrentUser | None:
    """Utilisateur courant ou `None` (anonyme)."""
    return await resolve_auth_backend(settings).authenticate(request)


async def get_current_user(
    user: Annotated[CurrentUser | None, Depends(get_optional_user)],
) -> CurrentUser:
    """Utilisateur courant ; 401 UNAUTHENTICATED si anonyme."""
    if user is None:
        raise _unauthenticated()
    return user


def require_roles(
    *roles: Role | str,
) -> Callable[..., Coroutine[Any, Any, CurrentUser]]:
    """Dépendance : l'utilisateur doit détenir **au moins un** des rôles (union des droits).

    Usage : `user: Annotated[CurrentUser, Depends(require_roles(Role.DIRECTION))]`
    ou `dependencies=[Depends(require_roles("iit_academic_lead", "direction"))]`.
    """
    if not roles:
        raise ValueError("require_roles() exige au moins un rôle.")
    allowed = frozenset(Role(r) for r in roles)  # ValueError si code inconnu

    async def _dependency(
        user: Annotated[CurrentUser, Depends(get_current_user)],
    ) -> CurrentUser:
        if not user.roles & allowed:
            raise AppError(ErrorCode.FORBIDDEN)
        return user

    return _dependency


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]
OptionalUserDep = Annotated[CurrentUser | None, Depends(get_optional_user)]
