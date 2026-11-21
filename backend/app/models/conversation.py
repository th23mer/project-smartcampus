"""Sessions visiteurs, conversations, messages et retours (SA-13 §4.B et §4.H).

Une conversation appartient à une session visiteur **ou** à un compte (CHECK `owner`). Les
messages portent la traçabilité IA (modèle, version de prompt, jetons, latence) et l'audio
est purgé à 7 jours (C7) par un job `purge`.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import (
    REAL,
    CheckConstraint,
    Index,
    Integer,
    LargeBinary,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models import enums
from app.models._common import (
    TZ,
    Str,
    StrNull,
    Timestamps,
    TZNull,
    UUIDPrimaryKey,
    enum_check,
    enum_check_null,
    fk,
)


class VisitorSession(UUIDPrimaryKey, Timestamps, Base):
    """Session temporaire d'un visiteur sans compte : jeton haché, TTL, quotas (D-D)."""

    __tablename__ = "visitor_session"

    token_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    status: Mapped[str] = mapped_column(Text, server_default=text("'active'"))
    last_seen_at: Mapped[TZ]
    idle_expires_at: Mapped[TZ]
    hard_expires_at: Mapped[TZ]
    message_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    audio_seconds: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    llm_tokens: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    quota_window_start: Mapped[TZ]
    client_fingerprint_hash: Mapped[bytes | None] = mapped_column(LargeBinary)
    detected_language: Mapped[StrNull]
    attached_user_id: Mapped[uuid.UUID | None] = fk("user_account.id")
    attached_at: Mapped[TZNull]
    purged_at: Mapped[TZNull]

    __table_args__ = (
        enum_check("status", enums.VISITOR_SESSION_STATUS),
        CheckConstraint("message_count >= 0", name="message_count"),
        CheckConstraint("audio_seconds >= 0", name="audio_seconds"),
        CheckConstraint("llm_tokens >= 0", name="llm_tokens"),
        enum_check_null("detected_language", enums.LANG_CODE),
        CheckConstraint("hard_expires_at > created_at", name="hard_expiry"),
        CheckConstraint("(status = 'attached') = (attached_user_id IS NOT NULL)", name="attached"),
        Index(None, "status", "idle_expires_at"),
        Index(None, "attached_user_id"),
    )


class Conversation(UUIDPrimaryKey, Timestamps, Base):
    """Fil de discussion ; synthèse IA = seule vue du staff sans consentement (D-F)."""

    __tablename__ = "conversation"

    visitor_session_id: Mapped[uuid.UUID | None] = fk("visitor_session.id", ondelete="CASCADE")
    user_id: Mapped[uuid.UUID | None] = fk("user_account.id")
    origin_visitor_session_id: Mapped[uuid.UUID | None] = fk(
        "visitor_session.id", ondelete="SET NULL"
    )
    channel: Mapped[str] = mapped_column(Text, server_default=text("'text'"))
    detected_language: Mapped[StrNull]
    status: Mapped[str] = mapped_column(Text, server_default=text("'open'"))
    title: Mapped[StrNull]
    summary: Mapped[StrNull]
    summary_model: Mapped[StrNull]
    summary_updated_at: Mapped[TZNull]
    message_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    last_message_at: Mapped[TZNull]

    messages: Mapped[list[Message]] = relationship(
        back_populates="conversation", lazy="raise", passive_deletes=True
    )

    __table_args__ = (
        enum_check("channel", enums.CHANNEL),
        enum_check_null("detected_language", enums.LANG_CODE),
        enum_check("status", enums.CONVERSATION_STATUS),
        CheckConstraint("message_count >= 0", name="message_count"),
        CheckConstraint("num_nonnulls(visitor_session_id, user_id) = 1", name="owner"),
        Index(None, "visitor_session_id"),
        Index("ix_conversation_user_last_message", "user_id", text("last_message_at DESC")),
        Index(None, "origin_visitor_session_id"),
    )


class ConversationAttachment(UUIDPrimaryKey, Timestamps, Base):
    """Offre de rattachement d'une session visiteur à un compte (SA-29)."""

    __tablename__ = "conversation_attachment"

    visitor_session_id: Mapped[uuid.UUID] = fk(
        "visitor_session.id", nullable=False, ondelete="CASCADE"
    )
    user_id: Mapped[uuid.UUID] = fk("user_account.id", nullable=False)
    status: Mapped[str] = mapped_column(Text, server_default=text("'offered'"))
    offered_at: Mapped[TZ] = mapped_column(server_default=text("now()"))
    offer_expires_at: Mapped[TZ]
    ownership_checked_at: Mapped[TZNull]
    consent_id: Mapped[uuid.UUID | None] = fk("consent.id")
    conversations_moved: Mapped[int | None] = mapped_column(Integer)
    resolved_at: Mapped[TZNull]

    __table_args__ = (
        enum_check("status", enums.CONVERSATION_ATTACHMENT_STATUS),
        CheckConstraint("conversations_moved >= 0", name="conversations_moved"),
        CheckConstraint(
            "status <> 'attached' OR (consent_id IS NOT NULL AND ownership_checked_at IS NOT NULL)",
            name="attached_proof",
        ),
        Index(
            "uq_conversation_attachment_attached",
            "visitor_session_id",
            unique=True,
            postgresql_where=text("status = 'attached'"),
        ),
        Index(None, "user_id"),
        Index(None, "consent_id"),
    )


class Message(UUIDPrimaryKey, Timestamps, Base):
    """Un tour de dialogue (mémoire, audit des sources, évaluation)."""

    __tablename__ = "message"

    conversation_id: Mapped[uuid.UUID] = fk("conversation.id", nullable=False, ondelete="CASCADE")
    seq: Mapped[int] = mapped_column(Integer)
    client_message_id: Mapped[uuid.UUID | None]
    role: Mapped[Str]
    content: Mapped[StrNull]
    input_modality: Mapped[str] = mapped_column(Text, server_default=text("'text'"))
    audio_storage_path: Mapped[StrNull]
    audio_purge_at: Mapped[TZNull]
    audio_duration_ms: Mapped[int | None] = mapped_column(Integer)
    transcript_raw: Mapped[StrNull]
    stt_confidence: Mapped[float | None] = mapped_column(REAL)
    detected_language: Mapped[StrNull]
    reply_language: Mapped[StrNull]
    language_confidence: Mapped[float | None] = mapped_column(REAL)
    sources: Mapped[list[Any]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    tool_calls: Mapped[list[Any] | None] = mapped_column(JSONB)
    tool_call_id: Mapped[StrNull]
    tool_name: Mapped[StrNull]
    grounding: Mapped[StrNull]
    knowledge_gap_id: Mapped[uuid.UUID | None] = fk("knowledge_gap.id", ondelete="SET NULL")
    finish_reason: Mapped[StrNull]
    model_name: Mapped[StrNull]
    prompt_version: Mapped[StrNull]
    tokens_in: Mapped[int | None] = mapped_column(Integer)
    tokens_out: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)

    conversation: Mapped[Conversation] = relationship(back_populates="messages", lazy="raise")

    __table_args__ = (
        UniqueConstraint("conversation_id", "seq"),
        UniqueConstraint("conversation_id", "client_message_id"),
        enum_check("role", enums.MESSAGE_ROLE),
        CheckConstraint("input_modality IN ('text','audio')", name="input_modality"),
        CheckConstraint("audio_duration_ms > 0", name="audio_duration_ms"),
        CheckConstraint("stt_confidence BETWEEN 0 AND 1", name="stt_confidence"),
        enum_check_null("detected_language", enums.LANG_CODE),
        enum_check_null("reply_language", enums.LANG_CODE),
        CheckConstraint("language_confidence BETWEEN 0 AND 1", name="language_confidence"),
        enum_check_null("grounding", enums.GROUNDING),
        enum_check_null("finish_reason", enums.FINISH_REASON),
        CheckConstraint("tokens_in >= 0", name="tokens_in"),
        CheckConstraint("tokens_out >= 0", name="tokens_out"),
        CheckConstraint("latency_ms >= 0", name="latency_ms"),
        CheckConstraint("(role = 'tool') = (tool_call_id IS NOT NULL)", name="tool_call"),
        CheckConstraint(
            "grounding IS DISTINCT FROM 'no_official_source' OR knowledge_gap_id IS NOT NULL",
            name="knowledge_gap",
        ),
        CheckConstraint("client_message_id IS NULL OR role = 'user'", name="client_message_id"),
        Index(None, "knowledge_gap_id", postgresql_where=text("knowledge_gap_id IS NOT NULL")),
        Index(
            "ix_message_audio_purge",
            "audio_purge_at",
            postgresql_where=text("audio_storage_path IS NOT NULL"),
        ),
    )


class MessageFeedback(UUIDPrimaryKey, Timestamps, Base):
    """Retour (pouce haut/bas) sur une réponse de l'agent ; un seul par message."""

    __tablename__ = "message_feedback"

    message_id: Mapped[uuid.UUID] = fk(
        "message.id", nullable=False, ondelete="CASCADE", unique=True
    )
    rating: Mapped[Str]
    reason: Mapped[StrNull]
    comment: Mapped[StrNull]
    author_user_id: Mapped[uuid.UUID | None] = fk("user_account.id")
    author_visitor_session_id: Mapped[uuid.UUID | None] = fk(
        "visitor_session.id", ondelete="SET NULL"
    )

    __table_args__ = (
        enum_check("rating", enums.FEEDBACK_RATING),
        enum_check_null("reason", enums.FEEDBACK_REASON),
        CheckConstraint("length(comment) <= 1000", name="comment"),
        Index(None, "rating", "created_at"),
        Index(None, "author_user_id"),
        Index(None, "author_visitor_session_id"),
    )
