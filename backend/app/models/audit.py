"""Journaux transverses (SA-13 §4.G et §4.H) : `status_history`, `agent_action_log`,
`idempotency_key`.

`status_history` et `agent_action_log` sont **append-only** pour le rôle applicatif : la
migration retire UPDATE et DELETE à `smartcampus_app` (seul le job de purge, exécuté par le
propriétaire, peut effacer `arguments` / `result` après 90 jours, D33).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    SmallInteger,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models import enums
from app.models._common import (
    TZ,
    CreatedAt,
    Str,
    StrNull,
    Timestamps,
    UUIDPrimaryKey,
    enum_check,
    enum_check_null,
    fk,
)


class StatusHistory(UUIDPrimaryKey, CreatedAt, Base):
    """Journal polymorphe et append-only des transitions de statut (qui, quand, humain ou agent)."""

    __tablename__ = "status_history"

    entity_type: Mapped[Str]
    entity_id: Mapped[uuid.UUID]
    from_status: Mapped[StrNull]
    to_status: Mapped[Str]
    actor_type: Mapped[Str]
    actor_user_id: Mapped[uuid.UUID | None] = fk("user_account.id")
    requires_human: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    reason: Mapped[StrNull]
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, server_default=text("'{}'::jsonb")
    )
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        enum_check("entity_type", enums.STATUS_ENTITY_TYPE),
        enum_check("actor_type", enums.ACTOR_TYPE),
        CheckConstraint(
            "NOT requires_human OR (actor_type = 'staff' AND actor_user_id IS NOT NULL)",
            name="human_actor",
        ),
        Index(None, "entity_type", "entity_id", "changed_at"),
        Index(None, "actor_user_id"),
    )


class AgentActionLog(UUIDPrimaryKey, CreatedAt, Base):
    """Une étape d'agent (appel LLM, outil, recherche, STT…) : latence, jetons, coût, erreurs."""

    __tablename__ = "agent_action_log"

    conversation_id: Mapped[uuid.UUID | None] = fk("conversation.id", ondelete="SET NULL")
    message_id: Mapped[uuid.UUID | None] = fk("message.id", ondelete="SET NULL")
    request_id: Mapped[StrNull]
    agent: Mapped[Str]
    step_type: Mapped[Str]
    tool_name: Mapped[StrNull]
    tool_kind: Mapped[StrNull]
    call_id: Mapped[StrNull]
    arguments: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    result: Mapped[Any | None] = mapped_column(JSONB)
    result_summary: Mapped[StrNull]
    status: Mapped[Str]
    error_code: Mapped[StrNull]
    duration_ms: Mapped[int] = mapped_column(Integer)
    model_name: Mapped[StrNull]
    prompt_version: Mapped[StrNull]
    tokens_in: Mapped[int | None] = mapped_column(Integer)
    tokens_out: Mapped[int | None] = mapped_column(Integer)
    cost_estimate_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    actor_type: Mapped[Str]
    actor_user_id: Mapped[uuid.UUID | None] = fk("user_account.id")
    visitor_session_id: Mapped[uuid.UUID | None] = fk("visitor_session.id", ondelete="SET NULL")
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        enum_check("step_type", enums.AGENT_STEP_TYPE),
        enum_check_null("tool_kind", enums.AGENT_TOOL_KIND),
        enum_check("status", enums.AGENT_STEP_STATUS),
        CheckConstraint("duration_ms >= 0", name="duration_ms"),
        CheckConstraint("tokens_in >= 0", name="tokens_in"),
        CheckConstraint("tokens_out >= 0", name="tokens_out"),
        CheckConstraint("cost_estimate_usd >= 0", name="cost_estimate_usd"),
        enum_check("actor_type", enums.ACTOR_TYPE),
        Index(None, "conversation_id", "occurred_at"),
        Index(None, "tool_name", "occurred_at"),
        Index(
            "ix_agent_action_log_errors",
            "occurred_at",
            postgresql_where=text("status <> 'succeeded'"),
        ),
        Index(None, "message_id"),
        Index(None, "visitor_session_id"),
    )


class IdempotencyKey(UUIDPrimaryKey, Timestamps, Base):
    """Mémoire des requêtes à effet métier (en-tête Idempotency-Key, rejeu pendant 24 h)."""

    __tablename__ = "idempotency_key"

    user_id: Mapped[uuid.UUID | None] = fk("user_account.id", ondelete="CASCADE")
    visitor_session_id: Mapped[uuid.UUID | None] = fk("visitor_session.id", ondelete="CASCADE")
    idempotency_key: Mapped[uuid.UUID]
    method: Mapped[Str]
    route: Mapped[Str]
    request_hash: Mapped[bytes] = mapped_column(LargeBinary)
    state: Mapped[Str]
    response_status: Mapped[int | None] = mapped_column(SmallInteger)
    response_body: Mapped[Any | None] = mapped_column(JSONB)
    expires_at: Mapped[TZ]

    __table_args__ = (
        enum_check("state", enums.IDEMPOTENCY_STATE),
        CheckConstraint("num_nonnulls(user_id, visitor_session_id) = 1", name="caller"),
        CheckConstraint(
            "state = 'in_progress' OR response_status BETWEEN 200 AND 499", name="response"
        ),
        Index(
            "uq_idempotency_key_caller_key",
            text("COALESCE(user_id, visitor_session_id)"),
            "idempotency_key",
            unique=True,
        ),
        Index(None, "expires_at"),
        Index(None, "user_id"),
        Index(None, "visitor_session_id"),
    )
