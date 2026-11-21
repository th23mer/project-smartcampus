"""Radar des lacunes de connaissance F8 (SA-13 §4.H) : `knowledge_gap`, `knowledge_gap_question`.

Une question sans source officielle est enregistrée par l'outil `log_knowledge_gap`, avec un
embedding (même dimension que `document_chunk.embedding`, SA-14 D2) pour le regroupement.
"""

from __future__ import annotations

import uuid
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import CheckConstraint, Index, Integer, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

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
from app.models.documents import EMBEDDING_DIM


class KnowledgeGap(UUIDPrimaryKey, Timestamps, Base):
    """Groupe de questions sans réponse officielle ; clôture par un humain."""

    __tablename__ = "knowledge_gap"

    cluster_label: Mapped[Str]
    institution_id: Mapped[uuid.UUID | None] = fk("institution.id")
    status: Mapped[str] = mapped_column(Text, server_default=text("'open'"))
    question_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    example_questions: Mapped[list[Any]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    first_seen_at: Mapped[TZ]
    last_seen_at: Mapped[TZ]
    clustered_at: Mapped[TZNull]
    resolution_document_id: Mapped[uuid.UUID | None] = fk("document.id")
    resolution_entity: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    resolution_comment: Mapped[StrNull]
    resolved_by: Mapped[uuid.UUID | None] = fk("user_account.id")
    resolved_at: Mapped[TZNull]

    __table_args__ = (
        enum_check("status", enums.KNOWLEDGE_GAP_STATUS),
        CheckConstraint("question_count >= 0", name="question_count"),
        CheckConstraint(
            "status NOT IN ('resolved','dismissed') OR resolved_by IS NOT NULL",
            name="human_resolution",
        ),
        Index(None, "status", text("last_seen_at DESC")),
        Index(None, "institution_id"),
    )


class KnowledgeGapQuestion(UUIDPrimaryKey, Timestamps, Base):
    """Une question sans réponse officielle (texte nettoyé des données personnelles)."""

    __tablename__ = "knowledge_gap_question"

    knowledge_gap_id: Mapped[uuid.UUID] = fk("knowledge_gap.id", nullable=False)
    message_id: Mapped[uuid.UUID | None] = fk("message.id", ondelete="SET NULL")
    question_text: Mapped[Str]
    language: Mapped[StrNull]
    grounding: Mapped[Str]
    embedding: Mapped[Any | None] = mapped_column(Vector(EMBEDDING_DIM))
    asked_at: Mapped[TZ]

    __table_args__ = (
        enum_check_null("language", enums.LANG_CODE),
        CheckConstraint("grounding IN ('no_official_source','partial')", name="grounding"),
        Index(None, "knowledge_gap_id"),
        Index(None, "message_id"),
        Index(
            "ix_knowledge_gap_question_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )
