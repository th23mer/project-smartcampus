"""Schémas des sessions visiteur, conversations et messages (SA-25, SA-26 ; SA-5 §3, §5.3–5.4)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Language = Literal["fr", "aeb_arab", "aeb_latn", "ar", "en", "mixed", "unknown"]


class Quota(BaseModel):
    """Quota visiteur : messages utilisés dans la fenêtre courante (30 / 24 h, D-D)."""

    messages_used: int
    messages_limit: int
    resets_at: datetime


class VisitorSessionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    locale: Literal["fr", "ar"] | None = None


class VisitorSessionOut(BaseModel):
    id: uuid.UUID
    status: Literal["active", "attached", "expired", "purged"]
    created_at: datetime
    #: Fin de validité : la plus proche entre l'inactivité (24 h) et la durée maximale (7 j).
    expires_at: datetime
    quota: Quota
    #: Profil provisoire extrait en session par l'agent (E4) ; non conservé. Null pour l'instant.
    provisional_profile: dict[str, Any] | None = None


class ConversationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel: Literal["web"] = "web"
    title: str | None = Field(default=None, max_length=200)


class ConversationOut(BaseModel):
    id: uuid.UUID
    owner_type: Literal["visitor", "candidate"]
    status: Literal["open", "closed", "archived"]
    title: str | None
    created_at: datetime
    last_message_at: datetime | None
    message_count: int


class TextContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["text"]
    #: 1 à 2 000 caractères (SA-5 §3.1) ; un texte fait seulement d'espaces est refusé.
    text: str = Field(min_length=1, max_length=2000)


class ChatMessageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: UUID créé par le front : un réessai avec le même identifiant ne duplique pas le message.
    client_message_id: uuid.UUID
    content: TextContent
    language_hint: Language | None = None


class MessageOut(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    role: Literal["user", "assistant", "system_notice"]
    content_type: Literal["text", "audio"]
    text: str | None
    language: Language | None = None
    reply_language: Language | None = None
    transcription: dict[str, Any] | None = None
    audio_expires_at: datetime | None = None
    citations: list[dict[str, Any]] = Field(default_factory=list)
    finish_reason: str | None = None
    created_at: datetime


class ChatReply(BaseModel):
    user_message: MessageOut
    assistant_message: MessageOut
    #: Renseigné pour un visiteur, null pour un candidat (SA-5 §3.2).
    quota: Quota | None = None
