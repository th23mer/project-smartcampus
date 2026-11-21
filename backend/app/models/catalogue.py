"""Catalogue académique (SA-12) : 13 tables + journal d'audit `catalogue_audit_log`.

Catégories (SA-12 §1) :
- A. entités stables publiables : `institution`, `programme`, `speciality` ;
- B. faits versionnés publiables (contrainte d'exclusion) : `curriculum`, `admission_condition`,
  `fee_schedule`, `bridge` ;
- C. enfants d'une version : `curriculum_subject`, `prerequisite`,
  `admission_subject_requirement`, `payment_plan`, `payment_installment` ;
- D. référentiel interne : `subject` ;
- E. journal append-only : `catalogue_audit_log` (alimenté par le trigger `audit_catalogue()`).

Les triggers (`set_updated_at`, `audit_catalogue`, garde des versions publiées) et les index
plein texte sont posés par la migration `catalogue` (SQL brut), pas par ces classes.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CHAR,
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models import enums
from app.models._common import (
    CreatedAt,
    PublicationBlock,
    Str,
    StrNull,
    Timestamps,
    UUIDPrimaryKey,
    coalesce_uuid,
    enum_check,
    enum_check_null,
    fk,
    one_published_exclusion,
    publication_constraints,
    sql_list,
)

CODE_RE = "^[A-Z0-9_-]{2,32}$"
YEAR_RE = "^[0-9]{4}-[0-9]{4}$"


def _code_check(regex: str = CODE_RE) -> CheckConstraint:
    return CheckConstraint(f"code ~ '{regex}'", name="code")


def _academic_year_check() -> CheckConstraint:
    return CheckConstraint(f"academic_year ~ '{YEAR_RE}'", name="academic_year")


# ============ A. Entités stables publiables ============


class Institution(UUIDPrimaryKey, PublicationBlock, Timestamps, Base):
    """Établissement (IIT, ISB) : entité stable publiable."""

    __tablename__ = "institution"

    code: Mapped[str] = mapped_column(Text, unique=True)
    name_fr: Mapped[Str]
    name_ar: Mapped[StrNull]
    city: Mapped[Str]
    website_url: Mapped[StrNull]
    description_fr: Mapped[StrNull]

    programmes: Mapped[list[Programme]] = relationship(
        back_populates="institution", lazy="raise", passive_deletes=True
    )

    __table_args__ = (
        _code_check("^[A-Z0-9_]{2,16}$"),
        *publication_constraints(),
    )


class Programme(UUIDPrimaryKey, PublicationBlock, Timestamps, Base):
    """Formation (Licence, Prépa, Ingénierie…) : entité stable publiable."""

    __tablename__ = "programme"

    institution_id: Mapped[uuid.UUID] = fk("institution.id", nullable=False, ondelete="RESTRICT")
    code: Mapped[str] = mapped_column(Text, unique=True)
    name_fr: Mapped[Str]
    name_ar: Mapped[StrNull]
    programme_type: Mapped[Str]
    diploma_name_fr: Mapped[StrNull]
    duration_years: Mapped[int] = mapped_column(SmallInteger)
    total_ects: Mapped[int | None] = mapped_column(SmallInteger)
    description_fr: Mapped[StrNull]
    career_outcomes_fr: Mapped[StrNull]

    institution: Mapped[Institution] = relationship(back_populates="programmes", lazy="raise")
    specialities: Mapped[list[Speciality]] = relationship(
        back_populates="programme", lazy="raise", passive_deletes=True
    )

    __table_args__ = (
        _code_check(),
        enum_check("programme_type", enums.PROGRAMME_TYPE),
        CheckConstraint("duration_years BETWEEN 1 AND 6", name="duration_years"),
        CheckConstraint("total_ects > 0", name="total_ects"),
        *publication_constraints(),
        Index("ix_programme_institution", "institution_id"),
        Index(
            "ix_programme_official",
            "validity",
            postgresql_using="gist",
            postgresql_where=text("publication_status = 'published'"),
        ),
        Index(
            "ix_programme_fts",
            text(
                "to_tsvector('french'::regconfig, "
                "(name_fr || ' '::text) || COALESCE(description_fr, ''::text))"
            ),
            postgresql_using="gin",
        ),
    )


class Speciality(UUIDPrimaryKey, PublicationBlock, Timestamps, Base):
    """Spécialité d'une formation (ex. GL de la Licence informatique)."""

    __tablename__ = "speciality"

    programme_id: Mapped[uuid.UUID] = fk("programme.id", nullable=False, ondelete="RESTRICT")
    code: Mapped[Str]
    name_fr: Mapped[Str]
    name_ar: Mapped[StrNull]
    description_fr: Mapped[StrNull]
    career_outcomes_fr: Mapped[StrNull]

    programme: Mapped[Programme] = relationship(back_populates="specialities", lazy="raise")

    __table_args__ = (
        _code_check(),
        UniqueConstraint("programme_id", "code", name="uq_speciality_programme_code"),
        # Cible des FK composites (spécialité, formation) : cohérence garantie par la base.
        UniqueConstraint("id", "programme_id", name="uq_speciality_id_programme"),
        *publication_constraints(),
        Index(
            "ix_speciality_official",
            "programme_id",
            "validity",
            postgresql_using="gist",
            postgresql_where=text("publication_status = 'published'"),
        ),
        Index(
            "ix_speciality_fts",
            text(
                "to_tsvector('french'::regconfig, "
                "(name_fr || ' '::text) || COALESCE(description_fr, ''::text))"
            ),
            postgresql_using="gin",
        ),
    )


# ============ D. Référentiel interne ============


class Subject(UUIDPrimaryKey, Timestamps, Base):
    """Matière enseignée (référentiel interne, visible via un cursus publié, SA-12 D5)."""

    __tablename__ = "subject"

    institution_id: Mapped[uuid.UUID] = fk("institution.id", nullable=False, ondelete="RESTRICT")
    code: Mapped[Str]
    name_fr: Mapped[Str]
    name_ar: Mapped[StrNull]
    domain: Mapped[StrNull]
    description_fr: Mapped[StrNull]
    learning_outcomes_fr: Mapped[StrNull]

    __table_args__ = (
        _code_check(),
        UniqueConstraint("institution_id", "code", name="uq_subject_institution_code"),
        Index("ix_subject_institution", "institution_id"),
        Index(
            "ix_subject_fts",
            text(
                "to_tsvector('french'::regconfig, "
                "(name_fr || ' '::text) || COALESCE(description_fr, ''::text))"
            ),
            postgresql_using="gin",
        ),
    )


# ============ B. Faits versionnés publiables (+ C. enfants) ============


def _speciality_fk(
    spec_col: str = "speciality_id", prog_col: str = "programme_id", *, name: str
) -> ForeignKeyConstraint:
    """FK composite (spécialité, formation) → speciality(id, programme_id), SA-12 règle 5."""
    return ForeignKeyConstraint(
        [spec_col, prog_col],
        ["speciality.id", "speciality.programme_id"],
        name=name,
        ondelete="RESTRICT",
    )


class Curriculum(UUIDPrimaryKey, PublicationBlock, Timestamps, Base):
    """Version du cursus d'une formation (ou d'une spécialité). `academic_year` hors clé (D20)."""

    __tablename__ = "curriculum"

    programme_id: Mapped[uuid.UUID] = fk("programme.id", nullable=False, ondelete="RESTRICT")
    speciality_id: Mapped[uuid.UUID | None]
    version_label: Mapped[Str]
    academic_year: Mapped[Str]
    total_ects: Mapped[int | None] = mapped_column(SmallInteger)
    notes_fr: Mapped[StrNull]

    subjects: Mapped[list[CurriculumSubject]] = relationship(
        back_populates="curriculum", lazy="raise", passive_deletes=True
    )

    __table_args__ = (
        _speciality_fk(name="fk_curriculum_speciality"),
        UniqueConstraint(
            "programme_id",
            "speciality_id",
            "version_label",
            name="uq_curriculum_version",
            postgresql_nulls_not_distinct=True,
        ),
        _academic_year_check(),
        CheckConstraint("total_ects > 0", name="total_ects"),
        *publication_constraints(),
        one_published_exclusion("programme_id", coalesce_uuid("speciality_id")),
        Index("ix_curriculum_programme", "programme_id"),
        Index("ix_curriculum_speciality", "speciality_id"),
        Index("ix_curriculum_status", "publication_status", text("updated_at DESC")),
    )


class CurriculumSubject(UUIDPrimaryKey, Timestamps, Base):
    """Matière d'une version de cursus (semestre, coefficient, crédits, heures)."""

    __tablename__ = "curriculum_subject"

    curriculum_id: Mapped[uuid.UUID] = fk("curriculum.id", nullable=False, ondelete="CASCADE")
    subject_id: Mapped[uuid.UUID] = fk("subject.id", nullable=False, ondelete="RESTRICT")
    semester: Mapped[int] = mapped_column(SmallInteger)
    teaching_unit_code: Mapped[StrNull]
    teaching_unit_name_fr: Mapped[StrNull]
    coefficient: Mapped[Decimal] = mapped_column(Numeric(4, 2))
    ects_credits: Mapped[Decimal] = mapped_column(Numeric(4, 1))
    hours_lecture: Mapped[Decimal] = mapped_column(Numeric(5, 1), server_default=text("0"))
    hours_tutorial: Mapped[Decimal] = mapped_column(Numeric(5, 1), server_default=text("0"))
    hours_practical: Mapped[Decimal] = mapped_column(Numeric(5, 1), server_default=text("0"))
    hours_total: Mapped[Decimal | None] = mapped_column(
        Numeric(6, 1),
        Computed("hours_lecture + hours_tutorial + hours_practical", persisted=True),
    )
    is_elective: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))

    curriculum: Mapped[Curriculum] = relationship(back_populates="subjects", lazy="raise")

    __table_args__ = (
        UniqueConstraint("curriculum_id", "subject_id", name="uq_curriculum_subject"),
        UniqueConstraint("id", "curriculum_id", name="uq_curriculum_subject_id_curriculum"),
        CheckConstraint("semester BETWEEN 1 AND 10", name="semester"),
        CheckConstraint("coefficient > 0", name="coefficient"),
        CheckConstraint("ects_credits >= 0", name="ects_credits"),
        CheckConstraint("hours_lecture >= 0", name="hours_lecture"),
        CheckConstraint("hours_tutorial >= 0", name="hours_tutorial"),
        CheckConstraint("hours_practical >= 0", name="hours_practical"),
        Index("ix_curriculum_subject_subject", "subject_id"),
    )


class Prerequisite(UUIDPrimaryKey, Timestamps, Base):
    """Prérequis d'une matière du cursus (matière exigée et/ou connaissance attendue)."""

    __tablename__ = "prerequisite"

    curriculum_id: Mapped[uuid.UUID] = fk("curriculum.id", nullable=False, ondelete="CASCADE")
    curriculum_subject_id: Mapped[uuid.UUID | None]
    required_subject_id: Mapped[uuid.UUID | None] = fk("subject.id", ondelete="RESTRICT")
    required_knowledge_fr: Mapped[StrNull]
    is_mandatory: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))

    __table_args__ = (
        ForeignKeyConstraint(
            ["curriculum_subject_id", "curriculum_id"],
            ["curriculum_subject.id", "curriculum_subject.curriculum_id"],
            name="fk_prerequisite_target",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "required_subject_id IS NOT NULL OR required_knowledge_fr IS NOT NULL",
            name="content",
        ),
        Index("ix_prerequisite_curriculum", "curriculum_id"),
        Index("ix_prerequisite_target", "curriculum_subject_id"),
        Index("ix_prerequisite_required", "required_subject_id"),
    )


class AdmissionCondition(UUIDPrimaryKey, PublicationBlock, Timestamps, Base):
    """Conditions d'admission d'une formation pour une rentrée (année dans la clé, D-I)."""

    __tablename__ = "admission_condition"

    programme_id: Mapped[uuid.UUID] = fk("programme.id", nullable=False, ondelete="RESTRICT")
    speciality_id: Mapped[uuid.UUID | None]
    entry_level: Mapped[int] = mapped_column(SmallInteger)
    applicant_category: Mapped[Str]
    required_diploma: Mapped[Str]
    accepted_bac_sections: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    min_validated_years: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))
    min_average: Mapped[Decimal | None] = mapped_column(Numeric(4, 2))
    average_basis: Mapped[StrNull]
    requires_application_file: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    requires_test: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    requires_interview: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    max_places: Mapped[int | None] = mapped_column(Integer)
    academic_year: Mapped[Str]
    summary_fr: Mapped[Str]

    requirements: Mapped[list[AdmissionSubjectRequirement]] = relationship(
        back_populates="admission_condition", lazy="raise", passive_deletes=True
    )

    __table_args__ = (
        _speciality_fk(name="fk_admission_condition_speciality"),
        CheckConstraint("entry_level BETWEEN 1 AND 5", name="entry_level"),
        enum_check("applicant_category", enums.APPLICANT_CATEGORY),
        enum_check("required_diploma", enums.REQUIRED_DIPLOMA),
        CheckConstraint(
            f"accepted_bac_sections <@ ARRAY{list(enums.BAC_SECTION)}::text[]",
            name="accepted_bac_sections",
        ),
        CheckConstraint("min_validated_years BETWEEN 0 AND 5", name="min_validated_years"),
        CheckConstraint("min_average BETWEEN 0 AND 20", name="min_average"),
        enum_check_null("average_basis", enums.AVERAGE_BASIS),
        CheckConstraint("max_places > 0", name="max_places"),
        _academic_year_check(),
        CheckConstraint("(min_average IS NULL) = (average_basis IS NULL)", name="average"),
        CheckConstraint(
            "required_diploma = 'baccalaureate' OR accepted_bac_sections IS NULL", name="bac"
        ),
        *publication_constraints(),
        one_published_exclusion(
            "programme_id",
            coalesce_uuid("speciality_id"),
            "entry_level",
            "applicant_category",
            "academic_year",
        ),
        Index("ix_admission_condition_programme", "programme_id"),
        Index("ix_admission_condition_speciality", "speciality_id"),
        Index("ix_admission_condition_status", "publication_status", text("updated_at DESC")),
        Index(
            "ix_admission_condition_sections",
            "accepted_bac_sections",
            postgresql_using="gin",
        ),
    )


class AdmissionSubjectRequirement(UUIDPrimaryKey, Timestamps, Base):
    """Note minimale exigée dans une matière du bac (clé française, C1)."""

    __tablename__ = "admission_subject_requirement"

    admission_condition_id: Mapped[uuid.UUID] = fk(
        "admission_condition.id", nullable=False, ondelete="CASCADE"
    )
    subject_key: Mapped[Str]
    subject_name_fr: Mapped[Str]
    min_grade: Mapped[Decimal] = mapped_column(Numeric(4, 2))

    admission_condition: Mapped[AdmissionCondition] = relationship(
        back_populates="requirements", lazy="raise"
    )

    __table_args__ = (
        UniqueConstraint(
            "admission_condition_id", "subject_key", name="uq_admission_subject_requirement"
        ),
        CheckConstraint("subject_key ~ '^[a-z_]{2,40}$'", name="subject_key"),
        CheckConstraint("min_grade BETWEEN 0 AND 20", name="min_grade"),
    )


class FeeSchedule(UUIDPrimaryKey, PublicationBlock, Timestamps, Base):
    """Grille de frais officielle pour une année universitaire (D-A) ; total = colonne générée."""

    __tablename__ = "fee_schedule"

    programme_id: Mapped[uuid.UUID] = fk("programme.id", nullable=False, ondelete="RESTRICT")
    speciality_id: Mapped[uuid.UUID | None]
    study_year: Mapped[int | None] = mapped_column(SmallInteger)
    student_category: Mapped[str] = mapped_column(Text, server_default=text("'tunisian'"))
    academic_year: Mapped[Str]
    currency: Mapped[str] = mapped_column(CHAR(3), server_default=text("'TND'"))
    registration_fee: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    annual_tuition_fee: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    other_fees: Mapped[Decimal] = mapped_column(Numeric(12, 3), server_default=text("0"))
    other_fees_label_fr: Mapped[StrNull]
    annual_total: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 3),
        Computed("registration_fee + annual_tuition_fee + other_fees", persisted=True),
    )
    notes_fr: Mapped[StrNull]

    payment_plans: Mapped[list[PaymentPlan]] = relationship(
        back_populates="fee_schedule", lazy="raise", passive_deletes=True
    )

    __table_args__ = (
        _speciality_fk(name="fk_fee_schedule_speciality"),
        CheckConstraint("study_year BETWEEN 1 AND 6", name="study_year"),
        enum_check("student_category", enums.STUDENT_CATEGORY),
        _academic_year_check(),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency"),
        CheckConstraint("registration_fee >= 0", name="registration_fee"),
        CheckConstraint("annual_tuition_fee >= 0", name="annual_tuition_fee"),
        CheckConstraint("other_fees >= 0", name="other_fees"),
        CheckConstraint("other_fees = 0 OR other_fees_label_fr IS NOT NULL", name="other_label"),
        *publication_constraints(),
        one_published_exclusion(
            "programme_id",
            coalesce_uuid("speciality_id"),
            text("COALESCE(study_year, 0::smallint)"),
            "student_category",
            "academic_year",
        ),
        Index("ix_fee_schedule_programme", "programme_id"),
        Index("ix_fee_schedule_speciality", "speciality_id"),
        Index("ix_fee_schedule_status", "publication_status", text("updated_at DESC")),
    )


class PaymentPlan(UUIDPrimaryKey, Timestamps, Base):
    """Plan de paiement d'une grille (ex. 3 tranches)."""

    __tablename__ = "payment_plan"

    fee_schedule_id: Mapped[uuid.UUID] = fk("fee_schedule.id", nullable=False, ondelete="CASCADE")
    code: Mapped[Str]
    label_fr: Mapped[Str]
    installment_count: Mapped[int] = mapped_column(SmallInteger)
    discount_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), server_default=text("0"))
    is_default: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))

    fee_schedule: Mapped[FeeSchedule] = relationship(back_populates="payment_plans", lazy="raise")
    installments: Mapped[list[PaymentInstallment]] = relationship(
        back_populates="payment_plan", lazy="raise", passive_deletes=True
    )

    __table_args__ = (
        _code_check(),
        UniqueConstraint("fee_schedule_id", "code", name="uq_payment_plan_code"),
        CheckConstraint("installment_count BETWEEN 1 AND 12", name="installment_count"),
        CheckConstraint("discount_rate BETWEEN 0 AND 100", name="discount_rate"),
        # Un seul plan par défaut par grille.
        Index(
            "uq_payment_plan_default",
            "fee_schedule_id",
            unique=True,
            postgresql_where=text("is_default"),
        ),
    )


class PaymentInstallment(UUIDPrimaryKey, Timestamps, Base):
    """Échéance d'un plan de paiement."""

    __tablename__ = "payment_installment"

    payment_plan_id: Mapped[uuid.UUID] = fk("payment_plan.id", nullable=False, ondelete="CASCADE")
    installment_no: Mapped[int] = mapped_column(SmallInteger)
    due_date: Mapped[date | None] = mapped_column(Date)
    due_label_fr: Mapped[StrNull]
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 3))

    payment_plan: Mapped[PaymentPlan] = relationship(back_populates="installments", lazy="raise")

    __table_args__ = (
        UniqueConstraint("payment_plan_id", "installment_no", name="uq_payment_installment_no"),
        CheckConstraint("installment_no >= 1", name="installment_no"),
        CheckConstraint("amount > 0", name="amount"),
        CheckConstraint("due_date IS NOT NULL OR due_label_fr IS NOT NULL", name="due"),
    )


class Bridge(UUIDPrimaryKey, PublicationBlock, Timestamps, Base):
    """Passerelle entre deux formations (non annuelle, D20)."""

    __tablename__ = "bridge"

    source_programme_id: Mapped[uuid.UUID] = fk("programme.id", nullable=False, ondelete="RESTRICT")
    source_speciality_id: Mapped[uuid.UUID | None]
    source_min_completed_years: Mapped[int] = mapped_column(SmallInteger)
    target_programme_id: Mapped[uuid.UUID] = fk("programme.id", nullable=False, ondelete="RESTRICT")
    target_speciality_id: Mapped[uuid.UUID | None]
    target_entry_level: Mapped[int] = mapped_column(SmallInteger)
    access_mode: Mapped[Str]
    conditions_summary_fr: Mapped[Str]

    __table_args__ = (
        _speciality_fk(
            "source_speciality_id", "source_programme_id", name="fk_bridge_source_speciality"
        ),
        _speciality_fk(
            "target_speciality_id", "target_programme_id", name="fk_bridge_target_speciality"
        ),
        CheckConstraint(
            "source_min_completed_years BETWEEN 0 AND 6", name="source_min_completed_years"
        ),
        CheckConstraint("target_entry_level BETWEEN 1 AND 5", name="target_entry_level"),
        enum_check("access_mode", enums.ACCESS_MODE),
        CheckConstraint(
            "source_programme_id <> target_programme_id "
            "OR source_speciality_id IS DISTINCT FROM target_speciality_id",
            name="distinct",
        ),
        *publication_constraints(),
        one_published_exclusion(
            "source_programme_id",
            coalesce_uuid("source_speciality_id"),
            "target_programme_id",
            coalesce_uuid("target_speciality_id"),
            "target_entry_level",
        ),
        Index("ix_bridge_source", "source_programme_id"),
        Index("ix_bridge_target", "target_programme_id"),
    )


# ============ E. Journal d'audit (C5) ============


class CatalogueAuditLog(UUIDPrimaryKey, CreatedAt, Base):
    """Journal append-only des éditions du catalogue (trigger `audit_catalogue()`).

    L'auteur vient de `current_setting('app.current_user_id')` (posé par `SET LOCAL` côté
    backend) ; NULL = script système. Le rôle applicatif n'a ni UPDATE ni DELETE ici.
    """

    __tablename__ = "catalogue_audit_log"

    table_name: Mapped[Str]
    row_id: Mapped[uuid.UUID]
    action: Mapped[Str]
    actor_id: Mapped[uuid.UUID | None] = fk("user_account.id", ondelete="RESTRICT")
    old_values: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    new_values: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    changed_fields: Mapped[list[str] | None] = mapped_column(ARRAY(Text))

    __table_args__ = (
        CheckConstraint(f"table_name IN {sql_list(enums.CATALOGUE_TABLES)}", name="table_name"),
        enum_check("action", enums.CATALOGUE_AUDIT_ACTION),
        CheckConstraint("old_values IS NOT NULL OR new_values IS NOT NULL", name="values"),
        Index("ix_catalogue_audit_log_row", "table_name", "row_id", text("created_at DESC")),
        Index("ix_catalogue_audit_log_actor", "actor_id", text("created_at DESC")),
    )


# ============ F. Révisions des entités stables publiées (SA-20 D1, validée 17/11) ============


class CatalogueRevision(UUIDPrimaryKey, Timestamps, Base):
    """Révision proposée d'une entité stable publiée (institution, programme, speciality).

    Les champs proposés sont stockés à part (`changes`, jsonb) : la ligne publiée reste
    visible telle quelle jusqu'à la publication de la révision (4 yeux), qui applique alors
    les changements sur place (tracés par `audit_catalogue()`). Un rejet abandonne la révision.
    Cycle : `draft → pending_review → published | rejected` ; au plus une révision ouverte
    (draft ou pending_review) par entité.
    """

    __tablename__ = "catalogue_revision"

    entity_type: Mapped[Str]
    entity_id: Mapped[uuid.UUID]
    status: Mapped[str] = mapped_column(Text, server_default=text("'draft'"))
    changes: Mapped[dict[str, Any]] = mapped_column(JSONB)
    reason_fr: Mapped[StrNull]
    created_by: Mapped[uuid.UUID] = fk("user_account.id", nullable=False)
    submitted_by: Mapped[uuid.UUID | None] = fk("user_account.id")
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_by: Mapped[uuid.UUID | None] = fk("user_account.id")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejected_by: Mapped[uuid.UUID | None] = fk("user_account.id")
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejection_reason: Mapped[StrNull]

    __table_args__ = (
        enum_check("entity_type", enums.REVISABLE_ENTITY_TYPE),
        enum_check("status", enums.REVISION_STATUS),
        CheckConstraint(
            "jsonb_typeof(changes) = 'object' AND changes <> '{}'::jsonb", name="changes"
        ),
        CheckConstraint(
            "status NOT IN ('pending_review','published') OR "
            "(submitted_by IS NOT NULL AND submitted_at IS NOT NULL)",
            name="submitted",
        ),
        CheckConstraint(
            "status <> 'published' OR (published_by IS NOT NULL AND published_at IS NOT NULL)",
            name="published",
        ),
        CheckConstraint(
            "status <> 'rejected' OR (rejected_by IS NOT NULL AND rejected_at IS NOT NULL)",
            name="rejected",
        ),
        CheckConstraint("published_by IS NULL OR published_by <> submitted_by", name="four_eyes"),
        Index(
            "uq_catalogue_revision_open",
            "entity_type",
            "entity_id",
            unique=True,
            postgresql_where=text("status IN ('draft','pending_review')"),
        ),
        Index("ix_catalogue_revision_entity", "entity_type", "entity_id", text("created_at DESC")),
    )


__all__ = [
    "AdmissionCondition",
    "AdmissionSubjectRequirement",
    "Bridge",
    "CatalogueAuditLog",
    "CatalogueRevision",
    "Curriculum",
    "CurriculumSubject",
    "FeeSchedule",
    "Institution",
    "PaymentInstallment",
    "PaymentPlan",
    "Prerequisite",
    "Programme",
    "Speciality",
    "Subject",
]
