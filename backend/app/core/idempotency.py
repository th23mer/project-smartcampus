"""Middleware d'idempotence commun (SA-5 §1.6, D8 ; table `idempotency_key` de SA-13/SA-17).

Principe (requêtes `POST`, `PUT`, `PATCH`, `DELETE` portant l'en-tête `Idempotency-Key`) :

1. l'appelant est identifié par le backend d'authentification actif (le même que les routes) ;
2. une ligne `in_progress` est réservée pour le couple (appelant, clé), avec la méthode, le
   chemin et l'empreinte SHA-256 de la requête (requête + corps JSON canonique) ;
3. la route s'exécute ; sa réponse (statut, corps JSON, en-têtes `ETag` / `Location`) est
   mémorisée **24 h** (`expires_at`) ;
4. même clé + même requête → la réponse d'origine est **rejouée** avec
   `Idempotent-Replayed: true`, sans réexécuter la route ;
5. même clé + requête différente, ou requête identique encore en cours →
   `409 IDEMPOTENCY_KEY_CONFLICT` (`details.reason` = `request_mismatch` / `in_progress`).

Ne sont **pas** mémorisées (le client peut réessayer avec la même clé) : les réponses 5xx
(SA-5), et les réponses qui dépendent d'en-têtes hors empreinte ou de l'état de
l'authentification (401, 403, 408, 412, 428, 429), ainsi que les réponses non JSON (flux).

**Clé obligatoire** (SA-5 D8, « idem. » des tableaux SA-5 §2) : tout `POST` sous
`/staff/catalogue/` (création, soumission, publication, rejet, archivage, nouvelle version,
révision). Sans clé → `422 VALIDATION_ERROR` (`field = Idempotency-Key`, `location = header`).
Pour respecter l'ordre de SA-5 §1.3 (identification, puis rôle), le contrôle n'est fait que si
l'appelant est identifié et détient un rôle de rédaction ou de relecture ; sinon la route
répond elle-même 401 / 403.

Les visiteurs (cookie `sc_visitor`, E3) ne sont pas encore identifiés par le backend
d'authentification : leurs requêtes passent sans mémorisation (à brancher par E3 via
`visitor_session_id`). Un appelant absent de `user_account` (auth simulée) passe aussi sans
mémorisation : la route le refuse elle-même (F9 de SA-21).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.db import get_session
from app.core.errors import AppError, ErrorCode, error_response
from app.core.request_id import get_request_id
from app.core.security import CurrentUser, Role, resolve_auth_backend

logger = logging.getLogger("app.idempotency")

IDEMPOTENCY_HEADER = "Idempotency-Key"
REPLAYED_HEADER = "Idempotent-Replayed"
#: Durée de rejeu (SA-5 §1.6).
REPLAY_TTL = timedelta(hours=24)
#: Méthodes concernées (les GET sont déjà idempotents).
MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
#: Statuts 2xx–4xx non mémorisés : ils dépendent d'en-têtes hors empreinte (If-Match) ou de
#: l'état de l'authentification ; un nouvel essai avec la même clé doit être réexécuté.
NOT_STORED_STATUSES = frozenset({401, 403, 408, 412, 428, 429})
#: En-têtes de réponse rejoués avec le corps.
REPLAYED_RESPONSE_HEADERS = ("etag", "location")


@dataclass(frozen=True)
class MandatoryRule:
    """Routes où la clé est obligatoire : méthode, motif du chemin (après le préfixe d'API)
    et rôles pour lesquels le contrôle s'applique (les autres sont refusés par la route)."""

    method: str
    path: re.Pattern[str]
    roles: frozenset[Role]


#: SA-5 §2, « idem. » : créations et actions à effet métier du catalogue staff.
MANDATORY_RULES: tuple[MandatoryRule, ...] = (
    MandatoryRule(
        "POST",
        re.compile(r"^/staff/catalogue/"),
        frozenset({Role.IIT_ACADEMIC_LEAD, Role.ISB_ACADEMIC_LEAD, Role.DIRECTION}),
    ),
)


def request_fingerprint(method: str, path: str, query: bytes, body: bytes) -> bytes:
    """Empreinte SHA-256 de la requête : méthode, chemin, paramètres triés et corps.

    Un corps JSON est canonisé (clés triées, sans espaces) : `{"a":1,"b":2}` et
    `{"b": 2, "a": 1}` ont la même empreinte.
    """
    try:
        canonical = json.dumps(
            json.loads(body), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    except (ValueError, UnicodeDecodeError):
        canonical = body
    params = b"&".join(sorted(query.split(b"&"))) if query else b""
    digest = hashlib.sha256()
    for part in (method.upper().encode(), path.encode(), params, canonical):
        digest.update(len(part).to_bytes(8, "big"))
        digest.update(part)
    return digest.digest()


def is_mandatory(method: str, relative_path: str, user: CurrentUser) -> bool:
    """La clé est-elle obligatoire pour cet appelant sur cette route ?"""
    return any(
        rule.method == method and rule.path.search(relative_path) and user.roles & rule.roles
        for rule in MANDATORY_RULES
    )


def _missing_key_response() -> Any:
    return error_response(
        ErrorCode.VALIDATION_ERROR,
        message="L'en-tête Idempotency-Key est obligatoire pour cette action.",
        details=[{"field": IDEMPOTENCY_HEADER, "issue": "required", "location": "header"}],
    )


def _invalid_key_response() -> Any:
    return error_response(
        ErrorCode.VALIDATION_ERROR,
        message="L'en-tête Idempotency-Key doit être un UUID.",
        details=[{"field": IDEMPOTENCY_HEADER, "issue": "uuid_parsing", "location": "header"}],
    )


def _conflict_response(reason: str) -> Any:
    message = (
        "Une requête avec cette clé d'idempotence est encore en cours."
        if reason == "in_progress"
        else None
    )
    headers = {"Retry-After": "1"} if reason == "in_progress" else None
    return error_response(
        ErrorCode.IDEMPOTENCY_KEY_CONFLICT,
        message=message,
        details={"reason": reason, "header": IDEMPOTENCY_HEADER},
        headers=headers,
    )


class IdempotencyMiddleware:
    """Middleware ASGI (à placer à l'intérieur de `RequestIdMiddleware`)."""

    def __init__(self, app: ASGIApp, api_prefix: str = "/api/v1") -> None:
        self.app = app
        self.api_prefix = api_prefix

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in MUTATING_METHODS:
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        raw_key = request.headers.get(IDEMPOTENCY_HEADER)
        path: str = scope["path"]
        relative = path[len(self.api_prefix) :] if path.startswith(self.api_prefix) else path

        user = await self._authenticate(request)
        if user is None:
            # Anonyme ou identité invalide : la route répondra 401 / 403 (SA-5 §1.3).
            await self.app(scope, receive, send)
            return

        if raw_key is None:
            if is_mandatory(scope["method"], relative, user):
                await _missing_key_response()(scope, receive, send)
                return
            await self.app(scope, receive, send)
            return

        try:
            key = uuid.UUID(raw_key)
        except ValueError:
            await _invalid_key_response()(scope, receive, send)
            return

        body = await _read_body(receive)
        replay_receive = _replaying_receive(body, receive)
        fingerprint = request_fingerprint(scope["method"], path, scope["query_string"], body)

        try:
            outcome = await self._reserve(scope, user.id, key, scope["method"], path, fingerprint)
        except Exception as exc:  # base non configurée ou injoignable : rien n'est exécuté
            logger.warning("Idempotence indisponible : %s", type(exc).__name__)
            await error_response(
                ErrorCode.SERVICE_UNAVAILABLE,
                details={"checks": {"database": "unavailable"}},
                headers={"Retry-After": "5"},
            )(scope, receive, send)
            return

        if outcome == "unknown_user":
            await self.app(scope, replay_receive, send)
            return
        if isinstance(outcome, _Stored):
            await _replay(outcome)(scope, receive, send)
            return
        if outcome in ("in_progress", "request_mismatch"):
            await _conflict_response(outcome)(scope, receive, send)
            return

        row_id: uuid.UUID = outcome
        capture = _Capture()

        async def send_and_capture(message: Message) -> None:
            capture.feed(message)
            await send(message)

        try:
            await self.app(scope, replay_receive, send_and_capture)
        except BaseException:
            await self._forget(scope, row_id)
            raise
        await self._finish(scope, row_id, capture)

    # --- Étapes ------------------------------------------------------------------------------

    async def _authenticate(self, request: Request) -> CurrentUser | None:
        settings = request.app.state.settings
        try:
            return await resolve_auth_backend(settings).authenticate(request)
        except AppError:
            return None

    async def _reserve(
        self,
        scope: Scope,
        user_id: uuid.UUID,
        key: uuid.UUID,
        method: str,
        path: str,
        fingerprint: bytes,
    ) -> Any:
        """Réserve la clé. Renvoie l'id de la ligne réservée, une réponse mémorisée (`_Stored`),
        `"in_progress"`, `"request_mismatch"` ou `"unknown_user"`."""
        from app.models import IdempotencyKey, UserAccount

        async with _session(scope) as session:
            exists = await session.scalar(select(UserAccount.id).where(UserAccount.id == user_id))
            if exists is None:
                return "unknown_user"
            # Une clé expirée (> 24 h) est oubliée : elle peut resservir.
            await session.execute(
                delete(IdempotencyKey).where(
                    IdempotencyKey.user_id == user_id,
                    IdempotencyKey.idempotency_key == key,
                    IdempotencyKey.expires_at <= func.now(),
                )
            )
            row_id = await session.scalar(
                insert(IdempotencyKey)
                .values(
                    user_id=user_id,
                    idempotency_key=key,
                    method=method,
                    route=path,
                    request_hash=fingerprint,
                    state="in_progress",
                    expires_at=func.now() + REPLAY_TTL,
                )
                .on_conflict_do_nothing()
                .returning(IdempotencyKey.id)
            )
            if row_id is not None:
                await session.commit()
                return row_id
            existing = (
                await session.execute(
                    select(
                        IdempotencyKey.method,
                        IdempotencyKey.route,
                        IdempotencyKey.request_hash,
                        IdempotencyKey.state,
                        IdempotencyKey.response_status,
                        IdempotencyKey.response_body,
                    ).where(
                        IdempotencyKey.user_id == user_id, IdempotencyKey.idempotency_key == key
                    )
                )
            ).first()
            await session.commit()
        if existing is None:  # libérée entre-temps (5xx d'une requête concurrente)
            return "in_progress"
        if (
            existing.method != method
            or existing.route != path
            or bytes(existing.request_hash) != fingerprint
        ):
            return "request_mismatch"
        if existing.state != "completed":
            return "in_progress"
        return _Stored(existing.response_status, existing.response_body)

    async def _finish(self, scope: Scope, row_id: uuid.UUID, capture: _Capture) -> None:
        """Mémorise la réponse, ou libère la clé si elle ne doit pas être rejouée."""
        stored = capture.storable()
        if stored is None:
            await self._forget(scope, row_id)
            return
        from app.models import IdempotencyKey

        try:
            async with _session(scope) as session:
                await session.execute(
                    update(IdempotencyKey)
                    .where(IdempotencyKey.id == row_id)
                    .values(
                        state="completed",
                        response_status=capture.status,
                        response_body=stored,
                    )
                )
                await session.commit()
        except Exception:  # la réponse est déjà partie : on journalise seulement
            logger.exception("Mémorisation de la réponse idempotente impossible")

    async def _forget(self, scope: Scope, row_id: uuid.UUID) -> None:
        from app.models import IdempotencyKey

        try:
            async with _session(scope) as session:
                await session.execute(delete(IdempotencyKey).where(IdempotencyKey.id == row_id))
                await session.commit()
        except Exception:
            logger.exception("Libération de la clé d'idempotence impossible")


# --- Outils internes -----------------------------------------------------------------------------


@dataclass(frozen=True)
class _Stored:
    status: int | None
    envelope: Any


class _Capture:
    """Capture la réponse envoyée au client (statut, en-têtes utiles, corps)."""

    def __init__(self) -> None:
        self.status: int = 0
        self.headers: dict[str, str] = {}
        self.content_type = ""
        self.chunks: list[bytes] = []

    def feed(self, message: Message) -> None:
        if message["type"] == "http.response.start":
            self.status = message["status"]
            for name, value in message.get("headers", []):
                lname = name.decode("latin-1").lower()
                if lname == "content-type":
                    self.content_type = value.decode("latin-1")
                elif lname in REPLAYED_RESPONSE_HEADERS:
                    self.headers[lname] = value.decode("latin-1")
        elif message["type"] == "http.response.body":
            self.chunks.append(message.get("body", b""))

    def storable(self) -> dict[str, Any] | None:
        """Enveloppe `{"body", "headers"}` à mémoriser, ou None si non rejouable."""
        if not 200 <= self.status <= 499 or self.status in NOT_STORED_STATUSES:
            return None
        raw = b"".join(self.chunks)
        if not raw:
            body: Any = None
        elif "json" in self.content_type:
            try:
                body = json.loads(raw)
            except ValueError:
                return None
        else:
            return None
        return {"body": body, "headers": self.headers}


def _replay(stored: _Stored) -> Any:
    """Réponse rejouée : même statut, même corps, `Idempotent-Replayed: true`."""
    from starlette.responses import JSONResponse, Response

    envelope = stored.envelope or {}
    headers = {**envelope.get("headers", {}), REPLAYED_HEADER: "true"}
    body = envelope.get("body")
    status = stored.status or 200
    if body is None:
        return Response(status_code=status, headers=headers)
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        # Une erreur rejouée porte le request_id de l'échange courant (= en-tête X-Request-ID).
        body = {"error": {**body["error"], "request_id": get_request_id()}}
    return JSONResponse(body, status_code=status, headers=headers)


async def _read_body(receive: Receive) -> bytes:
    chunks: list[bytes] = []
    while True:
        message = await receive()
        if message["type"] != "http.request":
            break
        chunks.append(message.get("body", b""))
        if not message.get("more_body", False):
            break
    return b"".join(chunks)


def _replaying_receive(body: bytes, receive: Receive) -> Receive:
    sent = False

    async def _receive() -> Message:
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        return await receive()

    return _receive


@asynccontextmanager
async def _session(scope: Scope) -> AsyncIterator[AsyncSession]:
    """Session SQLAlchemy obtenue comme dans les routes : la dépendance `get_session`, ou sa
    surcharge (`app.dependency_overrides`, utilisée par les tests)."""
    factory: Callable[[], AsyncIterator[AsyncSession]] = scope["app"].dependency_overrides.get(
        get_session, get_session
    )
    gen = factory()
    session = await anext(gen)  # type: ignore[call-overload]
    try:
        yield session
    finally:
        await gen.aclose()  # type: ignore[attr-defined]
