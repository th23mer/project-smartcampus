"""Frais de scolarité et modalités de paiement (SA-21) : écriture staff et lecture officielle.

- Une grille officielle par (formation, spécialité, année d'études, catégorie, **année
  universitaire**) et par période (contrainte `ex_fee_schedule_one_published`, D-A).
- Enfants (`payment_plan`, `payment_installment`) modifiables seulement quand la grille est
  `draft` (SA-12 catégorie C) ; la base ne les protège pas, le service si.
- Lecture officielle : `academic_year` **obligatoire** (D-J) ; précédence « la plus spécifique
  l'emporte » (SA-12 D7) ; total = colonne générée `annual_total`.
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
from app.models import FeeSchedule, PaymentInstallment, PaymentPlan
from app.schemas.catalogue_common import Money
from app.schemas.fees import (
    FeeScheduleCreate,
    FeeScheduleOfficial,
    FeeScheduleStaffOut,
    FeeScheduleUpdate,
    FeesResponse,
    PaymentPlanCreate,
    PaymentPlanOut,
    PaymentPlanUpdate,
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


def _fee_key(row: FeeSchedule) -> list:
    """Clé métier de `ex_fee_schedule_one_published` (D-A)."""
    return same_key(
        (FeeSchedule.programme_id, row.programme_id),
        (FeeSchedule.speciality_id, row.speciality_id),
        (FeeSchedule.study_year, row.study_year),
        (FeeSchedule.student_category, row.student_category),
        (FeeSchedule.academic_year, row.academic_year),
    )


async def load_plans(
    session: AsyncSession, fee_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, list[tuple[PaymentPlan, list[PaymentInstallment]]]]:
    """Plans de paiement (et échéances) de plusieurs grilles, plan par défaut en tête."""
    out: dict[uuid.UUID, list[tuple[PaymentPlan, list[PaymentInstallment]]]] = {
        fid: [] for fid in fee_ids
    }
    if not fee_ids:
        return out
    plans = list(
        await session.scalars(
            select(PaymentPlan)
            .where(PaymentPlan.fee_schedule_id.in_(fee_ids))
            .order_by(PaymentPlan.is_default.desc(), PaymentPlan.code)
            .execution_options(populate_existing=True)
        )
    )
    installments: dict[uuid.UUID, list[PaymentInstallment]] = {p.id: [] for p in plans}
    if plans:
        for inst in await session.scalars(
            select(PaymentInstallment)
            .where(PaymentInstallment.payment_plan_id.in_([p.id for p in plans]))
            .order_by(PaymentInstallment.installment_no)
            .execution_options(populate_existing=True)
        ):
            installments[inst.payment_plan_id].append(inst)
    for plan in plans:
        out[plan.fee_schedule_id].append((plan, installments[plan.id]))
    return out


async def _copy_plans(session: AsyncSession, src: FeeSchedule, dst: FeeSchedule) -> None:
    """`/new-version` : copie les plans et échéances de la grille source."""
    for plan, items in (await load_plans(session, [src.id]))[src.id]:
        new_plan = PaymentPlan(
            fee_schedule_id=dst.id,
            code=plan.code,
            label_fr=plan.label_fr,
            installment_count=plan.installment_count,
            discount_rate=plan.discount_rate,
            is_default=plan.is_default,
        )
        session.add(new_plan)
        await session.flush()
        for inst in items:
            session.add(
                PaymentInstallment(
                    payment_plan_id=new_plan.id,
                    installment_no=inst.installment_no,
                    due_date=inst.due_date,
                    due_label_fr=inst.due_label_fr,
                    amount=inst.amount,
                )
            )


async def _submit_checks(session: AsyncSession, row: FeeSchedule) -> None:
    """Contrôles de cohérence avant soumission (code déterministe, SA-3 P8 n° 2).

    Pour chaque plan ayant des échéances : nombre d'échéances = `installment_count` et somme
    des échéances = total annuel diminué de la remise (au millime près).
    """
    await session.refresh(row, ["annual_total"])
    total = Decimal(row.annual_total)
    problems: list[dict[str, Any]] = []
    for plan, items in (await load_plans(session, [row.id]))[row.id]:
        if not items:
            continue
        if len(items) != plan.installment_count:
            problems.append(
                {
                    "field": f"payment_plans.{plan.code}.installments",
                    "issue": "count_mismatch",
                    "expected": plan.installment_count,
                    "actual": len(items),
                }
            )
        expected = (total * (Decimal(100) - Decimal(plan.discount_rate)) / 100).quantize(
            Decimal("0.001")
        )
        actual = sum((Decimal(i.amount) for i in items), Decimal(0))
        if actual != expected:
            problems.append(
                {
                    "field": f"payment_plans.{plan.code}.installments",
                    "issue": "sum_mismatch",
                    "expected": f"{expected:.3f}",
                    "actual": f"{actual:.3f}",
                }
            )
    if problems:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            message="Plans de paiement incohérents avec la grille : soumission impossible.",
            details=problems,
        )


FEE_SPEC = PublishableSpec(
    entity_type="fee_schedule",
    model=FeeSchedule,
    institution_expr=lambda: programme_institution_expr(FeeSchedule.programme_id),
    business_key=_fee_key,
    label_fr="grille de frais",
    copy_children=_copy_plans,
    submit_checks=_submit_checks,
)


# --- Sérialisation -------------------------------------------------------------------------------


def _amounts(row: FeeSchedule) -> dict[str, Any]:
    cur = row.currency
    return {
        "registration_fee": Money.of(row.registration_fee, cur),
        "tuition_fee": Money.of(row.annual_tuition_fee, cur),
        "other_fees": Money.of(row.other_fees, cur),
        "other_fees_label_fr": row.other_fees_label_fr,
        "annual_total": Money.of(row.annual_total, cur),
    }


def _plans_out(row: FeeSchedule, plans: list) -> list[PaymentPlanOut]:
    return [PaymentPlanOut.from_row(p, items, row.currency) for p, items in plans]


async def staff_out(
    session: AsyncSession, row: FeeSchedule, plans: list | None = None
) -> FeeScheduleStaffOut:
    """Ligne staff complète (plans de paiement chargés si non fournis)."""
    if plans is None:
        plans = (await load_plans(session, [row.id]))[row.id]
    return FeeScheduleStaffOut(
        id=row.id,
        programme_id=row.programme_id,
        speciality_id=row.speciality_id,
        study_year=row.study_year,
        student_category=row.student_category,
        academic_year=row.academic_year,
        currency=row.currency,
        notes_fr=row.notes_fr,
        payment_plans=_plans_out(row, plans),
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
        **_amounts(row),
    )


# --- Écriture staff ------------------------------------------------------------------------------


def _money_columns(data: dict[str, Any]) -> dict[str, Any]:
    """`{"tuition_fee": {"amount", "currency"}}` → colonnes `annual_tuition_fee`, `currency`."""
    out: dict[str, Any] = {}
    mapping = {
        "registration_fee": "registration_fee",
        "tuition_fee": "annual_tuition_fee",
        "other_fees": "other_fees",
    }
    for api_name, column in mapping.items():
        if api_name in data:
            money = data.pop(api_name)
            if money is None:
                if api_name == "other_fees":
                    out[column] = Decimal(0)
                continue
            out[column] = money["amount"]
            out["currency"] = money["currency"]
    out.update(data)
    return out


async def list_fee_schedules(
    session: AsyncSession,
    user: CurrentUser,
    page: PageParams,
    *,
    programme_id: uuid.UUID | None = None,
    academic_year: str | None = None,
    publication_status: list[str] | None = None,
) -> tuple[list[FeeScheduleStaffOut], int]:
    """Liste staff (tous statuts) filtrée par périmètre."""
    conditions = []
    scope = scope_filter(FEE_SPEC, await staff_scope(session, user))
    if scope is not None:
        conditions.append(scope)
    if programme_id:
        conditions.append(FeeSchedule.programme_id == programme_id)
    if academic_year:
        conditions.append(FeeSchedule.academic_year == academic_year)
    if publication_status:
        conditions.append(FeeSchedule.publication_status.in_(publication_status))
    total = await session.scalar(select(func.count()).select_from(FeeSchedule).where(*conditions))
    rows = list(
        await session.scalars(
            select(FeeSchedule)
            .where(*conditions)
            .order_by(FeeSchedule.academic_year.desc(), FeeSchedule.updated_at.desc())
            .offset(page.offset)
            .limit(page.limit)
        )
    )
    plans = await load_plans(session, [r.id for r in rows])
    items = [await staff_out(session, row, plans[row.id]) for row in rows]
    return items, int(total or 0)


async def get_fee_schedule(
    session: AsyncSession, row_id: uuid.UUID, user: CurrentUser
) -> FeeSchedule:
    return await get_for_staff(session, FEE_SPEC, row_id, user)


async def create_fee_schedule(
    session: AsyncSession, user: CurrentUser, data: FeeScheduleCreate
) -> FeeSchedule:
    """Crée une grille brouillon (responsable de l'institution de la formation)."""
    async with staff_transaction(session, user):
        institution = await programme_institution_id(session, data.programme_id)
        if institution is None:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                details=[{"field": "programme_id", "issue": "not_found", "location": "body"}],
            )
        await authorize(session, user, Action.CREATE, institution, existing=False)
        values = _money_columns(data.model_dump(exclude_none=False))
        row = FeeSchedule(**values, publication_status="draft", created_by=user.id)
        session.add(row)
        await flush_or_translate(session)
    await session.refresh(row)
    return row


async def update_fee_schedule(
    session: AsyncSession,
    row_id: uuid.UUID,
    user: CurrentUser,
    data: FeeScheduleUpdate,
    if_match: str | None,
) -> FeeSchedule:
    """PATCH d'un brouillon (If-Match obligatoire, SA-5 §1.6)."""
    async with staff_transaction(session, user):
        row = await load_for_update(session, FEE_SPEC, row_id)
        await authorize(session, user, Action.EDIT, await institution_of(session, FEE_SPEC, row))
        check_if_match(row, if_match, required=True)
        ensure_draft(row)
        changes = _money_columns(data.model_dump(exclude_unset=True))
        for key, value in changes.items():
            setattr(row, key, value)
        await flush_or_translate(session)
    await session.refresh(row)
    return row


async def delete_fee_schedule(
    session: AsyncSession, row_id: uuid.UUID, user: CurrentUser, if_match: str | None
) -> None:
    """Suppression d'un brouillon (SA-12 §0 : seuls les brouillons sont supprimables)."""
    async with staff_transaction(session, user):
        row = await load_for_update(session, FEE_SPEC, row_id)
        await authorize(session, user, Action.DELETE, await institution_of(session, FEE_SPEC, row))
        check_if_match(row, if_match, required=False)
        ensure_deletable(row)
        await session.execute(delete(FeeSchedule).where(FeeSchedule.id == row.id))
    session.expunge(row)


# --- Plans de paiement (enfants d'une grille brouillon) -----------------------------------------


async def _draft_parent(
    session: AsyncSession,
    fee_schedule_id: uuid.UUID,
    user: CurrentUser,
    *,
    create: bool = False,
    if_match: str | None = None,
    if_match_required: bool = False,
    deleting: bool = False,
) -> FeeSchedule:
    """Grille parente verrouillée, dans le périmètre, à l'état `draft`.

    L'ETag contrôlé est celui de la **grille** (comme SA-20 D7 pour les matières d'un cursus) :
    obligatoire pour modifier un plan (PATCH), vérifié s'il est fourni sinon.
    """
    try:
        parent = await load_for_update(session, FEE_SPEC, fee_schedule_id)
    except AppError as exc:
        if create:  # parent inexistant à la création : erreur de saisie, pas 404
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                details=[{"field": "fee_schedule_id", "issue": "not_found", "location": "body"}],
            ) from exc
        raise
    await authorize(session, user, Action.EDIT, await institution_of(session, FEE_SPEC, parent))
    check_if_match(parent, if_match, required=if_match_required)
    if deleting:  # réponse commune des DELETE du catalogue (deletion.py)
        ensure_deletable(parent, child=True)
    else:
        ensure_draft(parent)
    return parent


async def _parent_etag(session: AsyncSession, parent: FeeSchedule) -> str:
    """Nouvel ETag de la grille après modification d'un enfant (renvoyé dans `ETag`)."""
    await session.refresh(parent)
    return compute_etag(parent)


def _installments(plan_id: uuid.UUID, items: Sequence[Any]) -> list[PaymentInstallment]:
    return [
        PaymentInstallment(
            payment_plan_id=plan_id,
            installment_no=i.installment_no,
            due_date=i.due_date,
            due_label_fr=i.due_label_fr,
            amount=i.amount,
        )
        for i in items
    ]


async def plan_out(session: AsyncSession, plan: PaymentPlan) -> PaymentPlanOut:
    parent = await session.get(FeeSchedule, plan.fee_schedule_id)
    items = list(
        await session.scalars(
            select(PaymentInstallment)
            .where(PaymentInstallment.payment_plan_id == plan.id)
            .execution_options(populate_existing=True)
        )
    )
    return PaymentPlanOut.from_row(plan, items, parent.currency if parent else "TND")


async def get_payment_plan(
    session: AsyncSession, plan_id: uuid.UUID, user: CurrentUser
) -> PaymentPlan:
    plan = await session.get(PaymentPlan, plan_id, populate_existing=True)
    if plan is None:
        raise AppError(ErrorCode.NOT_FOUND)
    await get_for_staff(session, FEE_SPEC, plan.fee_schedule_id, user)  # périmètre
    return plan


async def list_payment_plans(
    session: AsyncSession, fee_schedule_id: uuid.UUID, user: CurrentUser
) -> list[PaymentPlanOut]:
    parent = await get_for_staff(session, FEE_SPEC, fee_schedule_id, user)
    return _plans_out(parent, (await load_plans(session, [parent.id]))[parent.id])


async def create_payment_plan(
    session: AsyncSession, user: CurrentUser, data: PaymentPlanCreate, if_match: str | None = None
) -> tuple[PaymentPlan, str]:
    """Ajoute un plan à une grille brouillon ; renvoie le plan et le nouvel ETag de la grille."""
    async with staff_transaction(session, user):
        parent = await _draft_parent(
            session, data.fee_schedule_id, user, create=True, if_match=if_match
        )
        parent.updated_at = func.now()  # l'ETag de la grille change avec ses plans
        plan = PaymentPlan(**data.model_dump(exclude={"installments"}))
        session.add(plan)
        await flush_or_translate(session)
        session.add_all(_installments(plan.id, data.installments))
        await flush_or_translate(session)
    return plan, await _parent_etag(session, parent)


async def update_payment_plan(
    session: AsyncSession,
    plan_id: uuid.UUID,
    user: CurrentUser,
    data: PaymentPlanUpdate,
    if_match: str | None,
) -> tuple[PaymentPlan, str]:
    """PATCH d'un plan : If-Match de la **grille** obligatoire (428 / 412, SA-5 §1.6)."""
    async with staff_transaction(session, user):
        plan = await session.get(PaymentPlan, plan_id, with_for_update=True, populate_existing=True)
        if plan is None:
            raise AppError(ErrorCode.NOT_FOUND)
        parent = await _draft_parent(
            session, plan.fee_schedule_id, user, if_match=if_match, if_match_required=True
        )
        parent.updated_at = func.now()
        changes = data.model_dump(exclude_unset=True, exclude={"installments"})
        for key, value in changes.items():
            if value is None:
                raise AppError(
                    ErrorCode.VALIDATION_ERROR, details=[{"field": key, "issue": "not_nullable"}]
                )
            setattr(plan, key, value)
        if data.installments is not None:
            await session.execute(
                delete(PaymentInstallment).where(PaymentInstallment.payment_plan_id == plan.id)
            )
            session.add_all(_installments(plan.id, data.installments))
        await flush_or_translate(session)
    return plan, await _parent_etag(session, parent)


async def delete_payment_plan(
    session: AsyncSession, plan_id: uuid.UUID, user: CurrentUser, if_match: str | None = None
) -> str:
    async with staff_transaction(session, user):
        plan = await session.get(PaymentPlan, plan_id, with_for_update=True)
        if plan is None:
            raise AppError(ErrorCode.NOT_FOUND)
        parent = await _draft_parent(
            session, plan.fee_schedule_id, user, if_match=if_match, deleting=True
        )
        parent.updated_at = func.now()
        await session.execute(delete(PaymentPlan).where(PaymentPlan.id == plan.id))
    session.expunge(plan)
    return await _parent_etag(session, parent)


# --- Lecture officielle (public, outil get_fees) ------------------------------------------------


async def official_fees(
    session: AsyncSession,
    programme_id: uuid.UUID,
    academic_year: str | None,
    as_of: date,
    *,
    speciality_id: uuid.UUID | None = None,
    study_year: int | None = None,
    student_category: str | None = None,
) -> FeesResponse:
    """Grilles officielles (publiées et valides à `as_of`) d'une formation pour une année.

    - année absente → 422 ACADEMIC_YEAR_REQUIRED + `available_academic_years` (D-J) ;
    - formation / spécialité non officielle → 404 ;
    - précédence : par (année d'études, catégorie), la grille de la spécialité l'emporte sur
      celle de la formation ; si `study_year` est donné, la grille de cette année l'emporte
      sur la grille « toutes années » (SA-12 D7).
    """
    await ensure_official_programme(session, programme_id, as_of, speciality_id)
    spec_scope = (
        FeeSchedule.speciality_id.is_(None)
        if speciality_id is None
        else or_(FeeSchedule.speciality_id.is_(None), FeeSchedule.speciality_id == speciality_id)
    )
    available = await official_academic_years(
        session, FeeSchedule, as_of, FeeSchedule.programme_id == programme_id, spec_scope
    )
    if not academic_year:
        raise academic_year_required(available)

    conditions = [
        official_filter(FeeSchedule, as_of),
        FeeSchedule.programme_id == programme_id,
        FeeSchedule.academic_year == academic_year,
        spec_scope,
    ]
    if study_year is not None:
        conditions.append(
            or_(FeeSchedule.study_year.is_(None), FeeSchedule.study_year == study_year)
        )
    if student_category is not None:
        conditions.append(FeeSchedule.student_category == student_category)
    candidates = list(await session.scalars(select(FeeSchedule).where(*conditions)))

    if study_year is not None:
        chosen = most_specific(
            candidates,
            bucket=lambda r: r.student_category,
            specificity=lambda r: (r.speciality_id is not None, r.study_year is not None),
        )
    else:
        chosen = most_specific(
            candidates,
            bucket=lambda r: (r.study_year or 0, r.student_category),
            specificity=lambda r: (r.speciality_id is not None,),
        )
    chosen.sort(key=lambda r: (r.student_category, r.study_year or 0))
    plans = await load_plans(session, [r.id for r in chosen])
    schedules = [
        FeeScheduleOfficial(
            id=r.id,
            programme_id=r.programme_id,
            speciality_id=r.speciality_id,
            study_year=r.study_year,
            student_category=r.student_category,
            academic_year=r.academic_year,
            scope="speciality" if r.speciality_id else "programme",
            notes_fr=r.notes_fr,
            payment_plans=_plans_out(r, plans[r.id]),
            source=await source_ref(session, FEE_SPEC, r),
            **_amounts(r),
        )
        for r in chosen
    ]
    return FeesResponse(
        programme_id=programme_id,
        speciality_id=speciality_id,
        academic_year=academic_year,
        as_of=as_of,
        fee_schedules=schedules,
        available_academic_years=available,
    )
