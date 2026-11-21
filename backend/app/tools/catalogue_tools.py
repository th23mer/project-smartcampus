"""Outils d'agent déterministes du catalogue (SA-21) : `get_fees`, `get_admission_conditions`,
`check_eligibility`.

**Pas de LLM ici.** Ces fonctions lisent seulement des données **publiées et valides** à la date
(défaut : aujourd'hui à Tunis) et appellent les mêmes services que les endpoints publics
(SA-5 §2.1). Les montants et totaux viennent de la base (colonne générée `annual_total`) ;
l'éligibilité est un calcul de code, critère par critère.

Contrat pour E4 (orchestrateur) :

- chaque outil est une coroutine `outil(session, params, *, user=None)` ; `params` est un modèle
  Pydantic (schéma JSON prêt pour le « tool calling » : `TOOL_SPECS`) ;
- le résultat est **toujours** un objet : succès `{"ok": true, "data": ...}` ou erreur
  structurée `{"ok": false, "code", "message", "details"}` (jamais d'exception métier) ;
- `ACADEMIC_YEAR_REQUIRED` (D-J) : l'année manque → `details.available_academic_years` liste les
  années officielles ; **l'agent demande l'année au candidat** (ne pas deviner) ;
- `NOT_FOUND` : formation / spécialité inconnue ou non publiée à la date ;
- chaque donnée renvoyée porte une carte `source` (entity_type, entity_id, version,
  published_at, valid_from, valid_to) à citer dans la réponse (F1) ;
- `user` est accepté pour l'uniformité des outils (l'agent n'a jamais plus de droits que
  l'utilisateur servi) ; ces lectures sont publiques et ne l'utilisent pas.

Les formations et spécialités se désignent par **code** (ex. `LIC-INFO`, `GL`, SA-12 §0) ou
par identifiant.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ErrorCode
from app.core.security import CurrentUser
from app.models import Programme, Speciality
from app.schemas.admission import AdmissionConditionsResponse, BacProfile, EligibilityResult
from app.schemas.catalogue_common import AcademicYear
from app.schemas.fees import FeesResponse
from app.services.catalogue import admission as admission_svc
from app.services.catalogue import fees as fees_svc
from app.services.catalogue.publication import official_filter, today_tunis

# --- Contrats communs ----------------------------------------------------------------------------


class ToolError(BaseModel):
    """Erreur structurée renvoyée à l'agent (codes SA-5 §1.4)."""

    ok: Literal[False] = False
    code: str = Field(examples=["ACADEMIC_YEAR_REQUIRED"])
    message: str
    details: Any = None


class ProgrammeTarget(BaseModel):
    """Formation visée (code ou id) et spécialité facultative (code ou id)."""

    model_config = ConfigDict(extra="forbid")

    programme_code: str | None = Field(default=None, examples=["LIC-INFO"])
    programme_id: uuid.UUID | None = None
    speciality_code: str | None = Field(default=None, examples=["GL"])
    speciality_id: uuid.UUID | None = None
    academic_year: AcademicYear | None = Field(
        default=None,
        description=(
            "Année universitaire (ex. 2026-2027). Obligatoire : si elle manque, l'outil renvoie "
            "ACADEMIC_YEAR_REQUIRED avec les années disponibles, et l'agent la demande."
        ),
    )
    as_of: date | None = Field(
        default=None, description="Date de référence ; défaut : aujourd'hui (Africa/Tunis)."
    )

    @model_validator(mode="after")
    def _one_programme(self) -> ProgrammeTarget:
        if (self.programme_code is None) == (self.programme_id is None):
            raise ValueError("indiquer exactement un de programme_code ou programme_id")
        if self.speciality_code is not None and self.speciality_id is not None:
            raise ValueError("indiquer au plus un de speciality_code ou speciality_id")
        return self


class GetFeesInput(ProgrammeTarget):
    """Entrée de `get_fees`."""

    study_year: int | None = Field(
        default=None, ge=1, le=6, description="Année d'études (1 = 1re année) ; défaut : toutes."
    )
    student_category: Literal["tunisian", "foreign"] | None = Field(
        default=None, description="Catégorie tarifaire ; défaut : toutes."
    )


class GetAdmissionConditionsInput(ProgrammeTarget):
    """Entrée de `get_admission_conditions`."""

    entry_level: int | None = Field(default=None, ge=1, le=5)
    applicant_category: (
        Literal["new_bachelor", "higher_education_graduate", "transfer_student"] | None
    ) = None


class CheckEligibilityInput(ProgrammeTarget):
    """Entrée de `check_eligibility` : cible + profil scolaire (clés FR, C1)."""

    profile: BacProfile


class FeesResult(BaseModel):
    ok: Literal[True] = True
    data: FeesResponse


class AdmissionConditionsResult(BaseModel):
    ok: Literal[True] = True
    data: AdmissionConditionsResponse


class EligibilityToolResult(BaseModel):
    ok: Literal[True] = True
    data: EligibilityResult


# --- Résolution des cibles -----------------------------------------------------------------------


async def _resolve(
    session: AsyncSession, target: ProgrammeTarget, as_of: date
) -> tuple[uuid.UUID, uuid.UUID | None]:
    """Code → identifiant (formation publiée et valide ; spécialité de cette formation)."""
    programme_id = target.programme_id
    if programme_id is None:
        programme_id = await session.scalar(
            select(Programme.id).where(
                Programme.code == target.programme_code, official_filter(Programme, as_of)
            )
        )
        if programme_id is None:
            raise AppError(
                ErrorCode.NOT_FOUND,
                message="Formation introuvable ou non publiée à cette date.",
                details={"programme_code": target.programme_code},
            )
    speciality_id = target.speciality_id
    if target.speciality_code is not None:
        speciality_id = await session.scalar(
            select(Speciality.id).where(
                Speciality.programme_id == programme_id,
                Speciality.code == target.speciality_code,
                official_filter(Speciality, as_of),
            )
        )
        if speciality_id is None:
            raise AppError(
                ErrorCode.NOT_FOUND,
                message="Spécialité introuvable pour cette formation ou non publiée.",
                details={"speciality_code": target.speciality_code},
            )
    return programme_id, speciality_id


async def _safe[T](call: Callable[[], Awaitable[T]]) -> T | ToolError:
    try:
        return await call()
    except AppError as exc:
        return ToolError(code=str(exc.code), message=exc.message, details=exc.details)


# --- Outils ------------------------------------------------------------------------------------


async def get_fees(
    session: AsyncSession, params: GetFeesInput, *, user: CurrentUser | None = None
) -> FeesResult | ToolError:
    """Frais officiels d'une formation pour une année universitaire (D-A, D-J)."""

    async def run() -> FeesResult:
        as_of = params.as_of or today_tunis()
        programme_id, speciality_id = await _resolve(session, params, as_of)
        data = await fees_svc.official_fees(
            session,
            programme_id,
            params.academic_year,
            as_of,
            speciality_id=speciality_id,
            study_year=params.study_year,
            student_category=params.student_category,
        )
        return FeesResult(data=data)

    return await _safe(run)


async def get_admission_conditions(
    session: AsyncSession,
    params: GetAdmissionConditionsInput,
    *,
    user: CurrentUser | None = None,
) -> AdmissionConditionsResult | ToolError:
    """Conditions d'admission officielles d'une rentrée (D-I, D-J)."""

    async def run() -> AdmissionConditionsResult:
        as_of = params.as_of or today_tunis()
        programme_id, speciality_id = await _resolve(session, params, as_of)
        data = await admission_svc.official_conditions(
            session,
            programme_id,
            params.academic_year,
            as_of,
            speciality_id=speciality_id,
            entry_level=params.entry_level,
            applicant_category=params.applicant_category,
        )
        return AdmissionConditionsResult(data=data)

    return await _safe(run)


async def check_eligibility(
    session: AsyncSession, params: CheckEligibilityInput, *, user: CurrentUser | None = None
) -> EligibilityToolResult | ToolError:
    """Compare le profil bac aux conditions publiées : verdict critère par critère
    (`met` / `not_met` / `unknown`) + source officielle. **Indicatif** : la décision reste
    humaine ; l'agent doit le dire et demander les informations de `missing_information`."""

    async def run() -> EligibilityToolResult:
        as_of = params.as_of or today_tunis()
        programme_id, speciality_id = await _resolve(session, params, as_of)
        data = await admission_svc.check_eligibility(
            session,
            programme_id,
            params.academic_year,
            as_of,
            params.profile,
            speciality_id=speciality_id,
        )
        return EligibilityToolResult(data=data)

    return await _safe(run)


# --- Déclaration pour E4 -------------------------------------------------------------------------

#: Description des outils pour l'orchestrateur (nom, description FR, schéma JSON d'entrée).
TOOL_SPECS: list[dict[str, Any]] = [
    {
        "name": "get_fees",
        "kind": "deterministic",
        "description": (
            "Frais officiels (inscription, scolarité, autres frais, total annuel, plans de "
            "paiement) d'une formation pour une année universitaire. Exige academic_year : "
            "sinon renvoie ACADEMIC_YEAR_REQUIRED et la liste des années disponibles ; "
            "demander alors l'année au candidat. Ne jamais recalculer les montants."
        ),
        "input_schema": GetFeesInput.model_json_schema(),
        "function": get_fees,
    },
    {
        "name": "get_admission_conditions",
        "kind": "deterministic",
        "description": (
            "Conditions d'admission officielles (diplôme, séries du bac, moyenne, notes "
            "minimales, test, entretien) et prérequis d'une formation pour une rentrée. "
            "Exige academic_year (même règle que get_fees)."
        ),
        "input_schema": GetAdmissionConditionsInput.model_json_schema(),
        "function": get_admission_conditions,
    },
    {
        "name": "check_eligibility",
        "kind": "deterministic",
        "description": (
            "Vérifie, par le code, si un profil de bachelier (série, moyenne, notes par matière, "
            "clés françaises) satisfait les conditions publiées d'une formation. Renvoie un "
            "verdict par critère (met / not_met / unknown) et les informations manquantes. "
            "Résultat indicatif : la décision d'admission appartient au responsable."
        ),
        "input_schema": CheckEligibilityInput.model_json_schema(),
        "function": check_eligibility,
    },
]

__all__ = [
    "TOOL_SPECS",
    "AdmissionConditionsResult",
    "CheckEligibilityInput",
    "EligibilityToolResult",
    "FeesResult",
    "GetAdmissionConditionsInput",
    "GetFeesInput",
    "ToolError",
    "check_eligibility",
    "get_admission_conditions",
    "get_fees",
]
