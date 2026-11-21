"""Conditions d'admission, prérequis et éligibilité (SA-21).

- `admission_condition` : une condition officielle par (formation, spécialité, année d'entrée,
  catégorie de candidat, **année universitaire**) et par période (D-I) ; enfants
  `admission_subject_requirement` (notes minimales par matière, clés FR, C1).
- `prerequisite` : enfant d'une version de cursus (SA-20) ; écrit ici seulement quand le
  cursus est `draft`, lu avec les conditions (prérequis du cursus entier).
- Éligibilité : **calcul de code**, critère par critère (OK / KO / inconnu), avec la référence
  de la condition publiée utilisée. Aucun LLM, aucune donnée personnelle conservée.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ErrorCode
from app.core.pagination import PageParams
from app.core.security import CurrentUser
from app.models import (
    AdmissionCondition,
    AdmissionSubjectRequirement,
    Curriculum,
    Prerequisite,
    Subject,
)
from app.schemas.admission import (
    AdmissionConditionCreate,
    AdmissionConditionOfficial,
    AdmissionConditionsResponse,
    AdmissionConditionStaffOut,
    AdmissionConditionUpdate,
    BacProfile,
    ConditionVerdict,
    CriterionResult,
    EligibilityResult,
    PrerequisiteCreate,
    PrerequisiteOfficial,
    PrerequisiteOut,
    PrerequisiteUpdate,
    SubjectRequirementOut,
    grade_str,
)
from app.services.catalogue.deletion import ensure_deletable
from app.services.catalogue.publication import (
    Action,
    PublishableSpec,
    academic_year_required,
    authorize,
    check_if_match,
    compute_etag,
    ensure_draft,
    ensure_official_programme,
    get_for_staff,
    institution_of,
    load_for_update,
    most_specific,
    official_academic_years,
    official_filter,
    programme_institution_expr,
    programme_institution_id,
    same_key,
    scope_filter,
    source_ref,
    staff_scope,
)
from app.services.catalogue.tx import flush_or_translate, staff_transaction

# --- Déclaration de l'entité publiable ---------------------------------------------------------


def _condition_key(row: AdmissionCondition) -> list:
    """Clé métier de `ex_admission_condition_one_published` (D-I)."""
    return same_key(
        (AdmissionCondition.programme_id, row.programme_id),
        (AdmissionCondition.speciality_id, row.speciality_id),
        (AdmissionCondition.entry_level, row.entry_level),
        (AdmissionCondition.applicant_category, row.applicant_category),
        (AdmissionCondition.academic_year, row.academic_year),
    )


async def load_requirements(
    session: AsyncSession, condition_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, list[AdmissionSubjectRequirement]]:
    out: dict[uuid.UUID, list[AdmissionSubjectRequirement]] = {cid: [] for cid in condition_ids}
    if not condition_ids:
        return out
    for req in await session.scalars(
        select(AdmissionSubjectRequirement)
        .where(AdmissionSubjectRequirement.admission_condition_id.in_(condition_ids))
        .order_by(AdmissionSubjectRequirement.subject_key)
        .execution_options(populate_existing=True)
    ):
        out[req.admission_condition_id].append(req)
    return out


async def _copy_requirements(
    session: AsyncSession, src: AdmissionCondition, dst: AdmissionCondition
) -> None:
    for req in (await load_requirements(session, [src.id]))[src.id]:
        session.add(
            AdmissionSubjectRequirement(
                admission_condition_id=dst.id,
                subject_key=req.subject_key,
                subject_name_fr=req.subject_name_fr,
                min_grade=req.min_grade,
            )
        )


ADMISSION_SPEC = PublishableSpec(
    entity_type="admission_condition",
    model=AdmissionCondition,
    institution_expr=lambda: programme_institution_expr(AdmissionCondition.programme_id),
    business_key=_condition_key,
    label_fr="condition d'admission",
    copy_children=_copy_requirements,
)


def _curriculum_spec() -> PublishableSpec:
    """Spécification du cursus déclarée par SA-20 (import tardif : module voisin)."""
    from app.services.catalogue.curricula import CURRICULUM_SPEC

    return CURRICULUM_SPEC


# --- Sérialisation -------------------------------------------------------------------------------


def _requirements_out(reqs: list[AdmissionSubjectRequirement]) -> list[SubjectRequirementOut]:
    return [
        SubjectRequirementOut(
            id=r.id,
            subject_key=r.subject_key,
            subject_name_fr=r.subject_name_fr,
            min_grade=grade_str(r.min_grade) or "0.00",
        )
        for r in reqs
    ]


def _fields(row: AdmissionCondition, reqs: list[AdmissionSubjectRequirement]) -> dict[str, Any]:
    return {
        "id": row.id,
        "programme_id": row.programme_id,
        "speciality_id": row.speciality_id,
        "entry_level": row.entry_level,
        "applicant_category": row.applicant_category,
        "required_diploma": row.required_diploma,
        "accepted_bac_sections": row.accepted_bac_sections,
        "min_validated_years": row.min_validated_years,
        "min_average": grade_str(row.min_average),
        "average_basis": row.average_basis,
        "requires_application_file": row.requires_application_file,
        "requires_test": row.requires_test,
        "requires_interview": row.requires_interview,
        "max_places": row.max_places,
        "academic_year": row.academic_year,
        "summary_fr": row.summary_fr,
        "subject_requirements": _requirements_out(reqs),
    }


async def staff_out(
    session: AsyncSession,
    row: AdmissionCondition,
    reqs: list[AdmissionSubjectRequirement] | None = None,
) -> AdmissionConditionStaffOut:
    if reqs is None:
        reqs = (await load_requirements(session, [row.id]))[row.id]
    return AdmissionConditionStaffOut(
        **_fields(row, reqs),
        etag=compute_etag(row),
        publication_status=row.publication_status,
        valid_from=row.valid_from,
        valid_to=row.valid_to,
        created_by=row.created_by,
        submitted_by=row.submitted_by,
        submitted_at=row.submitted_at,
        published_by=row.published_by,
        published_at=row.published_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


# --- Écriture staff : conditions -----------------------------------------------------------------


async def list_conditions(
    session: AsyncSession,
    user: CurrentUser,
    page: PageParams,
    *,
    programme_id: uuid.UUID | None = None,
    academic_year: str | None = None,
    publication_status: list[str] | None = None,
) -> tuple[list[AdmissionConditionStaffOut], int]:
    conditions = []
    scope = scope_filter(ADMISSION_SPEC, await staff_scope(session, user))
    if scope is not None:
        conditions.append(scope)
    if programme_id:
        conditions.append(AdmissionCondition.programme_id == programme_id)
    if academic_year:
        conditions.append(AdmissionCondition.academic_year == academic_year)
    if publication_status:
        conditions.append(AdmissionCondition.publication_status.in_(publication_status))
    total = await session.scalar(
        select(func.count()).select_from(AdmissionCondition).where(*conditions)
    )
    rows = list(
        await session.scalars(
            select(AdmissionCondition)
            .where(*conditions)
            .order_by(AdmissionCondition.academic_year.desc(), AdmissionCondition.updated_at.desc())
            .offset(page.offset)
            .limit(page.limit)
        )
    )
    reqs = await load_requirements(session, [r.id for r in rows])
    return [await staff_out(session, r, reqs[r.id]) for r in rows], int(total or 0)


async def get_condition(
    session: AsyncSession, row_id: uuid.UUID, user: CurrentUser
) -> AdmissionCondition:
    return await get_for_staff(session, ADMISSION_SPEC, row_id, user)


def _requirement_rows(condition_id: uuid.UUID, items: Sequence[Any]) -> list:
    return [
        AdmissionSubjectRequirement(
            admission_condition_id=condition_id,
            subject_key=i.subject_key,
            subject_name_fr=i.subject_name_fr,
            min_grade=i.min_grade,
        )
        for i in items
    ]


async def create_condition(
    session: AsyncSession, user: CurrentUser, data: AdmissionConditionCreate
) -> AdmissionCondition:
    async with staff_transaction(session, user):
        institution = await programme_institution_id(session, data.programme_id)
        if institution is None:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                details=[{"field": "programme_id", "issue": "not_found", "location": "body"}],
            )
        await authorize(session, user, Action.CREATE, institution, existing=False)
        row = AdmissionCondition(
            **data.model_dump(exclude={"subject_requirements"}),
            publication_status="draft",
            created_by=user.id,
        )
        session.add(row)
        await flush_or_translate(session)
        session.add_all(_requirement_rows(row.id, data.subject_requirements))
        await flush_or_translate(session)
    await session.refresh(row)
    return row


#: Colonnes obligatoires : `null` refusé en PATCH.
_NOT_NULLABLE = {
    "entry_level",
    "applicant_category",
    "required_diploma",
    "min_validated_years",
    "requires_application_file",
    "requires_test",
    "requires_interview",
    "academic_year",
    "summary_fr",
}


async def update_condition(
    session: AsyncSession,
    row_id: uuid.UUID,
    user: CurrentUser,
    data: AdmissionConditionUpdate,
    if_match: str | None,
) -> AdmissionCondition:
    async with staff_transaction(session, user):
        row = await load_for_update(session, ADMISSION_SPEC, row_id)
        await authorize(
            session, user, Action.EDIT, await institution_of(session, ADMISSION_SPEC, row)
        )
        check_if_match(row, if_match, required=True)
        ensure_draft(row)
        changes = data.model_dump(exclude_unset=True, exclude={"subject_requirements"})
        nulls = [k for k, v in changes.items() if v is None and k in _NOT_NULLABLE]
        if nulls:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                details=[{"field": k, "issue": "not_nullable"} for k in nulls],
            )
        for key, value in changes.items():
            setattr(row, key, value)
        if data.subject_requirements is not None:
            await session.execute(
                delete(AdmissionSubjectRequirement).where(
                    AdmissionSubjectRequirement.admission_condition_id == row.id
                )
            )
            session.add_all(_requirement_rows(row.id, data.subject_requirements))
            row.updated_at = func.now()  # l'ETag change aussi quand seules les notes changent
        await flush_or_translate(session)
    await session.refresh(row)
    return row


async def delete_condition(
    session: AsyncSession, row_id: uuid.UUID, user: CurrentUser, if_match: str | None
) -> None:
    async with staff_transaction(session, user):
        row = await load_for_update(session, ADMISSION_SPEC, row_id)
        await authorize(
            session, user, Action.DELETE, await institution_of(session, ADMISSION_SPEC, row)
        )
        check_if_match(row, if_match, required=False)
        ensure_deletable(row)
        await session.execute(delete(AdmissionCondition).where(AdmissionCondition.id == row.id))
    session.expunge(row)


# --- Écriture staff : prérequis (enfants d'un cursus brouillon) --------------------------------


async def _draft_curriculum(
    session: AsyncSession,
    curriculum_id: uuid.UUID,
    user: CurrentUser,
    *,
    create: bool = False,
    if_match: str | None = None,
    if_match_required: bool = False,
    deleting: bool = False,
) -> Curriculum:
    """Cursus parent verrouillé, dans le périmètre, `draft` ; ETag **du cursus** contrôlé
    (obligatoire en PATCH, vérifié s'il est fourni sinon ; comme SA-20 D7)."""
    spec = _curriculum_spec()
    try:
        cur = await load_for_update(session, spec, curriculum_id)
    except AppError as exc:
        if create:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                details=[{"field": "curriculum_id", "issue": "not_found", "location": "body"}],
            ) from exc
        raise
    await authorize(session, user, Action.EDIT, await institution_of(session, spec, cur))
    check_if_match(cur, if_match, required=if_match_required)
    if deleting:  # réponse commune des DELETE du catalogue (deletion.py)
        ensure_deletable(cur, child=True)
    else:
        ensure_draft(cur)
    return cur


async def _curriculum_etag(session: AsyncSession, cur: Curriculum) -> str:
    """Nouvel ETag du cursus après modification d'un prérequis (renvoyé dans `ETag`)."""
    await session.refresh(cur)
    return compute_etag(cur)


def prerequisite_out(row: Prerequisite, subject_name: str | None = None) -> PrerequisiteOut:
    return PrerequisiteOut(
        id=row.id,
        curriculum_id=row.curriculum_id,
        curriculum_subject_id=row.curriculum_subject_id,
        required_subject_id=row.required_subject_id,
        required_subject_name_fr=subject_name,
        required_knowledge_fr=row.required_knowledge_fr,
        is_mandatory=row.is_mandatory,
    )


async def list_prerequisites(
    session: AsyncSession, curriculum_id: uuid.UUID, user: CurrentUser
) -> list[PrerequisiteOut]:
    await get_for_staff(session, _curriculum_spec(), curriculum_id, user)
    rows = await session.execute(
        select(Prerequisite, Subject.name_fr)
        .outerjoin(Subject, Subject.id == Prerequisite.required_subject_id)
        .where(Prerequisite.curriculum_id == curriculum_id)
        .order_by(Prerequisite.created_at)
    )
    return [prerequisite_out(p, name) for p, name in rows]


async def get_prerequisite(
    session: AsyncSession, row_id: uuid.UUID, user: CurrentUser
) -> Prerequisite:
    row = await session.get(Prerequisite, row_id, populate_existing=True)
    if row is None:
        raise AppError(ErrorCode.NOT_FOUND)
    await get_for_staff(session, _curriculum_spec(), row.curriculum_id, user)
    return row


async def create_prerequisite(
    session: AsyncSession, user: CurrentUser, data: PrerequisiteCreate, if_match: str | None = None
) -> tuple[Prerequisite, str]:
    async with staff_transaction(session, user):
        cur = await _draft_curriculum(
            session, data.curriculum_id, user, create=True, if_match=if_match
        )
        row = Prerequisite(**data.model_dump())
        session.add(row)
        cur.updated_at = func.now()
        await flush_or_translate(session)
    await session.refresh(row)
    return row, await _curriculum_etag(session, cur)


async def update_prerequisite(
    session: AsyncSession,
    row_id: uuid.UUID,
    user: CurrentUser,
    data: PrerequisiteUpdate,
    if_match: str | None,
) -> tuple[Prerequisite, str]:
    """PATCH d'un prérequis : If-Match du **cursus** obligatoire (428 / 412)."""
    async with staff_transaction(session, user):
        row = await session.get(Prerequisite, row_id, with_for_update=True, populate_existing=True)
        if row is None:
            raise AppError(ErrorCode.NOT_FOUND)
        cur = await _draft_curriculum(
            session, row.curriculum_id, user, if_match=if_match, if_match_required=True
        )
        changes = data.model_dump(exclude_unset=True)
        if changes.get("is_mandatory", True) is None:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                details=[{"field": "is_mandatory", "issue": "not_nullable"}],
            )
        for key, value in changes.items():
            setattr(row, key, value)
        cur.updated_at = func.now()
        await flush_or_translate(session)
    await session.refresh(row)
    return row, await _curriculum_etag(session, cur)


async def delete_prerequisite(
    session: AsyncSession, row_id: uuid.UUID, user: CurrentUser, if_match: str | None = None
) -> str:
    async with staff_transaction(session, user):
        row = await session.get(Prerequisite, row_id, with_for_update=True)
        if row is None:
            raise AppError(ErrorCode.NOT_FOUND)
        cur = await _draft_curriculum(
            session, row.curriculum_id, user, if_match=if_match, deleting=True
        )
        await session.execute(delete(Prerequisite).where(Prerequisite.id == row.id))
        cur.updated_at = func.now()
    session.expunge(row)
    return await _curriculum_etag(session, cur)


# --- Lecture officielle (public, outil get_admission_conditions) ------------------------------


def _spec_scope(speciality_id: uuid.UUID | None):
    if speciality_id is None:
        return AdmissionCondition.speciality_id.is_(None)
    return or_(
        AdmissionCondition.speciality_id.is_(None),
        AdmissionCondition.speciality_id == speciality_id,
    )


async def _official_condition_rows(
    session: AsyncSession,
    programme_id: uuid.UUID,
    academic_year: str,
    as_of: date,
    speciality_id: uuid.UUID | None,
    entry_level: int | None = None,
    applicant_category: str | None = None,
) -> list[AdmissionCondition]:
    """Conditions officielles retenues après précédence (spécialité > formation, SA-12 D7)."""
    where = [
        official_filter(AdmissionCondition, as_of),
        AdmissionCondition.programme_id == programme_id,
        AdmissionCondition.academic_year == academic_year,
        _spec_scope(speciality_id),
    ]
    if entry_level is not None:
        where.append(AdmissionCondition.entry_level == entry_level)
    if applicant_category is not None:
        where.append(AdmissionCondition.applicant_category == applicant_category)
    candidates = list(await session.scalars(select(AdmissionCondition).where(*where)))
    chosen = most_specific(
        candidates,
        bucket=lambda r: (r.entry_level, r.applicant_category),
        specificity=lambda r: (r.speciality_id is not None,),
    )
    chosen.sort(key=lambda r: (r.entry_level, r.applicant_category))
    return chosen


async def _official_prerequisites(
    session: AsyncSession, programme_id: uuid.UUID, as_of: date, speciality_id: uuid.UUID | None
) -> list[PrerequisiteOfficial]:
    """Prérequis du cursus entier de la version de cursus officielle (spécialité d'abord)."""
    spec = _curriculum_spec()
    scope = (
        Curriculum.speciality_id.is_(None)
        if speciality_id is None
        else or_(Curriculum.speciality_id.is_(None), Curriculum.speciality_id == speciality_id)
    )
    curricula = list(
        await session.scalars(
            select(Curriculum).where(
                official_filter(Curriculum, as_of), Curriculum.programme_id == programme_id, scope
            )
        )
    )
    if not curricula:
        return []
    curriculum = max(curricula, key=lambda c: c.speciality_id is not None)
    source = await source_ref(session, spec, curriculum)
    rows = await session.execute(
        select(Prerequisite, Subject.name_fr)
        .outerjoin(Subject, Subject.id == Prerequisite.required_subject_id)
        .where(
            Prerequisite.curriculum_id == curriculum.id,
            Prerequisite.curriculum_subject_id.is_(None),
        )
        .order_by(Prerequisite.created_at)
    )
    out = []
    for p, name in rows:
        base = prerequisite_out(p, name)
        label = p.required_knowledge_fr or name or "Prérequis"
        out.append(PrerequisiteOfficial(**base.model_dump(), label=label, source=source))
    return out


async def official_conditions(
    session: AsyncSession,
    programme_id: uuid.UUID,
    academic_year: str | None,
    as_of: date,
    *,
    speciality_id: uuid.UUID | None = None,
    entry_level: int | None = None,
    applicant_category: str | None = None,
) -> AdmissionConditionsResponse:
    """Conditions officielles d'une rentrée (année obligatoire, D-J)."""
    await ensure_official_programme(session, programme_id, as_of, speciality_id)
    available = await official_academic_years(
        session,
        AdmissionCondition,
        as_of,
        AdmissionCondition.programme_id == programme_id,
        _spec_scope(speciality_id),
    )
    if not academic_year:
        raise academic_year_required(available)
    rows = await _official_condition_rows(
        session, programme_id, academic_year, as_of, speciality_id, entry_level, applicant_category
    )
    reqs = await load_requirements(session, [r.id for r in rows])
    conditions = [
        AdmissionConditionOfficial(
            **_fields(r, reqs[r.id]),
            label=r.summary_fr,
            scope="speciality" if r.speciality_id else "programme",
            source=await source_ref(session, ADMISSION_SPEC, r),
        )
        for r in rows
    ]
    return AdmissionConditionsResponse(
        programme_id=programme_id,
        speciality_id=speciality_id,
        academic_year=academic_year,
        as_of=as_of,
        conditions=conditions,
        prerequisites=await _official_prerequisites(session, programme_id, as_of, speciality_id),
        available_academic_years=available,
    )


# --- Éligibilité : calcul déterministe -----------------------------------------------------------

_BASIS_FIELD = {
    "bac_average": ("bac_average", "moyenne du bac"),
    "last_year_average": ("last_year_average", "moyenne de la dernière année"),
    "cycle_average": ("cycle_average", "moyenne du cycle"),
}
_DIPLOMA_FR = {
    "baccalaureate": "baccalauréat",
    "preparatory_cycle": "cycle préparatoire",
    "licence": "licence",
    "other_higher_education": "autre diplôme du supérieur",
}
#: Ordre des diplômes (un diplôme supérieur satisfait une exigence inférieure).
_DIPLOMA_RANK = {
    "baccalaureate": 1,
    "preparatory_cycle": 2,
    "other_higher_education": 2,
    "licence": 3,
}


def _criterion(
    condition_id: uuid.UUID,
    criterion: str,
    label: str,
    status: str,
    expected: Any,
    actual: Any,
    explanation: str,
) -> CriterionResult:
    return CriterionResult(
        condition_id=condition_id,
        criterion=criterion,
        label=label,
        status=status,  # type: ignore[arg-type]
        met={"met": True, "not_met": False}.get(status),
        expected=expected,
        actual=actual,
        explanation=explanation,
    )


def _compare(value: Decimal | None, minimum: Decimal) -> str:
    if value is None:
        return "unknown"
    return "met" if Decimal(value) >= Decimal(minimum) else "not_met"


def evaluate_condition(
    row: AdmissionCondition,
    reqs: list[AdmissionSubjectRequirement],
    profile: BacProfile,
) -> tuple[str, list[CriterionResult], list[str], set[str]]:
    """Évalue un profil contre une condition publiée. Fonction pure, sans base ni LLM.

    Renvoie (statut, critères, étapes suivantes, champs manquants). Statut : `not_met` si un
    critère est KO ; sinon `unknown` si un critère manque d'information ; sinon `met`.
    """
    cid = row.id
    criteria: list[CriterionResult] = []
    missing: set[str] = set()

    # 1. Diplôme exigé
    diploma = profile.highest_diploma or ("baccalaureate" if profile.bac_section else None)
    expected_dip = _DIPLOMA_FR.get(row.required_diploma, row.required_diploma)
    if diploma is None:
        status, actual = "unknown", None
        missing.add("highest_diploma")
        text = f"Diplôme exigé : {expected_dip}. Diplôme du candidat non renseigné."
    else:
        ok = _DIPLOMA_RANK.get(diploma, 0) >= _DIPLOMA_RANK.get(row.required_diploma, 99)
        status, actual = ("met" if ok else "not_met"), diploma
        verb = "satisfait" if ok else "ne satisfait pas"
        text = (
            f"Diplôme exigé : {expected_dip} ; diplôme déclaré : "
            f"{_DIPLOMA_FR.get(diploma, diploma)} ({verb} l'exigence)."
        )
    criteria.append(
        _criterion(
            cid, "required_diploma", "Diplôme exigé", status, row.required_diploma, actual, text
        )
    )

    # 2. Série du bac
    if row.accepted_bac_sections:
        sections = list(row.accepted_bac_sections)
        if profile.bac_section is None:
            status = "unknown"
            missing.add("bac_section")
            text = f"Séries acceptées : {', '.join(sections)}. Série du candidat non renseignée."
        else:
            status = "met" if profile.bac_section in sections else "not_met"
            text = (
                f"Série du candidat : {profile.bac_section} ; séries acceptées : "
                f"{', '.join(sections)}."
            )
        criteria.append(
            _criterion(
                cid,
                "bac_section",
                "Série du bac acceptée",
                status,
                sections,
                profile.bac_section,
                text,
            )
        )

    # 3. Moyenne minimale
    if row.min_average is not None:
        field, label_fr = _BASIS_FIELD.get(
            row.average_basis or "bac_average", _BASIS_FIELD["bac_average"]
        )
        value = getattr(profile, field)
        status = _compare(value, row.min_average)
        if status == "unknown":
            missing.add(field)
            text = f"Minimum exigé : {grade_str(row.min_average)}/20 ({label_fr}), non renseignée."
        else:
            text = (
                f"{label_fr.capitalize()} : {grade_str(value)}/20 ; minimum exigé : "
                f"{grade_str(row.min_average)}/20."
            )
        criteria.append(
            _criterion(
                cid,
                "min_average",
                f"Moyenne minimale ({label_fr})",
                status,
                grade_str(row.min_average),
                grade_str(value),
                text,
            )
        )

    # 4. Années d'études supérieures validées
    if row.min_validated_years > 0:
        years = profile.validated_years
        if years is None:
            status = "unknown"
            missing.add("validated_years")
        else:
            status = "met" if years >= row.min_validated_years else "not_met"
        criteria.append(
            _criterion(
                cid,
                "min_validated_years",
                "Années d'études supérieures validées",
                status,
                row.min_validated_years,
                years,
                f"Exigé : {row.min_validated_years} année(s) validée(s) ; déclaré : "
                f"{years if years is not None else 'non renseigné'}.",
            )
        )

    # 5. Notes minimales par matière (clés FR, C1)
    for req in reqs:
        grade = profile.subject_grades.get(req.subject_key)
        status = _compare(grade, req.min_grade)
        if status == "unknown":
            missing.add(f"subject_grades.{req.subject_key}")
        criteria.append(
            _criterion(
                cid,
                f"subject_grade:{req.subject_key}",
                f"Note minimale en {req.subject_name_fr}",
                status,
                grade_str(req.min_grade),
                grade_str(grade),
                f"{req.subject_name_fr} : "
                f"{grade_str(grade) + '/20' if grade is not None else 'note non renseignée'} ; "
                f"minimum exigé : {grade_str(req.min_grade)}/20.",
            )
        )

    statuses = {c.status for c in criteria}
    overall = "not_met" if "not_met" in statuses else "unknown" if "unknown" in statuses else "met"
    next_steps = []
    if row.requires_application_file:
        next_steps.append("Étude du dossier par le responsable.")
    if row.requires_test:
        next_steps.append("Test (QCM) de positionnement.")
    if row.requires_interview:
        next_steps.append("Entretien.")
    return overall, criteria, next_steps, missing


async def check_eligibility(
    session: AsyncSession,
    programme_id: uuid.UUID,
    academic_year: str | None,
    as_of: date,
    profile: BacProfile,
    *,
    speciality_id: uuid.UUID | None = None,
) -> EligibilityResult:
    """Compare le profil aux conditions **publiées et valides** (année obligatoire, D-J)."""
    await ensure_official_programme(session, programme_id, as_of, speciality_id)
    if not academic_year:
        available = await official_academic_years(
            session,
            AdmissionCondition,
            as_of,
            AdmissionCondition.programme_id == programme_id,
            _spec_scope(speciality_id),
        )
        raise academic_year_required(available)
    rows = await _official_condition_rows(
        session,
        programme_id,
        academic_year,
        as_of,
        speciality_id,
        profile.entry_level,
        profile.applicant_category,
    )
    reqs = await load_requirements(session, [r.id for r in rows])
    verdicts: list[ConditionVerdict] = []
    missing: set[str] = set()
    for row in rows:
        status, criteria, steps, miss = evaluate_condition(row, reqs[row.id], profile)
        missing |= miss
        verdicts.append(
            ConditionVerdict(
                condition_id=row.id,
                label=row.summary_fr,
                scope="speciality" if row.speciality_id else "programme",
                status=status,  # type: ignore[arg-type]
                criteria=criteria,
                next_steps=steps,
                source=await source_ref(session, ADMISSION_SPEC, row),
            )
        )
    if not verdicts:
        overall = "no_official_condition"
    else:
        statuses = {v.status for v in verdicts}
        overall = "met" if "met" in statuses else "unknown" if "unknown" in statuses else "not_met"
    return EligibilityResult(
        status=overall,  # type: ignore[arg-type]
        programme_id=programme_id,
        speciality_id=speciality_id,
        academic_year=academic_year,
        as_of=as_of,
        verdicts=verdicts,
        criteria=[c for v in verdicts for c in v.criteria],
        missing_information=sorted(missing),
    )
