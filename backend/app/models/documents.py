"""Gestion documentaire et RAG (SA-14 §4.1 à §4.4, §4.7).

- Documents officiels : `document` (identité stable), `document_programme` (N-N),
  `document_version` (contenu immuable, publication à 4 yeux, état d'indexation),
  `document_chunk` (copie dérivée : embedding `vector(D)` + `tsv` 'simple', C4/D-K),
  `embedding_model` (un seul actif).
- Pièces des candidats : `candidate_attachment`, **jamais** indexées (aucune FK possible vers
  chunk / sync_job, SA-14 D1).

Le RAG ne lit que la vue `v_searchable_chunk` (posée par la migration, droits SA-16).
"""

from __future__ import annotations

import uuid
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models import enums
from app.models._common import (
    PublicationBlock,
    Str,
    StrNull,
    Timestamps,
    TZNull,
    UUIDPrimaryKey,
    enum_check,
    fk,
    one_published_exclusion,
    publication_constraints,
)

#: Dimension D des embeddings (SA-14 D2, valeur provisoire tant qu'E4 n'a pas choisi le modèle).
#: La changer = nouvelle migration (`ALTER COLUMN ... TYPE vector(D')` + index) + réindexation.
EMBEDDING_DIM = 1024

#: Taille maximale d'un fichier déposé (50 Mo).
MAX_FILE_BYTES = 50 * 1024 * 1024


class EmbeddingModel(UUIDPrimaryKey, Timestamps, Base):
    """Référentiel des modèles d'embedding ; un seul actif à la fois."""

    __tablename__ = "embedding_model"

    name: Mapped[Str]
    revision: Mapped[Str]
    dimension: Mapped[int] = mapped_column(Integer)
    distance: Mapped[str] = mapped_column(Text, server_default=text("'cosine'"))
    max_input_tokens: Mapped[int | None] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))

    __table_args__ = (
        UniqueConstraint("name", "revision"),
        CheckConstraint("dimension > 0", name="dimension"),
        enum_check("distance", enums.EMBEDDING_DISTANCE),
        CheckConstraint("max_input_tokens > 0", name="max_input_tokens"),
        Index(
            "uq_embedding_model_active",
            "is_active",
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )


class Document(UUIDPrimaryKey, Timestamps, Base):
    """Identité stable d'un document officiel (clé métier `code`, ex. GUIDE-LIC-INFO)."""

    __tablename__ = "document"

    code: Mapped[str] = mapped_column(Text, unique=True)
    document_type: Mapped[Str]
    title_fr: Mapped[Str]
    title_ar: Mapped[StrNull]
    description_fr: Mapped[StrNull]
    institution_id: Mapped[uuid.UUID | None] = fk("institution.id", ondelete="RESTRICT")
    owner_user_id: Mapped[uuid.UUID] = fk("user_account.id", nullable=False)
    default_language: Mapped[str] = mapped_column(Text, server_default=text("'fr'"))
    archived_at: Mapped[TZNull]
    created_by: Mapped[uuid.UUID] = fk("user_account.id", nullable=False)

    versions: Mapped[list[DocumentVersion]] = relationship(
        back_populates="document", lazy="raise", passive_deletes=True
    )

    __table_args__ = (
        CheckConstraint("code ~ '^[A-Z0-9_-]{2,32}$'", name="code"),
        enum_check("document_type", enums.DOCUMENT_TYPE),
        enum_check("default_language", enums.LANG_CODE),
        Index(None, "institution_id"),
        Index(None, "owner_user_id"),
    )


class DocumentProgramme(Timestamps, Base):
    """Lien N-N document ↔ formation (D9) ; métadonnée, sans réindexation."""

    __tablename__ = "document_programme"

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document.id", ondelete="CASCADE"), primary_key=True
    )
    programme_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("programme.id", ondelete="RESTRICT"), primary_key=True
    )

    __table_args__ = (Index(None, "programme_id"),)


class DocumentVersion(UUIDPrimaryKey, PublicationBlock, Timestamps, Base):
    """Version immuable d'un document (hash SHA-256), publiée à 4 yeux, état de son index."""

    __tablename__ = "document_version"

    document_id: Mapped[uuid.UUID] = fk("document.id", nullable=False, ondelete="RESTRICT")
    version_number: Mapped[int] = mapped_column(Integer)
    content_sha256: Mapped[str] = mapped_column(CHAR(64))
    storage_path: Mapped[str] = mapped_column(Text, unique=True)
    original_filename: Mapped[Str]
    mime_type: Mapped[Str]
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    language: Mapped[Str]
    page_count: Mapped[int | None] = mapped_column(Integer)
    change_note: Mapped[StrNull]
    review_comment: Mapped[StrNull]
    index_status: Mapped[str] = mapped_column(Text, server_default=text("'not_indexed'"))
    indexed_model_id: Mapped[uuid.UUID | None] = fk("embedding_model.id")
    indexed_at: Mapped[TZNull]

    document: Mapped[Document] = relationship(back_populates="versions", lazy="raise")

    __table_args__ = (
        UniqueConstraint("document_id", "version_number"),
        UniqueConstraint("document_id", "content_sha256"),
        CheckConstraint("version_number > 0", name="version_number"),
        CheckConstraint("content_sha256 ~ '^[0-9a-f]{64}$'", name="content_sha256"),
        enum_check("mime_type", enums.DOCUMENT_MIME_TYPE),
        CheckConstraint(f"size_bytes > 0 AND size_bytes <= {MAX_FILE_BYTES}", name="size_bytes"),
        enum_check("language", enums.LANG_CODE),
        CheckConstraint("page_count > 0", name="page_count"),
        enum_check("index_status", enums.INDEX_STATUS),
        *publication_constraints(),
        one_published_exclusion("document_id", name="validity"),
        Index("ix_document_version_lookup", "document_id", "publication_status", "valid_from"),
        Index(
            "ix_document_version_to_review",
            "submitted_at",
            postgresql_where=text("publication_status = 'pending_review'"),
        ),
        Index(None, "indexed_model_id"),
    )


class DocumentChunk(UUIDPrimaryKey, Timestamps, Base):
    """Passage d'une version pour le RAG hybride : embedding (HNSW cosinus) + plein texte (GIN)."""

    __tablename__ = "document_chunk"

    document_version_id: Mapped[uuid.UUID] = fk(
        "document_version.id", nullable=False, ondelete="CASCADE"
    )
    embedding_model_id: Mapped[uuid.UUID] = fk("embedding_model.id", nullable=False)
    sync_job_id: Mapped[uuid.UUID] = fk("sync_job.job_id", nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[Str]
    token_count: Mapped[int] = mapped_column(Integer)
    char_start: Mapped[int] = mapped_column(Integer)
    char_end: Mapped[int] = mapped_column(Integer)
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    section_path: Mapped[StrNull]
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, server_default=text("'{}'::jsonb")
    )
    embedding: Mapped[Any] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)
    tsv: Mapped[Any | None] = mapped_column(
        TSVECTOR,
        Computed(
            "to_tsvector('simple'::regconfig, coalesce(section_path, '') || ' ' || content)",
            persisted=True,
        ),
    )

    __table_args__ = (
        UniqueConstraint(
            "document_version_id",
            "embedding_model_id",
            "chunk_index",
            name="uq_document_chunk_version_model_index",
        ),
        CheckConstraint("chunk_index >= 0", name="chunk_index"),
        CheckConstraint("token_count > 0", name="token_count"),
        CheckConstraint("char_start >= 0 AND char_end > char_start", name="char_range"),
        CheckConstraint(
            "page_end IS NULL OR page_start IS NULL OR page_end >= page_start", name="page_range"
        ),
        Index(
            "ix_document_chunk_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index("ix_document_chunk_tsv", "tsv", postgresql_using="gin"),
        Index("ix_document_chunk_version_model", "document_version_id", "embedding_model_id"),
        Index(None, "sync_job_id"),
        Index(None, "embedding_model_id"),
    )


class CandidateAttachment(UUIDPrimaryKey, Timestamps, Base):
    """Pièce justificative d'un candidat (préfixe privé, jamais indexée, revue humaine)."""

    __tablename__ = "candidate_attachment"

    candidate_profile_id: Mapped[uuid.UUID] = fk("candidate_profile.id", nullable=False)
    attachment_type: Mapped[Str]
    preregistration_id: Mapped[uuid.UUID | None] = fk("preregistration.id")
    equivalence_request_id: Mapped[uuid.UUID | None] = fk("equivalence_request.id")
    content_sha256: Mapped[str] = mapped_column(CHAR(64))
    storage_path: Mapped[str] = mapped_column(Text, unique=True)
    original_filename: Mapped[Str]
    mime_type: Mapped[Str]
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    review_status: Mapped[str] = mapped_column(Text, server_default=text("'pending'"))
    reviewed_by: Mapped[uuid.UUID | None] = fk("user_account.id")
    reviewed_at: Mapped[TZNull]
    rejection_reason: Mapped[StrNull]
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("candidate_attachment.id", ondelete="SET NULL")
    )
    deleted_at: Mapped[TZNull]
    uploaded_by: Mapped[uuid.UUID] = fk("user_account.id", nullable=False)

    __table_args__ = (
        UniqueConstraint("candidate_profile_id", "content_sha256"),
        enum_check("attachment_type", enums.ATTACHMENT_TYPE),
        CheckConstraint("content_sha256 ~ '^[0-9a-f]{64}$'", name="content_sha256"),
        enum_check("mime_type", enums.ATTACHMENT_MIME_TYPE),
        CheckConstraint(f"size_bytes > 0 AND size_bytes <= {MAX_FILE_BYTES}", name="size_bytes"),
        enum_check("review_status", enums.CANDIDATE_DOCUMENT_REVIEW_STATUS),
        CheckConstraint(
            "review_status = 'pending' OR (reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL)",
            name="human_review",
        ),
        CheckConstraint(
            "review_status <> 'rejected' OR rejection_reason IS NOT NULL", name="rejection_reason"
        ),
        Index(None, "candidate_profile_id"),
        Index(None, "preregistration_id"),
        Index(None, "equivalence_request_id"),
        Index(None, "supersedes_id"),
    )
