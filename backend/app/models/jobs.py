"""File de travaux générique (SA-14 §4.5, §4.6, décision C3).

- `job` : un travail (vector_sync, email, follow_up, equivalence_analysis, purge), pris par un
  worker Python avec `FOR UPDATE SKIP LOCKED` ; idempotence par `dedup_key` (unique partiel sur
  les jobs actifs) et sérialisation par `concurrency_key`.
- `sync_job` : table fille 1-1 (PK = FK vers `job.id`) pour la synchro vectorielle (SA-14 D14).
  Un trigger de contrainte différé (migration) vérifie qu'un job `vector_sync` a sa ligne
  `sync_job` à la fin de la transaction.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, SmallInteger, Text, text
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
    fk,
)


class Job(UUIDPrimaryKey, Timestamps, Base):
    """Travail de la file générique (queued → running → succeeded / retry_wait / failed…)."""

    __tablename__ = "job"

    job_type: Mapped[Str]
    status: Mapped[str] = mapped_column(Text, server_default=text("'queued'"))
    priority: Mapped[int] = mapped_column(SmallInteger, server_default=text("100"))
    run_after: Mapped[TZ] = mapped_column(server_default=text("now()"))
    attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    max_attempts: Mapped[int] = mapped_column(Integer, server_default=text("5"))
    locked_by: Mapped[StrNull]
    locked_until: Mapped[TZNull]
    dedup_key: Mapped[StrNull]
    concurrency_key: Mapped[StrNull]
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    result: Mapped[Any | None] = mapped_column(JSONB)
    last_error_code: Mapped[StrNull]
    last_error: Mapped[StrNull]
    requested_by: Mapped[uuid.UUID | None] = fk("user_account.id")
    started_at: Mapped[TZNull]
    finished_at: Mapped[TZNull]

    sync: Mapped[SyncJob | None] = relationship(back_populates="job", lazy="raise")

    __table_args__ = (
        enum_check("job_type", enums.JOB_TYPE),
        enum_check("status", enums.JOB_STATUS),
        CheckConstraint("attempts >= 0", name="attempts"),
        CheckConstraint("max_attempts >= 1", name="max_attempts"),
        Index(
            "ix_job_ready",
            "priority",
            "run_after",
            postgresql_where=text("status IN ('queued','retry_wait')"),
        ),
        Index(
            "uq_job_dedup_active",
            "dedup_key",
            unique=True,
            postgresql_where=text("status IN ('queued','running','retry_wait')"),
        ),
        Index(
            "ix_job_running_concurrency",
            "concurrency_key",
            postgresql_where=text("status = 'running'"),
        ),
        Index(None, "job_type", "status"),
        Index(None, "requested_by"),
    )


class SyncJob(Timestamps, Base):
    """Spécialisation « synchro vectorielle » d'un job : version ciblée, opération, modèle."""

    __tablename__ = "sync_job"

    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("job.id", ondelete="CASCADE"), primary_key=True
    )
    document_id: Mapped[uuid.UUID] = fk("document.id", nullable=False)
    document_version_id: Mapped[uuid.UUID] = fk(
        "document_version.id", nullable=False, ondelete="CASCADE"
    )
    operation: Mapped[Str]
    trigger: Mapped[Str]
    embedding_model_id: Mapped[uuid.UUID] = fk("embedding_model.id", nullable=False)
    chunker_version: Mapped[Str]
    chunks_written: Mapped[int | None] = mapped_column(Integer)

    job: Mapped[Job] = relationship(back_populates="sync", lazy="raise")

    __table_args__ = (
        enum_check("operation", enums.SYNC_OPERATION),
        enum_check("trigger", enums.SYNC_TRIGGER),
        CheckConstraint("chunks_written >= 0", name="chunks_written"),
        Index(None, "document_id"),
        Index(None, "document_version_id"),
        Index(None, "embedding_model_id"),
    )
