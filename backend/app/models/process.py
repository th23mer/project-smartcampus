"""Processus de candidature (SA-13 §4.D à §4.G) : pré-inscription, QCM, équivalences,
rendez-vous, entretiens, relances et notifications.

Chaque décision officielle porte un décideur humain (CHECK `human_decision`) ; les scores et
créneaux sont calculés par code ; les propositions IA et les décisions humaines sont dans des
colonnes séparées.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    REAL,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, ExcludeConstraint
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

# ============ D. Pré-inscription et QCM ============


class Preregistration(UUIDPrimaryKey, Timestamps, Base):
    """Pré-inscription dans un parcours pour une année universitaire ; décision humaine."""

    __tablename__ = "preregistration"

    candidate_profile_id: Mapped[uuid.UUID] = fk("candidate_profile.id", nullable=False)
    programme_id: Mapped[uuid.UUID] = fk("programme.id", nullable=False)
    speciality_id: Mapped[uuid.UUID | None] = fk("speciality.id")
    academic_year: Mapped[Str]
    entry_level: Mapped[int] = mapped_column(SmallInteger, server_default=text("1"))
    status: Mapped[str] = mapped_column(Text, server_default=text("'draft'"))
    recommendation_item_id: Mapped[uuid.UUID | None] = fk("recommendation_item.id")
    consent_id: Mapped[uuid.UUID] = fk("consent.id", nullable=False)
    submitted_at: Mapped[TZNull]
    assigned_to: Mapped[uuid.UUID | None] = fk("user_account.id")
    decided_by: Mapped[uuid.UUID | None] = fk("user_account.id")
    decided_at: Mapped[TZNull]
    decision_note: Mapped[StrNull]

    __table_args__ = (
        CheckConstraint("academic_year ~ '^[0-9]{4}-[0-9]{4}$'", name="academic_year"),
        CheckConstraint("entry_level BETWEEN 1 AND 5", name="entry_level"),
        enum_check("status", enums.PREREGISTRATION_STATUS),
        CheckConstraint(
            "status NOT IN ('waitlisted','admitted','enrolled','rejected') "
            "OR decided_by IS NOT NULL",
            name="human_decision",
        ),
        Index(
            "uq_preregistration_active",
            "candidate_profile_id",
            "programme_id",
            "academic_year",
            unique=True,
            postgresql_where=text("status NOT IN ('withdrawn','abandoned','rejected')"),
        ),
        Index(None, "status", "programme_id"),
        Index(None, "candidate_profile_id"),
    )


class McqQuestion(UUIDPrimaryKey, Timestamps, Base):
    """Banque de questions (C6) : utilisable seulement une fois validée par le staff."""

    __tablename__ = "mcq_question"

    programme_id: Mapped[uuid.UUID | None] = fk("programme.id")
    topic: Mapped[Str]
    difficulty: Mapped[int] = mapped_column(SmallInteger)
    stem: Mapped[Str]
    options: Mapped[list[Any]] = mapped_column(JSONB)
    correct_keys: Mapped[list[str]] = mapped_column(ARRAY(Text))
    origin: Mapped[Str]
    status: Mapped[str] = mapped_column(Text, server_default=text("'draft'"))
    generator_model: Mapped[StrNull]
    validated_by: Mapped[uuid.UUID | None] = fk("user_account.id")
    validated_at: Mapped[TZNull]
    retired_at: Mapped[TZNull]

    __table_args__ = (
        CheckConstraint("difficulty BETWEEN 1 AND 5", name="difficulty"),
        enum_check("origin", enums.MCQ_QUESTION_ORIGIN),
        enum_check("status", enums.MCQ_QUESTION_STATUS),
        CheckConstraint("status = 'draft' OR validated_by IS NOT NULL", name="human_validation"),
        Index(
            "ix_mcq_question_validated",
            "programme_id",
            "topic",
            "difficulty",
            postgresql_where=text("status = 'validated'"),
        ),
    )


class McqAttempt(UUIDPrimaryKey, Timestamps, Base):
    """Passation d'un QCM ciblé ; score visible du staff seulement (D-G)."""

    __tablename__ = "mcq_attempt"

    preregistration_id: Mapped[uuid.UUID] = fk("preregistration.id", nullable=False)
    status: Mapped[str] = mapped_column(Text, server_default=text("'generated'"))
    generator_model: Mapped[StrNull]
    question_count: Mapped[int] = mapped_column(SmallInteger)
    time_limit_minutes: Mapped[int | None] = mapped_column(SmallInteger)
    assigned_by: Mapped[uuid.UUID | None] = fk("user_account.id")
    prompt_version: Mapped[StrNull]
    started_at: Mapped[TZNull]
    submitted_at: Mapped[TZNull]
    expires_at: Mapped[TZ]
    score: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    max_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    ai_summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    candidate_feedback: Mapped[StrNull]
    candidate_feedback_released_at: Mapped[TZNull]

    __table_args__ = (
        enum_check("status", enums.QCM_STATUS),
        CheckConstraint("question_count > 0", name="question_count"),
        CheckConstraint("time_limit_minutes > 0", name="time_limit_minutes"),
        CheckConstraint("score >= 0", name="score"),
        CheckConstraint("max_score > 0", name="max_score"),
        Index(
            "uq_mcq_attempt_open",
            "preregistration_id",
            unique=True,
            postgresql_where=text("status IN ('generated','assigned','in_progress')"),
        ),
        Index(None, "preregistration_id"),
    )


class McqAttemptItem(UUIDPrimaryKey, Timestamps, Base):
    """Question posée (copie figée) et réponse du candidat ; correction par code."""

    __tablename__ = "mcq_attempt_item"

    mcq_attempt_id: Mapped[uuid.UUID] = fk("mcq_attempt.id", nullable=False, ondelete="CASCADE")
    position: Mapped[int] = mapped_column(SmallInteger)
    mcq_question_id: Mapped[uuid.UUID] = fk("mcq_question.id", nullable=False)
    question_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    answer_keys: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    is_correct: Mapped[bool | None]
    answered_at: Mapped[TZNull]

    __table_args__ = (
        UniqueConstraint("mcq_attempt_id", "position"),
        CheckConstraint("position >= 1", name="position"),
        Index(None, "mcq_question_id"),
    )


# ============ E. Équivalences ============


class EquivalenceRequest(UUIDPrimaryKey, Timestamps, Base):
    """Demande d'équivalence : l'IA prépare la correspondance, le staff décide."""

    __tablename__ = "equivalence_request"

    candidate_profile_id: Mapped[uuid.UUID] = fk("candidate_profile.id", nullable=False)
    preregistration_id: Mapped[uuid.UUID | None] = fk("preregistration.id")
    target_curriculum_id: Mapped[uuid.UUID] = fk("curriculum.id", nullable=False)
    target_level: Mapped[int] = mapped_column(SmallInteger)
    origin_institution_name: Mapped[Str]
    origin_programme_label: Mapped[Str]
    # FK posée après la création de candidate_attachment (cycle avec
    # candidate_attachment.equivalence_request_id) : use_alter.
    transcript_attachment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "candidate_attachment.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_equivalence_request_transcript_attachment_id",
        )
    )
    status: Mapped[str] = mapped_column(Text, server_default=text("'draft'"))
    ai_model: Mapped[StrNull]
    ai_prompt_version: Mapped[StrNull]
    ai_analysed_at: Mapped[TZNull]
    submitted_at: Mapped[TZNull]
    decided_by: Mapped[uuid.UUID | None] = fk("user_account.id")
    decided_at: Mapped[TZNull]
    decision_note: Mapped[StrNull]

    __table_args__ = (
        CheckConstraint("target_level >= 1", name="target_level"),
        enum_check("status", enums.EQUIVALENCE_STATUS),
        CheckConstraint(
            "status NOT IN ('approved','partially_approved','rejected') OR decided_by IS NOT NULL",
            name="human_decision",
        ),
        Index(None, "status"),
        Index(None, "candidate_profile_id"),
        Index(None, "preregistration_id"),
        Index(None, "transcript_attachment_id"),
    )


class EquivalenceItem(UUIDPrimaryKey, Timestamps, Base):
    """Ligne de correspondance : proposition IA (`ai_*`) et décision humaine (`final_*`)."""

    __tablename__ = "equivalence_item"

    equivalence_request_id: Mapped[uuid.UUID] = fk(
        "equivalence_request.id", nullable=False, ondelete="CASCADE"
    )
    origin_subject_label: Mapped[Str]
    origin_hours: Mapped[int | None] = mapped_column(Integer)
    origin_credits: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    origin_grade: Mapped[Decimal | None] = mapped_column(Numeric(4, 2))
    ai_target_subject_id: Mapped[uuid.UUID | None] = fk("subject.id")
    ai_verdict: Mapped[StrNull]
    ai_confidence: Mapped[float | None] = mapped_column(REAL)
    ai_rationale: Mapped[StrNull]
    decision: Mapped[str] = mapped_column(Text, server_default=text("'proposed'"))
    final_target_subject_id: Mapped[uuid.UUID | None] = fk("subject.id")
    final_verdict: Mapped[StrNull]
    decided_by: Mapped[uuid.UUID | None] = fk("user_account.id")
    decided_at: Mapped[TZNull]
    staff_comment: Mapped[StrNull]

    __table_args__ = (
        CheckConstraint("origin_grade BETWEEN 0 AND 20", name="origin_grade"),
        enum_check_null("ai_verdict", enums.EQUIVALENCE_VERDICT),
        CheckConstraint("ai_confidence BETWEEN 0 AND 1", name="ai_confidence"),
        enum_check("decision", enums.EQUIVALENCE_LINE_DECISION),
        enum_check_null("final_verdict", enums.EQUIVALENCE_VERDICT),
        CheckConstraint(
            "decision = 'proposed' OR (decided_by IS NOT NULL AND final_verdict IS NOT NULL)",
            name="human_decision",
        ),
        Index(
            "ix_equivalence_item_to_review",
            "equivalence_request_id",
            postgresql_where=text("decision = 'proposed'"),
        ),
        Index(None, "equivalence_request_id"),
    )


# ============ F. Rendez-vous et entretiens ============


class AppointmentSlot(UUIDPrimaryKey, Timestamps, Base):
    """Créneau ouvert par le staff ; pas de chevauchement pour un même responsable (EXCLUDE)."""

    __tablename__ = "appointment_slot"

    institution_id: Mapped[uuid.UUID] = fk("institution.id", nullable=False)
    appointment_type: Mapped[Str]
    staff_user_id: Mapped[uuid.UUID | None] = fk("user_account.id")
    starts_at: Mapped[TZ]
    ends_at: Mapped[TZ]
    mode: Mapped[Str]
    location: Mapped[StrNull]
    status: Mapped[str] = mapped_column(Text, server_default=text("'open'"))
    created_by: Mapped[uuid.UUID] = fk("user_account.id", nullable=False)

    __table_args__ = (
        enum_check("appointment_type", enums.APPOINTMENT_TYPE),
        enum_check("mode", enums.APPOINTMENT_MODE),
        enum_check("status", enums.SLOT_STATUS),
        CheckConstraint("ends_at > starts_at", name="period"),
        ExcludeConstraint(
            ("staff_user_id", "="),
            (text("tstzrange(starts_at, ends_at)"), "&&"),
            name="staff_overlap",
            using="gist",
            where=text("status <> 'cancelled'"),
        ),
        Index(
            "ix_appointment_slot_open",
            "institution_id",
            "appointment_type",
            "starts_at",
            postgresql_where=text("status = 'open'"),
        ),
    )


class Appointment(UUIDPrimaryKey, Timestamps, Base):
    """Réservation d'un créneau ; un seul rendez-vous actif par créneau (unique partiel)."""

    __tablename__ = "appointment"

    appointment_type: Mapped[Str]
    slot_id: Mapped[uuid.UUID | None] = fk("appointment_slot.id")
    offered_slot_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(Uuid), server_default=text("'{}'::uuid[]")
    )
    candidate_profile_id: Mapped[uuid.UUID] = fk("candidate_profile.id", nullable=False)
    preregistration_id: Mapped[uuid.UUID | None] = fk("preregistration.id")
    status: Mapped[str] = mapped_column(Text, server_default=text("'proposed'"))
    booked_via: Mapped[Str]
    booked_by: Mapped[uuid.UUID | None] = fk("user_account.id")
    invitation_sent_at: Mapped[TZNull]
    confirmed_at: Mapped[TZNull]
    cancelled_at: Mapped[TZNull]
    cancel_reason: Mapped[StrNull]
    rescheduled_from_id: Mapped[uuid.UUID | None] = fk("appointment.id")

    __table_args__ = (
        enum_check("appointment_type", enums.APPOINTMENT_TYPE),
        enum_check("status", enums.APPOINTMENT_STATUS),
        enum_check("booked_via", enums.BOOKED_VIA),
        CheckConstraint(
            "status IN ('proposed','cancelled') OR slot_id IS NOT NULL", name="slot_required"
        ),
        Index(
            "uq_appointment_active_slot",
            "slot_id",
            unique=True,
            postgresql_where=text("status IN ('scheduled','confirmed')"),
        ),
        Index(
            "uq_appointment_active_type",
            "preregistration_id",
            "appointment_type",
            unique=True,
            postgresql_where=text("status IN ('proposed','scheduled','confirmed')"),
        ),
        Index(None, "candidate_profile_id"),
        Index(None, "slot_id"),
    )


class Interview(UUIDPrimaryKey, Timestamps, Base):
    """Entretien : brief IA, grille, avis de l'intervieweur (un avis, pas une admission)."""

    __tablename__ = "interview"

    appointment_id: Mapped[uuid.UUID | None] = fk("appointment.id", unique=True)
    preregistration_id: Mapped[uuid.UUID] = fk("preregistration.id", nullable=False)
    interviewer_id: Mapped[uuid.UUID] = fk("user_account.id", nullable=False)
    status: Mapped[str] = mapped_column(Text, server_default=text("'awaiting_scheduling'"))
    brief: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    brief_model: Mapped[StrNull]
    rubric_version: Mapped[StrNull]
    rubric_scores: Mapped[list[Any] | None] = mapped_column(JSONB)
    overall_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    outcome: Mapped[StrNull]
    observations: Mapped[StrNull]
    decided_by: Mapped[uuid.UUID | None] = fk("user_account.id")
    decided_at: Mapped[TZNull]

    __table_args__ = (
        enum_check("status", enums.INTERVIEW_STATUS),
        enum_check_null("outcome", enums.INTERVIEW_OUTCOME),
        CheckConstraint("(outcome IS NULL) = (decided_by IS NULL)", name="human_decision"),
        CheckConstraint("status <> 'result_recorded' OR outcome IS NOT NULL", name="result"),
        Index(None, "status", "interviewer_id"),
        Index(None, "preregistration_id"),
    )


# ============ G. Relances et notifications ============


class FollowUp(UUIDPrimaryKey, Timestamps, Base):
    """Relance : règle déclenchée par code, message rédigé par l'IA, escalade humaine."""

    __tablename__ = "follow_up"

    candidate_profile_id: Mapped[uuid.UUID] = fk("candidate_profile.id", nullable=False)
    reason: Mapped[Str]
    preregistration_id: Mapped[uuid.UUID | None] = fk("preregistration.id")
    attempt_no: Mapped[int] = mapped_column(SmallInteger)
    channel: Mapped[Str]
    status: Mapped[str] = mapped_column(Text, server_default=text("'planned'"))
    scheduled_at: Mapped[TZ]
    sent_at: Mapped[TZNull]
    message_body: Mapped[StrNull]
    escalated_to: Mapped[uuid.UUID | None] = fk("user_account.id")

    __table_args__ = (
        enum_check("reason", enums.FOLLOW_UP_REASON),
        CheckConstraint("attempt_no >= 1", name="attempt_no"),
        enum_check("channel", enums.FOLLOW_UP_CHANNEL),
        enum_check("status", enums.FOLLOW_UP_STATUS),
        Index(None, "status", "scheduled_at"),
        Index(None, "candidate_profile_id"),
    )


class Notification(UUIDPrimaryKey, Timestamps, Base):
    """Notification in-app ; l'e-mail éventuel part par un job de la file (C3)."""

    __tablename__ = "notification"

    user_id: Mapped[uuid.UUID] = fk("user_account.id", nullable=False, ondelete="CASCADE")
    type: Mapped[Str]
    title: Mapped[Str]
    body: Mapped[StrNull]
    link: Mapped[StrNull]
    entity_type: Mapped[StrNull]
    entity_id: Mapped[uuid.UUID | None]
    follow_up_id: Mapped[uuid.UUID | None] = fk("follow_up.id", ondelete="SET NULL")
    email_job_id: Mapped[uuid.UUID | None] = fk("job.id", ondelete="SET NULL")
    read_at: Mapped[TZNull]

    __table_args__ = (
        enum_check("type", enums.NOTIFICATION_TYPE),
        enum_check_null("entity_type", enums.STATUS_ENTITY_TYPE),
        Index(
            "ix_notification_unread",
            "user_id",
            text("created_at DESC"),
            postgresql_where=text("read_at IS NULL"),
        ),
        Index(None, "email_job_id"),
    )
