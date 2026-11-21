"""Identifiant de requête (`X-Request-ID`, SA-5 §1.1).

- Repris de l'en-tête entrant s'il est sûr (lettres, chiffres, `_ . -`, 128 car. max),
  sinon créé par le serveur (`req_` + 32 caractères hexadécimaux).
- Disponible partout via `get_request_id()` (variable de contexte) et `request.state.request_id`.
- Renvoyé dans l'en-tête de **chaque** réponse, y compris les erreurs 500.
"""

from __future__ import annotations

import re
import uuid
from contextvars import ContextVar

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "X-Request-ID"
_SAFE_ID = re.compile(r"^[A-Za-z0-9_.\-]{1,128}$")

_request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


def new_request_id() -> str:
    return f"req_{uuid.uuid4().hex}"


def get_request_id() -> str | None:
    """Identifiant de la requête en cours (None hors requête)."""
    return _request_id_var.get()


class RequestIdMiddleware:
    """Middleware ASGI : pose le request_id, l'ajoute à la réponse et convertit toute
    exception non gérée en 500 INTERNAL_ERROR au format SA-5 (sans trace)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = None
        for name, value in scope.get("headers", []):
            if name == b"x-request-id":
                incoming = value.decode("latin-1")
                break
        request_id = incoming if incoming and _SAFE_ID.match(incoming) else new_request_id()

        token = _request_id_var.set(request_id)
        scope.setdefault("state", {})["request_id"] = request_id
        response_started = False

        async def send_with_id(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
                headers = MutableHeaders(scope=message)
                headers[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        except Exception as exc:
            if response_started:
                # La réponse est déjà partie (ex. flux SSE) : on ne peut que relancer.
                raise
            # Import local : évite un import circulaire errors ↔ request_id.
            from app.core.errors import unhandled_error_response

            response = unhandled_error_response(exc)
            await response(scope, receive, send_with_id)
        finally:
            _request_id_var.reset(token)
