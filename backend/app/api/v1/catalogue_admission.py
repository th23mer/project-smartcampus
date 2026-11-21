"""Routes des conditions d'admission, prérequis et éligibilité (SA-21).

- Public : `GET /catalogue/programmes/{programme_id}/admission-conditions` (année obligatoire,
  D-J) et `POST /catalogue/eligibility-check` (calcul de code, rien n'est conservé) ;
- Staff : `/staff/catalogue/admission-conditions` (brouillons, ETag / If-Match, transitions à
  double validation) et `/staff/catalogue/prerequisites` (enfants d'un cursus brouillon).
"""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Body, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.catalogue_fees import (
    STAFF_ERRORS,
    AcademicYearQuery,
    AsOf,
    AuthorDep,
    IdempotencyKey,
    IfMatch,
    ParentIfMatch,
    ReaderDep,
    ReviewerDep,
    SessionDep,
    StatusFilter,
    _err,
)
from app.core.pagination import Page, PageParamsDep
from app.schemas.admission import (
    AdmissionConditionCreate,
    AdmissionConditionsResponse,
    AdmissionConditionStaffOut,
    AdmissionConditionUpdate,
    EligibilityRequest,
    EligibilityResult,
    PrerequisiteCreate,
    PrerequisiteOut,
    PrerequisiteUpdate,
)
from app.schemas.catalogue_common import (
    NewVersionRequest,
    OptionalReasonRequest,
    PublishRequest,
    ReasonRequest,
)
from app.services.catalogue import admission as svc
from app.services.catalogue import publication as pub
from app.services.catalogue.publication import Action, today_tunis

public_router = APIRouter(prefix="/catalogue", tags=["Catalogue public (publié et valide)"])
staff_router = APIRouter(
    prefix="/staff/catalogue",
    tags=["Catalogue : écriture et publication (staff)"],
    responses=STAFF_ERRORS,
)


# --- Public ------------------------------------------------------------------------------------


@public_router.get(
    "/programmes/{programme_id}/admission-conditions",
    response_model=AdmissionConditionsResponse,
    summary="Conditions d'admission et prérequis d'une année universitaire",
    responses={404: _err("NOT_FOUND"), 422: _err("ACADEMIC_YEAR_REQUIRED", "VALIDATION_ERROR")},
)
async def get_programme_admission_conditions(
    programme_id: uuid.UUID,
    session: SessionDep,
    academic_year: AcademicYearQuery = None,
    speciality_id: Annotated[uuid.UUID | None, Query()] = None,
    entry_level: Annotated[int | None, Query(ge=1, le=5)] = None,
    applicant_category: Annotated[
        Literal["new_bachelor", "higher_education_graduate", "transfer_student"] | None, Query()
    ] = None,
    as_of: AsOf = None,
) -> AdmissionConditionsResponse:
    """Conditions **publiées et valides** à la date pour la rentrée demandée (une par année
    d'entrée et catégorie ; la spécialité l'emporte sur la formation). Même service que
    l'outil `get_admission_conditions`."""
    return await svc.official_conditions(
        session,
        programme_id,
        academic_year,
        as_of or today_tunis(),
        speciality_id=speciality_id,
        entry_level=entry_level,
        applicant_category=applicant_category,
    )


@public_router.post(
    "/eligibility-check",
    response_model=EligibilityResult,
    summary="Vérifier l'éligibilité à une formation (calcul déterministe)",
    responses={404: _err("NOT_FOUND"), 422: _err("ACADEMIC_YEAR_REQUIRED", "VALIDATION_ERROR")},
)
async def eligibility_check(data: EligibilityRequest, session: SessionDep) -> EligibilityResult:
    """Compare le profil (série, moyenne, notes par matière, clés FR) aux conditions publiées.
    Résultat **indicatif**, critère par critère ; aucune donnée personnelle conservée.
    Même service que l'outil `check_eligibility`."""
    profile = data.model_dump(exclude={"programme_id", "speciality_id", "academic_year", "as_of"})
    return await svc.check_eligibility(
        session,
        data.programme_id,
        data.academic_year,
        data.as_of or today_tunis(),
        svc.BacProfile(**profile),
        speciality_id=data.speciality_id,
    )


# --- Staff : conditions d'admission ----------------------------------------------------------


async def _out(session: AsyncSession, row, response: Response) -> AdmissionConditionStaffOut:
    out = await svc.staff_out(session, row)
    response.headers["ETag"] = out.etag
    return out


@staff_router.get("/admission-conditions", response_model=Page[AdmissionConditionStaffOut])
async def list_admission_conditions(
    session: SessionDep,
    user: ReaderDep,
    page: PageParamsDep,
    programme_id: Annotated[uuid.UUID | None, Query()] = None,
    academic_year: AcademicYearQuery = None,
    publication_status: StatusFilter = None,
) -> Page[AdmissionConditionStaffOut]:
    items, total = await svc.list_conditions(
        session,
        user,
        page,
        programme_id=programme_id,
        academic_year=academic_year,
        publication_status=list(publication_status) if publication_status else None,
    )
    return Page[AdmissionConditionStaffOut].build(items, total, page)


@staff_router.post(
    "/admission-conditions",
    status_code=status.HTTP_201_CREATED,
    response_model=AdmissionConditionStaffOut,
)
async def create_admission_condition(
    data: AdmissionConditionCreate,
    session: SessionDep,
    user: AuthorDep,
    response: Response,
    _key: IdempotencyKey = None,
) -> AdmissionConditionStaffOut:
    """Crée une condition **brouillon** (avec ses notes minimales par matière)."""
    return await _out(session, await svc.create_condition(session, user, data), response)


@staff_router.get("/admission-conditions/{row_id}", response_model=AdmissionConditionStaffOut)
async def get_admission_condition(
    row_id: uuid.UUID, session: SessionDep, user: ReaderDep, response: Response
) -> AdmissionConditionStaffOut:
    return await _out(session, await svc.get_condition(session, row_id, user), response)


@staff_router.patch("/admission-conditions/{row_id}", response_model=AdmissionConditionStaffOut)
async def update_admission_condition(
    row_id: uuid.UUID,
    data: AdmissionConditionUpdate,
    session: SessionDep,
    user: AuthorDep,
    response: Response,
    if_match: IfMatch = None,
) -> AdmissionConditionStaffOut:
    """Modifie un **brouillon** (If-Match obligatoire) ; `subject_requirements` = remplace."""
    row = await svc.update_condition(session, row_id, user, data, if_match)
    return await _out(session, row, response)


@staff_router.delete("/admission-conditions/{row_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_admission_condition(
    row_id: uuid.UUID, session: SessionDep, user: AuthorDep, if_match: IfMatch = None
) -> Response:
    await svc.delete_condition(session, row_id, user, if_match)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@staff_router.post(
    "/admission-conditions/{row_id}/submit", response_model=AdmissionConditionStaffOut
)
async def submit_admission_condition(
    row_id: uuid.UUID,
    session: SessionDep,
    user: AuthorDep,
    response: Response,
    if_match: IfMatch = None,
    _key: IdempotencyKey = None,
) -> AdmissionConditionStaffOut:
    row = await pub.run_transition(
        session, svc.ADMISSION_SPEC, row_id, user, Action.SUBMIT, if_match=if_match,
        if_match_required=True,
    )  # fmt: skip
    return await _out(session, row, response)


@staff_router.post(
    "/admission-conditions/{row_id}/publish", response_model=AdmissionConditionStaffOut
)
async def publish_admission_condition(
    row_id: uuid.UUID,
    session: SessionDep,
    user: ReviewerDep,
    response: Response,
    body: Annotated[PublishRequest | None, Body()] = None,
    if_match: IfMatch = None,
    _key: IdempotencyKey = None,
) -> AdmissionConditionStaffOut:
    """Publication à 4 yeux (publieur ≠ soumetteur ; jamais l'admin)."""
    row = await pub.run_transition(
        session,
        svc.ADMISSION_SPEC,
        row_id,
        user,
        Action.PUBLISH,
        if_match=if_match,
        if_match_required=True,
        replace_current=bool(body and body.replace_current),
    )
    return await _out(session, row, response)


@staff_router.post(
    "/admission-conditions/{row_id}/reject", response_model=AdmissionConditionStaffOut
)
async def reject_admission_condition(
    row_id: uuid.UUID,
    body: ReasonRequest,
    session: SessionDep,
    user: ReviewerDep,
    response: Response,
    if_match: IfMatch = None,
    _key: IdempotencyKey = None,
) -> AdmissionConditionStaffOut:
    row = await pub.run_transition(
        session, svc.ADMISSION_SPEC, row_id, user, Action.REJECT, if_match=if_match,
        reason=body.reason,
    )  # fmt: skip
    return await _out(session, row, response)


@staff_router.post(
    "/admission-conditions/{row_id}/archive", response_model=AdmissionConditionStaffOut
)
async def archive_admission_condition(
    row_id: uuid.UUID,
    session: SessionDep,
    user: ReviewerDep,
    response: Response,
    body: Annotated[OptionalReasonRequest | None, Body()] = None,
    if_match: IfMatch = None,
    _key: IdempotencyKey = None,
) -> AdmissionConditionStaffOut:
    row = await pub.run_transition(
        session, svc.ADMISSION_SPEC, row_id, user, Action.ARCHIVE, if_match=if_match,
        reason=body.reason if body else None,
    )  # fmt: skip
    return await _out(session, row, response)


@staff_router.post(
    "/admission-conditions/{row_id}/new-version",
    status_code=status.HTTP_201_CREATED,
    response_model=AdmissionConditionStaffOut,
)
async def new_admission_condition_version(
    row_id: uuid.UUID,
    session: SessionDep,
    user: AuthorDep,
    response: Response,
    body: Annotated[NewVersionRequest | None, Body()] = None,
    _key: IdempotencyKey = None,
) -> AdmissionConditionStaffOut:
    row = await pub.run_transition(
        session, svc.ADMISSION_SPEC, row_id, user, Action.NEW_VERSION,
        overrides=body.model_dump(exclude_none=True) if body else None,
    )  # fmt: skip
    return await _out(session, row, response)


# --- Staff : prérequis (enfants d'un cursus brouillon) ----------------------------------------


@staff_router.get("/prerequisites", response_model=list[PrerequisiteOut])
async def list_prerequisites(
    curriculum_id: Annotated[uuid.UUID, Query()], session: SessionDep, user: ReaderDep
) -> list[PrerequisiteOut]:
    return await svc.list_prerequisites(session, curriculum_id, user)


@staff_router.post(
    "/prerequisites", status_code=status.HTTP_201_CREATED, response_model=PrerequisiteOut
)
async def create_prerequisite(
    data: PrerequisiteCreate,
    session: SessionDep,
    user: AuthorDep,
    response: Response,
    if_match: ParentIfMatch = None,
    _key: IdempotencyKey = None,
) -> PrerequisiteOut:
    """Ajoute un prérequis à un cursus **brouillon** (If-Match du cursus vérifié s'il est
    fourni) ; `ETag` renvoyé = nouvel ETag du cursus."""
    row, etag = await svc.create_prerequisite(session, user, data, if_match)
    response.headers["ETag"] = etag
    return svc.prerequisite_out(row)


@staff_router.get("/prerequisites/{row_id}", response_model=PrerequisiteOut)
async def get_prerequisite(
    row_id: uuid.UUID, session: SessionDep, user: ReaderDep
) -> PrerequisiteOut:
    return svc.prerequisite_out(await svc.get_prerequisite(session, row_id, user))


@staff_router.patch("/prerequisites/{row_id}", response_model=PrerequisiteOut)
async def update_prerequisite(
    row_id: uuid.UUID,
    data: PrerequisiteUpdate,
    session: SessionDep,
    user: AuthorDep,
    response: Response,
    if_match: ParentIfMatch = None,
) -> PrerequisiteOut:
    """Modifie un prérequis : **If-Match du cursus obligatoire** (428 / 412)."""
    row, etag = await svc.update_prerequisite(session, row_id, user, data, if_match)
    response.headers["ETag"] = etag
    return svc.prerequisite_out(row)


@staff_router.delete("/prerequisites/{row_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_prerequisite(
    row_id: uuid.UUID, session: SessionDep, user: AuthorDep, if_match: ParentIfMatch = None
) -> Response:
    etag = await svc.delete_prerequisite(session, row_id, user, if_match)
    return Response(status_code=status.HTTP_204_NO_CONTENT, headers={"ETag": etag})


router = APIRouter()
router.include_router(public_router)
router.include_router(staff_router)
