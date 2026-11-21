"""Schémas des conditions d'admission, prérequis et vérification d'éligibilité (SA-21).

Tables : `admission_condition` (par année universitaire, D-I), `admission_subject_requirement`,
`prerequisite` (enfant d'un cursus, SA-12). Clés du bac en **français** (C1) : séries
`mathematiques`, `sciences_techniques`… ; matières `mathematiques`, `physique`…
Notes /20 rendues en chaîne décimale (`"12.00"`), jamais en flottant.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from app.models import enums
from app.schemas.catalogue_common import AcademicYear, PublicationInfo, SourceRef, ValidityPeriod

ApplicantCategory = Literal["new_bachelor", "higher_education_graduate", "transfer_student"]
RequiredDiploma = Literal["baccalaureate", "preparatory_cycle", "licence", "other_higher_education"]
AverageBasis = Literal["bac_average", "last_year_average", "cycle_average"]


def _bac_section(value: str) -> str:
    if value not in enums.BAC_SECTION:
        raise ValueError(f"série du bac inconnue ; valeurs : {', '.join(enums.BAC_SECTION)}")
    return value


def _subject_key(value: str) -> str:
    if value not in enums.BAC_SUBJECT_KEY:
        raise ValueError(f"matière inconnue ; valeurs : {', '.join(enums.BAC_SUBJECT_KEY)}")
    return value


#: Série du bac, clé française (C1).
BacSection = Annotated[str, AfterValidator(_bac_section), Field(examples=["mathematiques"])]
#: Matière du bac, clé française (C1).
BacSubjectKey = Annotated[str, AfterValidator(_subject_key), Field(examples=["mathematiques"])]
#: Note /20 (au plus 2 décimales).
Grade = Annotated[Decimal, Field(ge=0, le=20, max_digits=4, decimal_places=2, examples=["14.25"])]


def grade_str(value: Decimal | None) -> str | None:
    return None if value is None else f"{Decimal(value):.2f}"


# --- Entrées staff -------------------------------------------------------------------------------


class SubjectRequirementIn(BaseModel):
    """Note minimale exigée dans une matière du bac."""

    model_config = ConfigDict(extra="forbid")

    subject_key: BacSubjectKey
    subject_name_fr: str = Field(min_length=2, max_length=200, examples=["Mathématiques"])
    min_grade: Grade


def _unique_subjects(items: list[SubjectRequirementIn] | None) -> None:
    if items is None:
        return
    keys = [i.subject_key for i in items]
    if len(keys) != len(set(keys)):
        raise ValueError("une matière ne peut apparaître qu'une fois")


class _ConditionRules(BaseModel):
    """Règles de cohérence (miroir des CHECK de la base, avec un message plus clair).

    En PATCH, seule l'unicité des matières est vérifiée ici : la cohérence finale de la
    ligne est garantie par les CHECK (`ck_admission_condition_average`, `..._bac`).
    """

    @model_validator(mode="after")
    def _rules(self) -> Any:
        data = self.__dict__
        _unique_subjects(data.get("subject_requirements"))
        if not isinstance(self, AdmissionConditionCreate):
            return self
        if (data.get("min_average") is None) != (data.get("average_basis") is None):
            raise ValueError("min_average et average_basis vont ensemble (tous deux ou aucun)")
        if data.get("required_diploma") != "baccalaureate" and data.get("accepted_bac_sections"):
            raise ValueError("accepted_bac_sections n'a de sens que si le diplôme exigé est le bac")
        return self


class AdmissionConditionCreate(ValidityPeriod, _ConditionRules):
    """Création d'une condition d'admission (brouillon) pour une rentrée (D-I)."""

    model_config = ConfigDict(extra="forbid")

    programme_id: uuid.UUID
    speciality_id: uuid.UUID | None = Field(default=None, description="NULL = toute la formation.")
    entry_level: int = Field(default=1, ge=1, le=5, description="Année d'entrée (1 = 1re année).")
    applicant_category: ApplicantCategory = "new_bachelor"
    required_diploma: RequiredDiploma = "baccalaureate"
    accepted_bac_sections: list[BacSection] | None = Field(
        default=None, description="NULL = toutes les séries (ou pas de bac exigé)."
    )
    min_validated_years: int = Field(default=0, ge=0, le=5)
    min_average: Grade | None = None
    average_basis: AverageBasis | None = None
    requires_application_file: bool = True
    requires_test: bool = False
    requires_interview: bool = False
    max_places: int | None = Field(default=None, gt=0)
    academic_year: AcademicYear
    summary_fr: str = Field(min_length=5, max_length=2000)
    subject_requirements: list[SubjectRequirementIn] = Field(default_factory=list)


class AdmissionConditionUpdate(_ConditionRules):
    """Modification partielle d'un brouillon ; `subject_requirements` fourni = remplace."""

    model_config = ConfigDict(extra="forbid")

    speciality_id: uuid.UUID | None = None
    entry_level: int | None = Field(default=None, ge=1, le=5)
    applicant_category: ApplicantCategory | None = None
    required_diploma: RequiredDiploma | None = None
    accepted_bac_sections: list[BacSection] | None = None
    min_validated_years: int | None = Field(default=None, ge=0, le=5)
    min_average: Grade | None = None
    average_basis: AverageBasis | None = None
    requires_application_file: bool | None = None
    requires_test: bool | None = None
    requires_interview: bool | None = None
    max_places: int | None = Field(default=None, gt=0)
    academic_year: AcademicYear | None = None
    summary_fr: str | None = Field(default=None, min_length=5, max_length=2000)
    subject_requirements: list[SubjectRequirementIn] | None = None
    valid_from: date | None = None
    valid_to: date | None = None


class PrerequisiteCreate(BaseModel):
    """Prérequis d'un cursus **brouillon** (matière exigée et/ou connaissance attendue)."""

    model_config = ConfigDict(extra="forbid")

    curriculum_id: uuid.UUID
    curriculum_subject_id: uuid.UUID | None = Field(
        default=None, description="Matière cible ; NULL = prérequis du cursus entier."
    )
    required_subject_id: uuid.UUID | None = None
    required_knowledge_fr: str | None = Field(default=None, max_length=2000)
    is_mandatory: bool = True

    @model_validator(mode="after")
    def _content(self) -> PrerequisiteCreate:
        if self.required_subject_id is None and not self.required_knowledge_fr:
            raise ValueError("required_subject_id ou required_knowledge_fr est obligatoire")
        return self


class PrerequisiteUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    curriculum_subject_id: uuid.UUID | None = None
    required_subject_id: uuid.UUID | None = None
    required_knowledge_fr: str | None = Field(default=None, max_length=2000)
    is_mandatory: bool | None = None


# --- Sorties -----------------------------------------------------------------------------------


class SubjectRequirementOut(BaseModel):
    id: uuid.UUID
    subject_key: str
    subject_name_fr: str
    min_grade: str = Field(examples=["12.00"])


class ConditionFields(BaseModel):
    """Champs métier d'une condition d'admission."""

    id: uuid.UUID
    programme_id: uuid.UUID
    speciality_id: uuid.UUID | None
    entry_level: int
    applicant_category: str
    required_diploma: str
    accepted_bac_sections: list[str] | None
    min_validated_years: int
    min_average: str | None
    average_basis: str | None
    requires_application_file: bool
    requires_test: bool
    requires_interview: bool
    max_places: int | None
    academic_year: str
    summary_fr: str
    subject_requirements: list[SubjectRequirementOut]


class AdmissionConditionStaffOut(PublicationInfo, ConditionFields):
    """Ligne complète pour le staff (tous statuts)."""

    etag: str


class AdmissionConditionOfficial(ConditionFields):
    """Condition officielle (publiée et valide) vue par le public et l'agent."""

    label: str = Field(description="Libellé lisible (= summary_fr), cité dans la carte source.")
    scope: Literal["programme", "speciality"]
    source: SourceRef


class PrerequisiteOut(BaseModel):
    id: uuid.UUID
    curriculum_id: uuid.UUID
    curriculum_subject_id: uuid.UUID | None
    required_subject_id: uuid.UUID | None
    required_subject_name_fr: str | None = None
    required_knowledge_fr: str | None
    is_mandatory: bool


class PrerequisiteOfficial(PrerequisiteOut):
    label: str
    source: SourceRef = Field(description="Version de cursus publiée qui porte ce prérequis.")


class AdmissionConditionsResponse(BaseModel):
    """Réponse de `GET /catalogue/programmes/{id}/admission-conditions` et de l'outil
    `get_admission_conditions`."""

    programme_id: uuid.UUID
    speciality_id: uuid.UUID | None
    academic_year: str
    as_of: date
    conditions: list[AdmissionConditionOfficial] = Field(
        description=(
            "Une condition par (année d'entrée, catégorie de candidat) : celle de la spécialité "
            "l'emporte sur celle de la formation (SA-12 D7)."
        )
    )
    prerequisites: list[PrerequisiteOfficial] = Field(
        description="Prérequis du cursus entier (informatifs) de la version de cursus en vigueur."
    )
    available_academic_years: list[str]


# --- Éligibilité (outil check_eligibility, POST /catalogue/eligibility-check) -----------------

CriterionStatus = Literal["met", "not_met", "unknown"]
EligibilityStatus = Literal["met", "not_met", "unknown", "no_official_condition"]


class BacProfile(BaseModel):
    """Profil scolaire comparé aux conditions publiées (aucune donnée conservée)."""

    model_config = ConfigDict(extra="forbid")

    applicant_category: ApplicantCategory = "new_bachelor"
    entry_level: int = Field(default=1, ge=1, le=5)
    bac_section: BacSection | None = Field(default=None, description="Série du bac (clé FR).")
    bac_average: Grade | None = Field(default=None, description="Moyenne générale du bac /20.")
    subject_grades: dict[BacSubjectKey, Grade] = Field(
        default_factory=dict,
        description='Notes du bac par matière (clés FR), ex. {"mathematiques": "15.5"}.',
    )
    highest_diploma: RequiredDiploma | None = Field(
        default=None, description="Diplôme le plus élevé ; déduit = bac si bac_section est donné."
    )
    validated_years: int | None = Field(
        default=None, ge=0, le=10, description="Années d'études supérieures validées."
    )
    last_year_average: Grade | None = None
    cycle_average: Grade | None = None


class EligibilityRequest(BacProfile):
    """Corps de `POST /catalogue/eligibility-check`."""

    programme_id: uuid.UUID
    speciality_id: uuid.UUID | None = None
    academic_year: AcademicYear | None = Field(
        default=None, description="Obligatoire (D-J) ; sinon 422 ACADEMIC_YEAR_REQUIRED."
    )
    as_of: date | None = Field(
        default=None, description="Date de référence (défaut : aujourd'hui à Tunis)."
    )


class CriterionResult(BaseModel):
    """Un critère évalué par le code : attendu, constaté, verdict, explication."""

    condition_id: uuid.UUID
    criterion: str = Field(
        examples=["bac_section", "min_average", "subject_grade:mathematiques"],
        description="Identifiant stable du critère.",
    )
    label: str
    status: CriterionStatus
    met: bool | None = Field(description="Raccourci SA-5 : true / false / null (inconnu).")
    expected: Any = None
    actual: Any = None
    explanation: str


class ConditionVerdict(BaseModel):
    """Verdict pour une condition publiée (une par année d'entrée et catégorie)."""

    condition_id: uuid.UUID
    label: str
    scope: Literal["programme", "speciality"]
    status: CriterionStatus
    criteria: list[CriterionResult]
    next_steps: list[str] = Field(
        description="Étapes de sélection annoncées par la condition (dossier, test, entretien)."
    )
    source: SourceRef


class EligibilityResult(BaseModel):
    """Résultat explicable et **indicatif** : la décision appartient au responsable (D-B)."""

    status: EligibilityStatus
    programme_id: uuid.UUID
    speciality_id: uuid.UUID | None
    academic_year: str
    as_of: date
    computed_by: Literal["code"] = "code"
    verdicts: list[ConditionVerdict]
    criteria: list[CriterionResult] = Field(description="Tous les critères, à plat (SA-5).")
    missing_information: list[str] = Field(
        description="Champs du profil à demander au candidat pour lever les « unknown »."
    )
    disclaimer: str = "Résultat indicatif : la décision d'admission appartient au responsable."
