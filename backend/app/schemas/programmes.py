"""Schémas Pydantic des formations, spécialités, matières, passerelles (SA-20).

Deux familles :
- **publiques** (`/catalogue/...`) : seulement des données publiées et valides, avec une
  référence de source officielle (`SourceRef`) pour les cartes source du chat ;
- **staff** (`/staff/catalogue/...`) : toutes les colonnes + le bloc de publication (D-B).

Les noms de champs suivent SA-5 (`name`, `level`, `institution`, `source`…). `level` reprend
les valeurs de `programme_type` (SA-3) : `preparatory`, `licence`, `engineering`, `master`, `other`.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.catalogue_common import PublicationInfo, SourceRef, ValidityPeriod

ProgrammeType = Literal["preparatory", "licence", "engineering", "master", "other"]
AccessMode = Literal["automatic", "on_application", "competitive_exam"]

CODE_PATTERN = r"^[A-Z0-9_-]{2,32}$"


# ============ Lecture publique ============


class InstitutionPublic(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    name_ar: str | None
    city: str
    website_url: str | None
    description: str | None
    source: SourceRef


class ProgrammeRef(BaseModel):
    """Résumé d'une formation (dans une passerelle, une spécialité…)."""

    id: uuid.UUID
    code: str
    name: str
    institution: str = Field(description="Code de l'établissement (IIT, ISB).")
    level: ProgrammeType


class SpecialityRef(BaseModel):
    id: uuid.UUID
    code: str
    name: str


class ProgrammeSummary(BaseModel):
    """Élément de la liste `GET /catalogue/programmes`."""

    id: uuid.UUID
    code: str
    name: str
    name_ar: str | None
    institution: str
    institution_id: uuid.UUID
    level: ProgrammeType
    diploma_name: str | None
    duration_years: int
    total_ects: int | None
    speciality_count: int
    source: SourceRef


class SpecialityPublic(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    name_ar: str | None
    description: str | None
    career_outcomes: str | None
    programme: ProgrammeRef
    source: SourceRef


class BridgePublic(BaseModel):
    """Passerelle publiée et valide (SA-5 `GET /catalogue/bridges`)."""

    id: uuid.UUID
    from_programme: ProgrammeRef
    from_speciality: SpecialityRef | None
    after_years: int = Field(description="Années validées exigées dans le parcours de départ.")
    to_programme: ProgrammeRef
    to_speciality: SpecialityRef | None
    entry_level: int = Field(description="Année d'entrée dans le parcours d'arrivée (1 à 5).")
    access_mode: AccessMode
    label: str = Field(description="Résumé officiel des conditions (conditions_summary_fr).")
    source: SourceRef


class ProgrammeDetail(ProgrammeSummary):
    """Fiche formation : spécialités, débouchés, passerelles au départ et à l'arrivée."""

    institution_name: str
    description: str | None
    career_outcomes: str | None
    specialities: list[SpecialityPublic]
    bridges_from: list[BridgePublic] = Field(description="Passerelles au départ de la formation.")
    bridges_to: list[BridgePublic] = Field(description="Passerelles qui mènent à la formation.")


class InstitutionList(BaseModel):
    items: list[InstitutionPublic]


# ============ Staff ============

#: Bloc de publication (lecture seule), partagé avec SA-21.
PublicationFields = PublicationInfo
_Validity = ValidityPeriod
_FORBID = ConfigDict(extra="forbid")


# --- Établissement (lecture seule) ---


class InstitutionStaff(PublicationFields):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name_fr: str
    name_ar: str | None
    city: str
    website_url: str | None
    description_fr: str | None


# --- Formation ---


class ProgrammeCreate(_Validity):
    model_config = _FORBID

    institution_id: uuid.UUID
    code: str = Field(pattern=CODE_PATTERN, examples=["IIT-LIC-INFO"])
    name_fr: str = Field(min_length=2, max_length=300)
    name_ar: str | None = Field(default=None, max_length=300)
    programme_type: ProgrammeType
    diploma_name_fr: str | None = Field(default=None, max_length=300)
    duration_years: int = Field(ge=1, le=6)
    total_ects: int | None = Field(default=None, gt=0, le=600)
    description_fr: str | None = None
    career_outcomes_fr: str | None = None


class ProgrammeUpdate(_Validity):
    """Champs modifiables d'un brouillon (l'établissement ne change pas)."""

    model_config = _FORBID

    code: str | None = Field(default=None, pattern=CODE_PATTERN)
    name_fr: str | None = Field(default=None, min_length=2, max_length=300)
    name_ar: str | None = Field(default=None, max_length=300)
    programme_type: ProgrammeType | None = None
    diploma_name_fr: str | None = Field(default=None, max_length=300)
    duration_years: int | None = Field(default=None, ge=1, le=6)
    total_ects: int | None = Field(default=None, gt=0, le=600)
    description_fr: str | None = None
    career_outcomes_fr: str | None = None


class ProgrammeStaff(PublicationFields):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    institution_id: uuid.UUID
    code: str
    name_fr: str
    name_ar: str | None
    programme_type: ProgrammeType
    diploma_name_fr: str | None
    duration_years: int
    total_ects: int | None
    description_fr: str | None
    career_outcomes_fr: str | None


# --- Spécialité ---


class SpecialityCreate(_Validity):
    model_config = _FORBID

    programme_id: uuid.UUID
    code: str = Field(pattern=CODE_PATTERN, examples=["GL"])
    name_fr: str = Field(min_length=2, max_length=300)
    name_ar: str | None = Field(default=None, max_length=300)
    description_fr: str | None = None
    career_outcomes_fr: str | None = None


class SpecialityUpdate(_Validity):
    model_config = _FORBID

    code: str | None = Field(default=None, pattern=CODE_PATTERN)
    name_fr: str | None = Field(default=None, min_length=2, max_length=300)
    name_ar: str | None = Field(default=None, max_length=300)
    description_fr: str | None = None
    career_outcomes_fr: str | None = None


class SpecialityStaff(PublicationFields):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    programme_id: uuid.UUID
    code: str
    name_fr: str
    name_ar: str | None
    description_fr: str | None
    career_outcomes_fr: str | None


# --- Matière (référentiel interne, sans publication) ---


class SubjectCreate(BaseModel):
    model_config = _FORBID

    institution_id: uuid.UUID
    code: str = Field(pattern=CODE_PATTERN, examples=["ASD1"])
    name_fr: str = Field(min_length=2, max_length=300)
    name_ar: str | None = Field(default=None, max_length=300)
    domain: str | None = Field(default=None, max_length=100)
    description_fr: str | None = None
    learning_outcomes_fr: str | None = None


class SubjectUpdate(BaseModel):
    model_config = _FORBID

    code: str | None = Field(default=None, pattern=CODE_PATTERN)
    name_fr: str | None = Field(default=None, min_length=2, max_length=300)
    name_ar: str | None = Field(default=None, max_length=300)
    domain: str | None = Field(default=None, max_length=100)
    description_fr: str | None = None
    learning_outcomes_fr: str | None = None


class SubjectStaff(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    institution_id: uuid.UUID
    code: str
    name_fr: str
    name_ar: str | None
    domain: str | None
    description_fr: str | None
    learning_outcomes_fr: str | None
    created_at: datetime
    updated_at: datetime


# --- Passerelle (fait versionné) ---


class BridgeCreate(_Validity):
    model_config = _FORBID

    source_programme_id: uuid.UUID
    source_speciality_id: uuid.UUID | None = None
    source_min_completed_years: int = Field(ge=0, le=6)
    target_programme_id: uuid.UUID
    target_speciality_id: uuid.UUID | None = None
    target_entry_level: int = Field(ge=1, le=5)
    access_mode: AccessMode
    conditions_summary_fr: str = Field(min_length=5)

    @model_validator(mode="after")
    def _distinct(self):
        if (
            self.source_programme_id == self.target_programme_id
            and self.source_speciality_id == self.target_speciality_id
        ):
            raise ValueError("Le parcours d'arrivée doit différer du parcours de départ.")
        return self


class BridgeUpdate(_Validity):
    model_config = _FORBID

    source_min_completed_years: int | None = Field(default=None, ge=0, le=6)
    target_entry_level: int | None = Field(default=None, ge=1, le=5)
    access_mode: AccessMode | None = None
    conditions_summary_fr: str | None = Field(default=None, min_length=5)


class BridgeStaff(PublicationFields):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_programme_id: uuid.UUID
    source_speciality_id: uuid.UUID | None
    source_min_completed_years: int
    target_programme_id: uuid.UUID
    target_speciality_id: uuid.UUID | None
    target_entry_level: int
    access_mode: AccessMode
    conditions_summary_fr: str


class BridgeNewVersion(_Validity):
    """Corps de `POST /staff/catalogue/bridges/{id}/new-version` (tout est facultatif)."""

    model_config = _FORBID


# ============ Révisions des entités stables publiées (SA-20 D1, validée 17/11) ============

RevisionStatus = Literal["draft", "pending_review", "published", "rejected"]


class InstitutionUpdate(BaseModel):
    """Champs révisables d'un établissement publié."""

    model_config = _FORBID

    name_fr: str | None = Field(default=None, min_length=2, max_length=300)
    name_ar: str | None = Field(default=None, max_length=300)
    city: str | None = Field(default=None, min_length=2, max_length=100)
    website_url: str | None = Field(default=None, max_length=500)
    description_fr: str | None = None


class RevisionCreate(BaseModel):
    """Corps de `POST /staff/catalogue/{entity}/{id}/revisions`.

    `changes` : champs proposés, mêmes noms et règles que le PATCH d'un brouillon de l'entité ;
    `valid_from` / `valid_to` exclus (la fin d'une offre passe par l'archivage).
    """

    model_config = _FORBID

    changes: dict[str, Any] = Field(
        min_length=1, examples=[{"description_fr": "Nouveau texte officiel (fictif)."}]
    )
    reason_fr: str | None = Field(default=None, max_length=2000, examples=["Débouchés mis à jour"])


class RevisionOut(BaseModel):
    """Révision proposée (lecture staff) ; `current` = valeurs publiées des champs concernés."""

    id: uuid.UUID
    entity_type: Literal["institution", "programme", "speciality"]
    entity_id: uuid.UUID
    status: RevisionStatus
    changes: dict[str, Any]
    current: dict[str, Any]
    reason_fr: str | None
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime
    submitted_by: uuid.UUID | None
    submitted_at: datetime | None
    published_by: uuid.UUID | None
    published_at: datetime | None
    rejected_by: uuid.UUID | None
    rejected_at: datetime | None
    rejection_reason: str | None
