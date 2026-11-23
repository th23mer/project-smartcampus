"""Point de branchement de la réponse de l'agent (frontière E3 / E4).

E3 (SA-26) enregistre le message de l'utilisateur, compte le quota et prépare la mémoire de
travail ; **E4** (SA-36, SA-37) produit la réponse avec le LLM. Le contrat entre les deux est
`ChatResponder` : E4 branche son implémentation avec `set_chat_responder(...)`, comme
`set_auth_backend` pour l'authentification.

Tant qu'aucun LLM n'est branché, `UnavailableResponder` applique le **secours déterministe**
de SA-5 §3.5 (D-E) : `503 LLM_UNAVAILABLE`, le message de l'utilisateur est conservé, et
`details.fallback` porte un texte fixe (fichier versionné `prompts/`) et des actions
proposées (créer un compte ou prendre rendez-vous, être recontacté). Il n'est jamais généré.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import BACKEND_DIR, REPO_DIR
from app.core.errors import AppError, ErrorCode
from app.models import Conversation, Message
from app.services.conversations import ChatCaller

FALLBACK_PROMPT = "chat_fallback_fr.txt"
#: Le texte de secours est cherché à la racine du dépôt (`prompts/`), puis dans `backend/prompts/`
#: (image Docker du backend, qui ne contient que `backend/`).
PROMPT_DIRS = (REPO_DIR / "prompts", BACKEND_DIR / "prompts")


@dataclass
class AssistantReply:
    """Réponse produite par l'agent (E4)."""

    text: str
    reply_language: str | None = None
    finish_reason: str = "completed"
    grounding: str | None = None
    sources: list[dict[str, Any]] = field(default_factory=list)
    model_name: str | None = None
    prompt_version: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    latency_ms: int | None = None


class ChatResponder(Protocol):
    async def reply(
        self,
        session: AsyncSession,
        caller: ChatCaller,
        conversation: Conversation,
        user_message: Message,
        context: list[dict[str, str]],
    ) -> AssistantReply:
        """Produit la réponse. `context` = mémoire de travail (N derniers messages, inclus
        celui de l'utilisateur). Lève `AppError(LLM_UNAVAILABLE / LLM_TIMEOUT)` en cas d'échec."""
        ...


@lru_cache
def fallback_text() -> str:
    for folder in PROMPT_DIRS:
        path: Path = folder / FALLBACK_PROMPT
        if path.is_file():
            return path.read_text(encoding="utf-8").strip()
    return "Je ne peux pas répondre pour le moment. Tu peux réessayer plus tard."


def fallback_actions(caller: ChatCaller) -> list[dict[str, Any]]:
    first = (
        {
            "type": "create_account",
            "label": "Créer un compte pour être accompagné",
            "requires_confirmation": True,
            "payload": {},
        }
        if caller.is_visitor
        else {
            "type": "book_appointment",
            "label": "Prendre rendez-vous avec un conseiller",
            "requires_confirmation": True,
            "payload": {"appointment_type": "advisory"},
        }
    )
    return [
        first,
        {
            "type": "contact_human",
            "label": "Être recontacté",
            "requires_confirmation": True,
            "payload": {},
        },
    ]


class UnavailableResponder:
    """Aucun LLM branché : secours déterministe (SA-5 §3.5)."""

    RETRY_AFTER_S = 30

    async def reply(
        self,
        session: AsyncSession,
        caller: ChatCaller,
        conversation: Conversation,
        user_message: Message,
        context: list[dict[str, str]],
    ) -> AssistantReply:
        raise AppError(
            ErrorCode.LLM_UNAVAILABLE,
            details={
                "retry_after_s": self.RETRY_AFTER_S,
                "user_message_id": str(user_message.id),
                "fallback": {
                    "text": fallback_text(),
                    "links": [],
                    "suggested_actions": fallback_actions(caller),
                },
            },
            headers={"Retry-After": str(self.RETRY_AFTER_S)},
        )


_responder: ChatResponder | None = None


def set_chat_responder(responder: ChatResponder | None) -> None:
    """E4 branche l'agent ici. `None` = retour au secours déterministe."""
    global _responder
    _responder = responder


def get_chat_responder() -> ChatResponder:
    return _responder or UnavailableResponder()
