"""Routes des frais de scolarité et modalités de paiement (SA-21).

- Public : `GET /catalogue/programmes/{programme_id}/fees` (publié et valide, année
  obligatoire, D-J) ;
- Staff : `/staff/catalogue/fee-schedules` et `/staff/catalogue/payment-plans` (brouillons,
  ETag / If-Match, transitions submit / publish / reject / archive / new-version, D-B / D-H).

Les dépendances communes (rôles, en-têtes) sont réutilisées par `catalogue_admission.py`.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Body, Depends, Header, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.pagination import Page, PageParamsDep
from app.core.security import CurrentUser, Role, require_roles
from app.schemas.catalogue_common import (
    NewVersionRequest,
    OptionalReasonRequest,
    PublishRequest,
    ReasonRequest,
)
from app.schemas.common import ErrorResponse
from app.schemas.fees import (
    FeeScheduleCreate,
    FeeScheduleStaffOut,
    FeeScheduleUpdate,
    FeesResponse,
    PaymentPlanCreate,
    PaymentPlanOut,
    PaymentPlanUpdate,
)
from app.services.catalogue import fees as svc
from app.services.catalogue import publication as pub
from app.services.catalogue.publication import Action, today_tunis

SessionDep = Annotated[AsyncSession, Depends(get_session)]

#: Matrice SA-5 §4 : lecture staff, rédaction (auteur), relecture (publication, D-H).
READERS = (Role.IIT_ACADEMIC_LEAD, Role.ISB_ACADEMIC_LEAD, Role.DIRECTION, Role.PLATFORM_ADMIN)
AUTHORS = (Role.IIT_ACADEMIC_LEAD, Role.ISB_ACADEMIC_LEAD)
REVIEWERS = (Role.IIT_ACADEMIC_LEAD, Role.ISB_ACADEMIC_LEAD, Role.DIRECTION)

ReaderDep = Annotated[CurrentUser, Depends(require_roles(*READERS))]
AuthorDep = Annotated[CurrentUser, Depends(require_roles(*AUTHORS))]
ReviewerDep = Annotated[CurrentUser, Depends(require_roles(*REVIEWERS))]

IfMatch = Annotated[
    str | None,
    Header(alias="If-Match", description="ETag reçu à la lecture (SA-5 §1.6)."),
]
ParentIfMatch = Annotated[
    str | None,
    Header(
        alias="If-Match",
        description=(
            "ETag du **parent** (grille ou cursus), reçu à sa lecture : obligatoire en PATCH "
            "(428 / 412), vérifié s'il est fourni en POST / DELETE (SA-5 §1.6, SA-20 D7)."
        ),
    ),
]
IdempotencyKey = Annotated[
    str | None,
    Header(
        alias="Idempotency-Key",
        description=(
            "UUID client (SA-5 §1.6). Accepté ; le rejeu sera assuré par le middleware "
            "d'idempotence commun (hors SA-21)."
        ),
    ),
]
AsOf = Annotated[
    date | None,
    Query(alias="date", description="Date « publié et valide à » (défaut : aujourd'hui, Tunis)."),
]
AcademicYearQuery = Annotated[
    str | None,
    Query(
        pattern=r"^\d{4}-\d{4}$",
        description=(
            "Année universitaire, ex. 2026-2027. **Obligatoire** (D-J) : sans elle, 422 "
            "ACADEMIC_YEAR_REQUIRED avec `details.available_academic_years`."
        ),
        examples=["2026-2027"],
    ),
]
StatusFilter = Annotated[
    list[Literal["draft", "pending_review", "published", "archived"]] | None,
    Query(description="Filtre de statut (répétable)."),
]


def _err(*codes: str) -> dict:
    return {"model": ErrorResponse, "description": " / ".join(codes)}


STAFF_ERRORS: dict[int | str, dict] = {
    401: _err("UNAUTHENTICATED"),
    403: _err("FORBIDDEN", "FOUR_EYES_REQUIRED"),
    404: _err("NOT_FOUND"),
    409: _err("INVALID_STATUS_TRANSITION", "VALIDITY_OVERLAP", "CONFLICT"),
    412: _err("PRECONDITION_FAILED"),
    428: _err("PRECONDITION_REQUIRED"),
}

public_router = APIRouter(prefix="/catalogue", tags=["Catalogue public (publié et valide)"])
staff_router = APIRouter(
    prefix="/staff/catalogue",
    tags=["Catalogue : écriture et publication (staff)"],
    responses=STAFF_ERRORS,
)


# --- Public ------------------------------------------------------------------------------------


@public_router.get(
    "/programmes/{programme_id}/fees",
    response_model=FeesResponse,
    summary="Frais et modalités de paiement d'une année universitaire",
    responses={404: _err("NOT_FOUND"), 422: _err("ACADEMIC_YEAR_REQUIRED", "VALIDATION_ERROR")},
)
async def get_programme_fees(
    programme_id: uuid.UUID,
    session: SessionDep,
    academic_year: AcademicYearQuery = None,
    speciality_id: Annotated[uuid.UUID | None, Query()] = None,
    study_year: Annotated[int | None, Query(ge=1, le=6)] = None,
    student_category: Annotated[Literal["tunisian", "foreign"] | None, Query()] = None,
    as_of: AsOf = None,
) -> FeesResponse:
    """Grilles **publiées et valides** à la date (défaut aujourd'hui) pour l'année demandée.

    Précédence : la grille de la spécialité l'emporte sur celle de la formation, la grille
    d'une année d'études précise sur la grille « toutes années » (SA-12 D7). Les totaux
    viennent de la colonne générée `annual_total`. Même service que l'outil `get_fees`.
    """
    return await svc.official_fees(
        session,
        programme_id,
        academic_year,
        as_of or today_tunis(),
        speciality_id=speciality_id,
        study_year=study_year,
        student_category=student_category,
    )


# --- Staff : grilles -----------------------------------------------------------------------------


async def _out(session: AsyncSession, row, response: Response) -> FeeScheduleStaffOut:
    out = await svc.staff_out(session, row)
    response.headers["ETag"] = out.etag
    return out


@staff_router.get("/fee-schedules", response_model=Page[FeeScheduleStaffOut])
async def list_fee_schedules(
    session: SessionDep,
    user: ReaderDep,
    page: PageParamsDep,
    programme_id: Annotated[uuid.UUID | None, Query()] = None,
    academic_year: AcademicYearQuery = None,
    publication_status: StatusFilter = None,
) -> Page[FeeScheduleStaffOut]:
    """Grilles de frais de tous statuts (périmètre du responsable ; direction et admin : tout)."""
    items, total = await svc.list_fee_schedules(
        session,
        user,
        page,
        programme_id=programme_id,
        academic_year=academic_year,
        publication_status=list(publication_status) if publication_status else None,
    )
    return Page[FeeScheduleStaffOut].build(items, total, page)


@staff_router.post(
    "/fee-schedules", status_code=status.HTTP_201_CREATED, response_model=FeeScheduleStaffOut
)
async def create_fee_schedule(
    data: FeeScheduleCreate,
    session: SessionDep,
    user: AuthorDep,
    response: Response,
    _key: IdempotencyKey = None,
) -> FeeScheduleStaffOut:
    """Crée une grille **brouillon** (responsable de l'institution de la formation)."""
    row = await svc.create_fee_schedule(session, user, data)
    return await _out(session, row, response)


@staff_router.get("/fee-schedules/{row_id}", response_model=FeeScheduleStaffOut)
async def get_fee_schedule(
    row_id: uuid.UUID, session: SessionDep, user: ReaderDep, response: Response
) -> FeeScheduleStaffOut:
    """Lit une grille (tous statuts) ; l'en-tête `ETag` sert ensuite à `If-Match`."""
    return await _out(session, await svc.get_fee_schedule(session, row_id, user), response)


@staff_router.patch("/fee-schedules/{row_id}", response_model=FeeScheduleStaffOut)
async def update_fee_schedule(
    row_id: uuid.UUID,
    data: FeeScheduleUpdate,
    session: SessionDep,
    user: AuthorDep,
    response: Response,
    if_match: IfMatch = None,
) -> FeeScheduleStaffOut:
    """Modifie un **brouillon** (If-Match obligatoire : 428 sinon, 412 si périmé)."""
    row = await svc.update_fee_schedule(session, row_id, user, data, if_match)
    return await _out(session, row, response)


@staff_router.delete("/fee-schedules/{row_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_fee_schedule(
    row_id: uuid.UUID, session: SessionDep, user: AuthorDep, if_match: IfMatch = None
) -> Response:
    """Supprime un **brouillon** (une ligne publiée s'archive, elle ne se supprime pas)."""
    await svc.delete_fee_schedule(session, row_id, user, if_match)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@staff_router.post("/fee-schedules/{row_id}/submit", response_model=FeeScheduleStaffOut)
async def submit_fee_schedule(
    row_id: uuid.UUID,
    session: SessionDep,
    user: AuthorDep,
    response: Response,
    if_match: IfMatch = None,
    _key: IdempotencyKey = None,
) -> FeeScheduleStaffOut:
    """`draft → pending_review` (contrôles : valid_from, période, plans de paiement)."""
    row = await pub.run_transition(
        session, svc.FEE_SPEC, row_id, user, Action.SUBMIT, if_match=if_match,
        if_match_required=True,
    )  # fmt: skip
    return await _out(session, row, response)


@staff_router.post("/fee-schedules/{row_id}/publish", response_model=FeeScheduleStaffOut)
async def publish_fee_schedule(
    row_id: uuid.UUID,
    session: SessionDep,
    user: ReviewerDep,
    response: Response,
    body: Annotated[PublishRequest | None, Body()] = None,
    if_match: IfMatch = None,
    _key: IdempotencyKey = None,
) -> FeeScheduleStaffOut:
    """`pending_review → published` par une **autre** personne (4 yeux) ; l'admin ne publie
    jamais. Chevauchement : 409 VALIDITY_OVERLAP, sauf `replace_current`."""
    row = await pub.run_transition(
        session,
        svc.FEE_SPEC,
        row_id,
        user,
        Action.PUBLISH,
        if_match=if_match,
        if_match_required=True,
        replace_current=bool(body and body.replace_current),
    )
    return await _out(session, row, response)


@staff_router.post("/fee-schedules/{row_id}/reject", response_model=FeeScheduleStaffOut)
async def reject_fee_schedule(
    row_id: uuid.UUID,
    body: ReasonRequest,
    session: SessionDep,
    user: ReviewerDep,
    response: Response,
    if_match: IfMatch = None,
    _key: IdempotencyKey = None,
) -> FeeScheduleStaffOut:
    """`pending_review → draft` avec motif, par un relecteur différent de l'auteur."""
    row = await pub.run_transition(
        session, svc.FEE_SPEC, row_id, user, Action.REJECT, if_match=if_match, reason=body.reason
    )
    return await _out(session, row, response)


@staff_router.post("/fee-schedules/{row_id}/archive", response_model=FeeScheduleStaffOut)
async def archive_fee_schedule(
    row_id: uuid.UUID,
    session: SessionDep,
    user: ReviewerDep,
    response: Response,
    body: Annotated[OptionalReasonRequest | None, Body()] = None,
    if_match: IfMatch = None,
    _key: IdempotencyKey = None,
) -> FeeScheduleStaffOut:
    """`published → archived` (retirée des lectures officielles, gardée pour l'historique)."""
    row = await pub.run_transition(
        session, svc.FEE_SPEC, row_id, user, Action.ARCHIVE, if_match=if_match,
        reason=body.reason if body else None,
    )  # fmt: skip
    return await _out(session, row, response)


@staff_router.post(
    "/fee-schedules/{row_id}/new-version",
    status_code=status.HTTP_201_CREATED,
    response_model=FeeScheduleStaffOut,
)
async def new_fee_schedule_version(
    row_id: uuid.UUID,
    session: SessionDep,
    user: AuthorDep,
    response: Response,
    body: Annotated[NewVersionRequest | None, Body()] = None,
    _key: IdempotencyKey = None,
) -> FeeScheduleStaffOut:
    """Copie une grille publiée (et ses plans) en **nouveau brouillon** ; surcharges
    facultatives `valid_from`, `valid_to`, `academic_year`."""
    row = await pub.run_transition(
        session, svc.FEE_SPEC, row_id, user, Action.NEW_VERSION,
        overrides=body.model_dump(exclude_none=True) if body else None,
    )  # fmt: skip
    return await _out(session, row, response)


# --- Staff : plans de paiement ---------------------------------------------------------------


@staff_router.get("/payment-plans", response_model=list[PaymentPlanOut])
async def list_payment_plans(
    fee_schedule_id: Annotated[uuid.UUID, Query()], session: SessionDep, user: ReaderDep
) -> list[PaymentPlanOut]:
    """Plans de paiement d'une grille (tous statuts)."""
    return await svc.list_payment_plans(session, fee_schedule_id, user)


@staff_router.post(
    "/payment-plans", status_code=status.HTTP_201_CREATED, response_model=PaymentPlanOut
)
async def create_payment_plan(
    data: PaymentPlanCreate,
    session: SessionDep,
    user: AuthorDep,
    response: Response,
    if_match: ParentIfMatch = None,
    _key: IdempotencyKey = None,
) -> PaymentPlanOut:
    """Ajoute un plan (avec ses échéances) à une grille **brouillon**. If-Match de la grille
    vérifié s'il est fourni ; l'en-tête `ETag` de la réponse est le nouvel ETag de la grille."""
    plan, etag = await svc.create_payment_plan(session, user, data, if_match)
    response.headers["ETag"] = etag
    return await svc.plan_out(session, plan)


@staff_router.get("/payment-plans/{plan_id}", response_model=PaymentPlanOut)
async def get_payment_plan(
    plan_id: uuid.UUID, session: SessionDep, user: ReaderDep
) -> PaymentPlanOut:
    return await svc.plan_out(session, await svc.get_payment_plan(session, plan_id, user))


@staff_router.patch("/payment-plans/{plan_id}", response_model=PaymentPlanOut)
async def update_payment_plan(
    plan_id: uuid.UUID,
    data: PaymentPlanUpdate,
    session: SessionDep,
    user: AuthorDep,
    response: Response,
    if_match: ParentIfMatch = None,
) -> PaymentPlanOut:
    """Modifie un plan d'une grille **brouillon** ; `installments` fourni = remplace la liste.
    **If-Match de la grille obligatoire** (428 / 412) ; `ETag` = nouvel ETag de la grille."""
    plan, etag = await svc.update_payment_plan(session, plan_id, user, data, if_match)
    response.headers["ETag"] = etag
    return await svc.plan_out(session, plan)


@staff_router.delete("/payment-plans/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_payment_plan(
    plan_id: uuid.UUID, session: SessionDep, user: AuthorDep, if_match: ParentIfMatch = None
) -> Response:
    """Retire un plan d'une grille brouillon (If-Match de la grille vérifié s'il est fourni)."""
    etag = await svc.delete_payment_plan(session, plan_id, user, if_match)
    return Response(status_code=status.HTTP_204_NO_CONTENT, headers={"ETag": etag})


router = APIRouter()
router.include_router(public_router)
router.include_router(staff_router)
