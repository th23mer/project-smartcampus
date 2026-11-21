"""Dossier candidat et recommandation d'orientation (SA-13 §4.C).

Le profil est rempli par l'IA depuis la conversation puis confirmé par le candidat ; la
shortlist (`recommendation`) est préparée par l'IA et validée par le staff (HITL : CHECK
`human_review`). Éligibilité, durées et coûts sont calculés par des outils déterministes.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models import enums
from app.models._common import (
    Str,
    StrNull,
    Timestamps,
    TZNull,
    UUIDPrimaryKey,
    enum_check,
    enum_check_null,
    fk,
)


class CandidateProfile(UUIDPrimaryKey, Timestamps, Base):
    """Profil d'orientation (1-1 avec un compte candidat) ; provenance par champ (field_sources)."""

    __tablename__ = "candidate_profile"

    user_id: Mapped[uuid.UUID] = fk("user_account.id", nullable=False, unique=True)
    candidate_type: Mapped[Str]
    birth_date: Mapped[date | None] = mapped_column(Date)
    city: Mapped[StrNull]
    interests: Mapped[list[Any]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    goals: Mapped[StrNull]
    constraints: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    profile_status: Mapped[str] = mapped_column(Text, server_default=text("'ai_draft'"))
    field_sources: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    confirmed_at: Mapped[TZNull]

    academic_records: Mapped[list[AcademicRecord]] = relationship(
        back_populates="candidate_profile", lazy="raise", passive_deletes=True
    )

    __table_args__ = (
        enum_check("candidate_type", enums.CANDIDATE_TYPE),
        enum_check("profile_status", enums.PROFILE_STATUS),
    )


class AcademicRecord(UUIDPrimaryKey, Timestamps, Base):
    """Diplôme ou année d'études (bac, année universitaire) ; clés du bac en français (C1)."""

    __tablename__ = "academic_record"

    candidate_profile_id: Mapped[uuid.UUID] = fk(
        "candidate_profile.id", nullable=False, ondelete="CASCADE"
    )
    record_type: Mapped[Str]
    bac_section: Mapped[StrNull]
    year: Mapped[int] = mapped_column(SmallInteger)
    institution_name: Mapped[StrNull]
    diploma_label: Mapped[StrNull]
    overall_average: Mapped[Decimal | None] = mapped_column(Numeric(4, 2))
    orientation_score: Mapped[Decimal | None] = mapped_column(Numeric(7, 3))
    source: Mapped[Str]
    attachment_id: Mapped[uuid.UUID | None] = fk("candidate_attachment.id", ondelete="SET NULL")
    verified_by: Mapped[uuid.UUID | None] = fk("user_account.id")
    verified_at: Mapped[TZNull]

    candidate_profile: Mapped[CandidateProfile] = relationship(
        back_populates="academic_records", lazy="raise"
    )
    subjects: Mapped[list[AcademicRecordSubject]] = relationship(
        back_populates="academic_record", lazy="raise", passive_deletes=True
    )

    __table_args__ = (
        enum_check("record_type", enums.RECORD_TYPE),
        enum_check_null("bac_section", enums.BAC_SECTION),
        CheckConstraint("year BETWEEN 1990 AND 2100", name="year"),
        CheckConstraint("overall_average BETWEEN 0 AND 20", name="overall_average"),
        CheckConstraint("orientation_score >= 0", name="orientation_score"),
        enum_check("source", enums.DATA_SOURCE),
        CheckConstraint(
            "(record_type = 'bac') = (bac_section IS NOT NULL)", name="bac_section_set"
        ),
        Index(None, "candidate_profile_id"),
        Index(None, "attachment_id"),
    )


class AcademicRecordSubject(UUIDPrimaryKey, Timestamps, Base):
    """Matière et note d'un relevé ; `subject_key` = clé française partagée avec SA-12."""

    __tablename__ = "academic_record_subject"

    academic_record_id: Mapped[uuid.UUID] = fk(
        "academic_record.id", nullable=False, ondelete="CASCADE"
    )
    subject_label: Mapped[Str]
    subject_key: Mapped[StrNull]
    grade: Mapped[Decimal | None] = mapped_column(Numeric(4, 2))
    coefficient: Mapped[Decimal | None] = mapped_column(Numeric(4, 2))
    credits: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    hours: Mapped[int | None] = mapped_column(Integer)

    academic_record: Mapped[AcademicRecord] = relationship(back_populates="subjects", lazy="raise")

    __table_args__ = (
        enum_check_null("subject_key", enums.BAC_SUBJECT_KEY),
        CheckConstraint("grade BETWEEN 0 AND 20", name="grade"),
        CheckConstraint("coefficient > 0", name="coefficient"),
        CheckConstraint("credits >= 0", name="credits"),
        CheckConstraint("hours >= 0", name="hours"),
        Index(None, "academic_record_id"),
    )


class Recommendation(UUIDPrimaryKey, Timestamps, Base):
    """Shortlist préparée par l'IA, validée ou ajustée par le staff (human-in-the-loop)."""

    __tablename__ = "recommendation"

    candidate_profile_id: Mapped[uuid.UUID] = fk("candidate_profile.id", nullable=False)
    conversation_id: Mapped[uuid.UUID | None] = fk("conversation.id", ondelete="SET NULL")
    status: Mapped[str] = mapped_column(Text, server_default=text("'draft'"))
    model_name: Mapped[Str]
    prompt_version: Mapped[Str]
    profile_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    reviewed_by: Mapped[uuid.UUID | None] = fk("user_account.id")
    reviewed_at: Mapped[TZNull]
    review_comment: Mapped[StrNull]
    superseded_by: Mapped[uuid.UUID | None] = fk("recommendation.id")

    items: Mapped[list[RecommendationItem]] = relationship(
        back_populates="recommendation", lazy="raise", passive_deletes=True
    )

    __table_args__ = (
        enum_check("status", enums.ORIENTATION_RECOMMENDATION_STATUS),
        CheckConstraint(
            "status NOT IN ('confirmed','adjusted') OR reviewed_by IS NOT NULL",
            name="human_review",
        ),
        Index(None, "candidate_profile_id"),
        Index(None, "conversation_id"),
        Index(None, "status"),
    )


class RecommendationItem(UUIDPrimaryKey, Timestamps, Base):
    """Un parcours de la shortlist : verdict d'éligibilité (code) + justification (IA)."""

    __tablename__ = "recommendation_item"

    recommendation_id: Mapped[uuid.UUID] = fk(
        "recommendation.id", nullable=False, ondelete="CASCADE"
    )
    rank: Mapped[int] = mapped_column(SmallInteger)
    programme_id: Mapped[uuid.UUID] = fk("programme.id", nullable=False)
    speciality_id: Mapped[uuid.UUID | None] = fk("speciality.id")
    eligibility: Mapped[dict[str, Any]] = mapped_column(JSONB)
    total_duration_years: Mapped[int | None] = mapped_column(SmallInteger)
    total_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    rationale: Mapped[Str]
    sources: Mapped[list[Any]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    staff_decision: Mapped[str] = mapped_column(Text, server_default=text("'pending'"))
    chosen_by_candidate_at: Mapped[TZNull]

    recommendation: Mapped[Recommendation] = relationship(back_populates="items", lazy="raise")

    __table_args__ = (
        UniqueConstraint("recommendation_id", "rank"),
        CheckConstraint("rank BETWEEN 1 AND 5", name="rank"),
        enum_check("staff_decision", enums.RECOMMENDATION_ITEM_DECISION),
        Index(None, "programme_id"),
        Index(None, "speciality_id"),
    )
