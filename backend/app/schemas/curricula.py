"""Schémas Pydantic des cursus et de leurs matières (SA-20).

Un cursus (`curriculum`) est un fait versionné publiable (SA-12 catégorie B) ; ses matières
(`curriculum_subject`) sont des enfants modifiables seulement quand le cursus est `draft`.
Les crédits, coefficients et heures sont des décimaux exacts, rendus en chaîne dans le JSON.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.catalogue_common import AcademicYear, SourceRef, ValidityPeriod
from app.schemas.programmes import PublicationFields, SpecialityRef

_FORBID = ConfigDict(extra="forbid")


# ============ Lecture publique ============


class PrerequisitePublic(BaseModel):
    subject_code: str | None
    subject_name: str | None
    knowledge: str | None = Field(description="Connaissance attendue (texte libre officiel).")
    is_mandatory: bool


class CurriculumSubjectPublic(BaseModel):
    id: uuid.UUID = Field(description="Identifiant de la matière (référentiel `subject`).")
    code: str
    name: str
    name_ar: str | None
    teaching_unit_code: str | None
    teaching_unit_name: str | None
    coefficient: Decimal
    credits: Decimal
    hours_lecture: Decimal
    hours_tutorial: Decimal
    hours_practical: Decimal
    hours: Decimal | None = Field(description="Total d'heures (colonne générée, jamais calculé).")
    is_elective: bool
    prerequisites: list[PrerequisitePublic]


class SemesterPublic(BaseModel):
    semester: int
    year_of_study: int = Field(description="Année d'études : (semestre + 1) // 2.")
    total_credits: Decimal = Field(description="Somme des crédits du semestre (calcul par code).")
    subjects: list[CurriculumSubjectPublic]


class CurriculumPublic(BaseModel):
    """Cursus publié et valide d'une formation (ou d'une spécialité)."""

    id: uuid.UUID
    programme_id: uuid.UUID
    speciality: SpecialityRef | None
    version_label: str
    academic_year: str = Field(description="Première année universitaire d'application.")
    total_ects: int | None
    computed_total_credits: Decimal = Field(description="Somme des crédits des matières.")
    notes: str | None
    semesters: list[SemesterPublic]
    source: SourceRef


class CurriculumList(BaseModel):
    items: list[CurriculumPublic]


# ============ Staff ============


class CurriculumCreate(ValidityPeriod):
    model_config = _FORBID

    programme_id: uuid.UUID
    speciality_id: uuid.UUID | None = None
    version_label: str = Field(min_length=1, max_length=50, examples=["v2026"])
    academic_year: AcademicYear
    total_ects: int | None = Field(default=None, gt=0, le=600)
    notes_fr: str | None = None


class CurriculumUpdate(ValidityPeriod):
    model_config = _FORBID

    version_label: str | None = Field(default=None, min_length=1, max_length=50)
    academic_year: AcademicYear | None = None
    total_ects: int | None = Field(default=None, gt=0, le=600)
    notes_fr: str | None = None


class CurriculumNewVersion(ValidityPeriod):
    """Corps de `POST /staff/catalogue/curricula/{id}/new-version`."""

    model_config = _FORBID

    version_label: str = Field(min_length=1, max_length=50, examples=["v2027"])
    academic_year: AcademicYear | None = None


class CurriculumSubjectCreate(BaseModel):
    model_config = _FORBID

    subject_id: uuid.UUID
    semester: int = Field(ge=1, le=10)
    teaching_unit_code: str | None = Field(default=None, max_length=32)
    teaching_unit_name_fr: str | None = Field(default=None, max_length=300)
    coefficient: Decimal = Field(gt=0, max_digits=4, decimal_places=2)
    ects_credits: Decimal = Field(ge=0, max_digits=4, decimal_places=1)
    hours_lecture: Decimal = Field(default=Decimal(0), ge=0, max_digits=5, decimal_places=1)
    hours_tutorial: Decimal = Field(default=Decimal(0), ge=0, max_digits=5, decimal_places=1)
    hours_practical: Decimal = Field(default=Decimal(0), ge=0, max_digits=5, decimal_places=1)
    is_elective: bool = False


class CurriculumSubjectUpdate(BaseModel):
    model_config = _FORBID

    semester: int | None = Field(default=None, ge=1, le=10)
    teaching_unit_code: str | None = Field(default=None, max_length=32)
    teaching_unit_name_fr: str | None = Field(default=None, max_length=300)
    coefficient: Decimal | None = Field(default=None, gt=0, max_digits=4, decimal_places=2)
    ects_credits: Decimal | None = Field(default=None, ge=0, max_digits=4, decimal_places=1)
    hours_lecture: Decimal | None = Field(default=None, ge=0, max_digits=5, decimal_places=1)
    hours_tutorial: Decimal | None = Field(default=None, ge=0, max_digits=5, decimal_places=1)
    hours_practical: Decimal | None = Field(default=None, ge=0, max_digits=5, decimal_places=1)
    is_elective: bool | None = None


class CurriculumSubjectStaff(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    curriculum_id: uuid.UUID
    subject_id: uuid.UUID
    semester: int
    teaching_unit_code: str | None
    teaching_unit_name_fr: str | None
    coefficient: Decimal
    ects_credits: Decimal
    hours_lecture: Decimal
    hours_tutorial: Decimal
    hours_practical: Decimal
    hours_total: Decimal | None
    is_elective: bool
    created_at: datetime
    updated_at: datetime


class CurriculumStaff(PublicationFields):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    programme_id: uuid.UUID
    speciality_id: uuid.UUID | None
    version_label: str
    academic_year: str
    total_ects: int | None
    notes_fr: str | None


class CurriculumStaffDetail(CurriculumStaff):
    """Lecture d'un cursus avec ses matières (`GET /staff/catalogue/curricula/{id}`)."""

    subjects: list[CurriculumSubjectStaff]
