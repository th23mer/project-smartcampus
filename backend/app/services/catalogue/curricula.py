"""Service des cursus et de leurs matières (SA-20).

- Lecture publique : cursus **publié et valide à la date D** d'une formation (et de ses
  spécialités officielles), regroupé par semestre ; totaux de crédits calculés par le code ;
  heures totales = colonne générée (jamais calculées par un LLM).
- Staff : brouillon de cursus, matières du cursus (modifiables seulement si le cursus est
  `draft`, SA-12 catégorie C), contrôles avant soumission, nouvelle version copiée depuis une
  version publiée (matières et prérequis compris). Transitions : `publication.py` (SA-21).
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.errors import AppError, ErrorCode
from app.core.security import CurrentUser
from app.models import Curriculum, CurriculumSubject, Prerequisite, Programme, Speciality, Subject
from app.services.catalogue import publication as pub
from app.services.catalogue.deletion import ensure_deletable
from app.services.catalogue.programmes import (
    apply_patch,
    check_speciality_of,
    finish,
    get_official_programme,
    load_for_edit,
    official,
    programme_for_create,
    source_of,
    today_tunis,
)
from app.services.catalogue.publication import (
    PublishableSpec,
    ensure_draft,
    programme_institution_expr,
    same_key,
)
from app.services.catalogue.tx import flush_or_translate, staff_transaction

# ============ Workflow de publication ============


async def _copy_children(session: AsyncSession, src: Curriculum, copy: Curriculum) -> None:
    """Nouvelle version : copie les matières puis les prérequis (cibles remappées)."""
    lines = (
        await session.scalars(
            select(CurriculumSubject).where(CurriculumSubject.curriculum_id == src.id)
        )
    ).all()
    mapping: dict[uuid.UUID, uuid.UUID] = {}
    for line in lines:
        new_line = CurriculumSubject(
            id=uuid.uuid4(),
            curriculum_id=copy.id,
            subject_id=line.subject_id,
            semester=line.semester,
            teaching_unit_code=line.teaching_unit_code,
            teaching_unit_name_fr=line.teaching_unit_name_fr,
            coefficient=line.coefficient,
            ects_credits=line.ects_credits,
            hours_lecture=line.hours_lecture,
            hours_tutorial=line.hours_tutorial,
            hours_practical=line.hours_practical,
            is_elective=line.is_elective,
        )
        mapping[line.id] = new_line.id
        session.add(new_line)
    await flush_or_translate(session)
    prereqs = (
        await session.scalars(select(Prerequisite).where(Prerequisite.curriculum_id == src.id))
    ).all()
    for pr in prereqs:
        session.add(
            Prerequisite(
                curriculum_id=copy.id,
                curriculum_subject_id=mapping.get(pr.curriculum_subject_id)
                if pr.curriculum_subject_id
                else None,
                required_subject_id=pr.required_subject_id,
                required_knowledge_fr=pr.required_knowledge_fr,
                is_mandatory=pr.is_mandatory,
            )
        )


async def _submit_checks(session: AsyncSession, row: Curriculum) -> None:
    """Avant relecture : au moins une matière ; total ECTS cohérent s'il est déclaré."""
    count, credits = (
        await session.execute(
            select(
                func.count(CurriculumSubject.id),
                func.coalesce(func.sum(CurriculumSubject.ects_credits), 0),
            ).where(CurriculumSubject.curriculum_id == row.id)
        )
    ).one()
    problems: list[dict[str, Any]] = []
    if count == 0:
        problems.append({"field": "subjects", "issue": "required"})
    elif row.total_ects is not None and Decimal(credits) != Decimal(row.total_ects):
        problems.append(
            {
                "field": "total_ects",
                "issue": "credits_mismatch",
                "declared": row.total_ects,
                "computed": str(credits),
            }
        )
    if problems:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            message="Impossible de soumettre le cursus : matières absentes ou crédits incohérents.",
            details=problems,
        )


CURRICULUM_SPEC = PublishableSpec(
    entity_type="curriculum",
    model=Curriculum,
    institution_expr=lambda: programme_institution_expr(Curriculum.programme_id),
    business_key=lambda r: same_key(
        (Curriculum.programme_id, r.programme_id),
        (Curriculum.speciality_id, r.speciality_id),
    ),
    label_fr="cursus",
    copy_children=_copy_children,
    submit_checks=_submit_checks,
)


# ============ Lecture publique ============


def _year_of_study(semester: int) -> int:
    return (semester + 1) // 2


async def get_programme_curricula(
    session: AsyncSession,
    programme_id: uuid.UUID,
    *,
    speciality_id: uuid.UUID | None = None,
    on_date: date | None = None,
) -> list[dict[str, Any]]:
    """Cursus officiels d'une formation à la date D (tronc commun + spécialités officielles).

    Avec `speciality_id` : le cursus de cette spécialité et le cursus commun de la formation.
    Formation non officielle → 404 (un brouillon reste invisible).
    """
    d = on_date or today_tunis()
    await get_official_programme(session, programme_id, d)
    spec = aliased(Speciality)
    where = [
        Curriculum.programme_id == programme_id,
        official(Curriculum, d),
        or_(Curriculum.speciality_id.is_(None), official(spec, d)),
    ]
    if speciality_id is not None:
        where.append(
            or_(Curriculum.speciality_id.is_(None), Curriculum.speciality_id == speciality_id)
        )
    rows = (
        await session.execute(
            select(Curriculum, spec)
            .outerjoin(spec, spec.id == Curriculum.speciality_id)
            .where(*where)
            .order_by(Curriculum.speciality_id.is_not(None), spec.code)
        )
    ).all()
    result = []
    for cur, sp in rows:
        result.append(await _curriculum_public(session, cur, sp))
    return result


async def _curriculum_public(
    session: AsyncSession, cur: Curriculum, sp: Speciality | None
) -> dict[str, Any]:
    lines = (
        await session.execute(
            select(CurriculumSubject, Subject)
            .join(Subject, Subject.id == CurriculumSubject.subject_id)
            .where(CurriculumSubject.curriculum_id == cur.id)
            .order_by(
                CurriculumSubject.semester, CurriculumSubject.teaching_unit_code, Subject.code
            )
        )
    ).all()
    req = aliased(Subject)
    prereq_rows = (
        await session.execute(
            select(Prerequisite, req)
            .outerjoin(req, req.id == Prerequisite.required_subject_id)
            .where(Prerequisite.curriculum_id == cur.id)
        )
    ).all()
    prereqs: dict[uuid.UUID | None, list[dict[str, Any]]] = defaultdict(list)
    for pr, rs in prereq_rows:
        prereqs[pr.curriculum_subject_id].append(
            {
                "subject_code": rs.code if rs else None,
                "subject_name": rs.name_fr if rs else None,
                "knowledge": pr.required_knowledge_fr,
                "is_mandatory": pr.is_mandatory,
            }
        )
    semesters: dict[int, list[dict[str, Any]]] = defaultdict(list)
    credits_by_sem: dict[int, Decimal] = defaultdict(Decimal)
    for line, subj in lines:
        semesters[line.semester].append(
            {
                "id": subj.id,
                "code": subj.code,
                "name": subj.name_fr,
                "name_ar": subj.name_ar,
                "teaching_unit_code": line.teaching_unit_code,
                "teaching_unit_name": line.teaching_unit_name_fr,
                "coefficient": line.coefficient,
                "credits": line.ects_credits,
                "hours_lecture": line.hours_lecture,
                "hours_tutorial": line.hours_tutorial,
                "hours_practical": line.hours_practical,
                "hours": line.hours_total,
                "is_elective": line.is_elective,
                "prerequisites": prereqs.get(line.id, []),
            }
        )
        credits_by_sem[line.semester] += line.ects_credits
    version = await pub.version_number(session, CURRICULUM_SPEC, cur)
    return {
        "id": cur.id,
        "programme_id": cur.programme_id,
        "speciality": None if sp is None else {"id": sp.id, "code": sp.code, "name": sp.name_fr},
        "version_label": cur.version_label,
        "academic_year": cur.academic_year,
        "total_ects": cur.total_ects,
        "computed_total_credits": sum(credits_by_sem.values(), Decimal(0)),
        "notes": cur.notes_fr,
        "semesters": [
            {
                "semester": s,
                "year_of_study": _year_of_study(s),
                "total_credits": credits_by_sem[s],
                "subjects": semesters[s],
            }
            for s in sorted(semesters)
        ],
        "source": source_of(cur, "curriculum", version),
    }


# ============ Staff : cursus ============


async def staff_curriculum_lines(
    session: AsyncSession, curriculum_id: uuid.UUID
) -> list[CurriculumSubject]:
    return list(
        (
            await session.scalars(
                select(CurriculumSubject)
                .where(CurriculumSubject.curriculum_id == curriculum_id)
                .order_by(
                    CurriculumSubject.semester,
                    CurriculumSubject.teaching_unit_code,
                    CurriculumSubject.id,
                )
            )
        ).all()
    )


async def create_curriculum(session: AsyncSession, user: CurrentUser, data: Any) -> Curriculum:
    async with staff_transaction(session, user):
        await programme_for_create(session, user, data.programme_id, "programme_id")
        await check_speciality_of(session, data.speciality_id, data.programme_id, "speciality_id")
        row = Curriculum(**data.model_dump(), created_by=user.id)
        session.add(row)
    return await finish(session, row)


async def update_curriculum(
    session: AsyncSession, user: CurrentUser, row_id: uuid.UUID, data: Any, if_match: str | None
) -> Curriculum:
    async with staff_transaction(session, user):
        row = await load_for_edit(session, user, CURRICULUM_SPEC, row_id, if_match)
        ensure_draft(row)
        apply_patch(row, data, non_nullable=("version_label", "academic_year"))
    return await finish(session, row)


# ============ Staff : matières d'un cursus (enfants) ============


async def _subject_for_curriculum(
    session: AsyncSession, cur: Curriculum, subject_id: uuid.UUID
) -> None:
    """La matière doit exister et appartenir au même établissement que la formation."""
    subj_inst = await session.scalar(select(Subject.institution_id).where(Subject.id == subject_id))
    prog_inst = await session.scalar(
        select(Programme.institution_id).where(Programme.id == cur.programme_id)
    )
    if subj_inst is None:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            details=[{"field": "subject_id", "issue": "not_found", "location": "body"}],
        )
    if subj_inst != prog_inst:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            message="La matière appartient à un autre établissement que la formation.",
            details=[{"field": "subject_id", "issue": "other_institution", "location": "body"}],
        )


def _touch(cur: Curriculum) -> None:
    """Modifier une matière change l'ETag du cursus (trigger `set_updated_at`)."""
    cur.updated_at = func.now()


async def _line_of(session: AsyncSession, cur: Curriculum, line_id: uuid.UUID) -> CurriculumSubject:
    line = await session.scalar(
        select(CurriculumSubject)
        .where(CurriculumSubject.id == line_id, CurriculumSubject.curriculum_id == cur.id)
        .with_for_update()
    )
    if line is None:
        raise AppError(ErrorCode.NOT_FOUND)
    return line


async def add_line(
    session: AsyncSession,
    user: CurrentUser,
    curriculum_id: uuid.UUID,
    data: Any,
    if_match: str | None,
) -> tuple[CurriculumSubject, Curriculum]:
    async with staff_transaction(session, user):
        cur = await load_for_edit(session, user, CURRICULUM_SPEC, curriculum_id, if_match)
        ensure_draft(cur)
        await _subject_for_curriculum(session, cur, data.subject_id)
        line = CurriculumSubject(**data.model_dump(), curriculum_id=cur.id)
        session.add(line)
        _touch(cur)
    await session.refresh(cur)
    return await finish(session, line), cur


async def update_line(
    session: AsyncSession,
    user: CurrentUser,
    curriculum_id: uuid.UUID,
    line_id: uuid.UUID,
    data: Any,
    if_match: str | None,
) -> tuple[CurriculumSubject, Curriculum]:
    async with staff_transaction(session, user):
        cur = await load_for_edit(session, user, CURRICULUM_SPEC, curriculum_id, if_match)
        ensure_draft(cur)
        line = await _line_of(session, cur, line_id)
        apply_patch(
            line,
            data,
            non_nullable=(
                "semester",
                "coefficient",
                "ects_credits",
                "hours_lecture",
                "hours_tutorial",
                "hours_practical",
                "is_elective",
            ),
        )
        _touch(cur)
    await session.refresh(cur)
    return await finish(session, line), cur


async def delete_line(
    session: AsyncSession,
    user: CurrentUser,
    curriculum_id: uuid.UUID,
    line_id: uuid.UUID,
    if_match: str | None,
) -> Curriculum:
    async with staff_transaction(session, user):
        cur = await load_for_edit(session, user, CURRICULUM_SPEC, curriculum_id, if_match)
        ensure_deletable(cur, child=True)  # réponse commune des DELETE (deletion.py)
        line = await _line_of(session, cur, line_id)
        await session.delete(line)
        _touch(cur)
    await session.refresh(cur)
    return cur


__all__ = [
    "CURRICULUM_SPEC",
    "add_line",
    "create_curriculum",
    "delete_line",
    "get_programme_curricula",
    "staff_curriculum_lines",
    "update_curriculum",
    "update_line",
]
