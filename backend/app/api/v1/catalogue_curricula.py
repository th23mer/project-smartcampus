"""Routes des cursus et de leurs matières (SA-20).

- `GET /catalogue/programmes/{programme_id}/curricula` (public) : cursus publiés et valides,
  par semestre, avec crédits, heures et prérequis ;
- `/staff/catalogue/curricula[...]` : brouillons, matières du cursus (enfants modifiables
  seulement en brouillon, If-Match sur le cursus), suppression d'un brouillon (avec ses
  matières et prérequis, en cascade), submit / publish / reject / archive,
  nouvelle version copiée depuis une version publiée.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.catalogue_programmes import (
    NOT_FOUND,
    STAFF_ERRORS,
    AuthorDep,
    IdempotencyKey,
    IfMatch,
    OnDate,
    ReaderDep,
    SessionDep,
    delete_route,
    publication_routes,
    read_routes,
    with_etag,
)
from app.models import Curriculum
from app.schemas.curricula import (
    CurriculumCreate,
    CurriculumList,
    CurriculumNewVersion,
    CurriculumStaff,
    CurriculumStaffDetail,
    CurriculumSubjectCreate,
    CurriculumSubjectStaff,
    CurriculumSubjectUpdate,
    CurriculumUpdate,
)
from app.services.catalogue import curricula as svc
from app.services.catalogue import programmes as prog_svc

public_router = APIRouter(prefix="/catalogue", tags=["Catalogue public (publié et valide)"])
staff_router = APIRouter(
    prefix="/staff/catalogue",
    tags=["Catalogue : écriture et publication (staff)"],
    responses=STAFF_ERRORS,
)


@public_router.get(
    "/programmes/{programme_id}/curricula",
    response_model=CurriculumList,
    responses=NOT_FOUND,
    summary="Cursus (années, semestres, matières)",
    description="Cursus publiés et valides de la formation (tronc commun et spécialités "
    "officielles). `speciality_id` : cursus de cette spécialité + tronc commun.",
)
async def public_curricula(
    programme_id: uuid.UUID,
    session: SessionDep,
    speciality_id: Annotated[uuid.UUID | None, Query()] = None,
    on_date: OnDate = None,
) -> dict:
    items = await svc.get_programme_curricula(
        session, programme_id, speciality_id=speciality_id, on_date=on_date
    )
    return {"items": items}


async def _detail(session: AsyncSession, row: Curriculum) -> dict[str, Any]:
    data = CurriculumStaff.model_validate(row).model_dump()
    data["subjects"] = await svc.staff_curriculum_lines(session, row.id)
    return data


read_routes(
    staff_router,
    "curricula",
    svc.CURRICULUM_SPEC,
    CurriculumStaffDetail,
    serialize=_detail,
    list_out=CurriculumStaff,
)


@staff_router.post(
    "/curricula",
    response_model=CurriculumStaffDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Créer un cursus (brouillon)",
)
async def create_curriculum(
    body: CurriculumCreate,
    session: SessionDep,
    user: AuthorDep,
    response: Response,
    _idem: IdempotencyKey = None,
) -> Any:
    row = await svc.create_curriculum(session, user, body)
    with_etag(response, row)
    return await _detail(session, row)


@staff_router.patch(
    "/curricula/{row_id}",
    response_model=CurriculumStaffDetail,
    summary="Modifier un cursus (brouillon, If-Match)",
)
async def update_curriculum(
    row_id: uuid.UUID,
    body: CurriculumUpdate,
    session: SessionDep,
    user: AuthorDep,
    response: Response,
    if_match: IfMatch = None,
) -> Any:
    row = await svc.update_curriculum(session, user, row_id, body, if_match)
    with_etag(response, row)
    return await _detail(session, row)


delete_route(staff_router, "curricula", svc.CURRICULUM_SPEC)
publication_routes(
    staff_router,
    "curricula",
    svc.CURRICULUM_SPEC,
    CurriculumStaffDetail,
    serialize=_detail,
    new_version_body=CurriculumNewVersion,
)


# --- Matières du cursus (l'ETag renvoyé est celui du cursus parent) ---


@staff_router.get(
    "/curricula/{row_id}/subjects",
    response_model=list[CurriculumSubjectStaff],
    summary="Matières d'un cursus",
)
async def list_lines(
    row_id: uuid.UUID, session: SessionDep, user: ReaderDep, response: Response
) -> Any:
    cur = await prog_svc.staff_get(session, user, svc.CURRICULUM_SPEC, row_id)
    with_etag(response, cur)
    return await svc.staff_curriculum_lines(session, cur.id)


@staff_router.post(
    "/curricula/{row_id}/subjects",
    response_model=CurriculumSubjectStaff,
    status_code=status.HTTP_201_CREATED,
    summary="Ajouter une matière au cursus (brouillon, If-Match du cursus)",
)
async def add_line(
    row_id: uuid.UUID,
    body: CurriculumSubjectCreate,
    session: SessionDep,
    user: AuthorDep,
    response: Response,
    if_match: IfMatch = None,
    _idem: IdempotencyKey = None,
) -> Any:
    line, cur = await svc.add_line(session, user, row_id, body, if_match)
    with_etag(response, cur)
    return line


@staff_router.patch(
    "/curricula/{row_id}/subjects/{line_id}",
    response_model=CurriculumSubjectStaff,
    summary="Modifier une matière du cursus (brouillon, If-Match du cursus)",
)
async def update_line(
    row_id: uuid.UUID,
    line_id: uuid.UUID,
    body: CurriculumSubjectUpdate,
    session: SessionDep,
    user: AuthorDep,
    response: Response,
    if_match: IfMatch = None,
) -> Any:
    line, cur = await svc.update_line(session, user, row_id, line_id, body, if_match)
    with_etag(response, cur)
    return line


@staff_router.delete(
    "/curricula/{row_id}/subjects/{line_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Retirer une matière du cursus (brouillon, If-Match du cursus)",
)
async def delete_line(
    row_id: uuid.UUID,
    line_id: uuid.UUID,
    session: SessionDep,
    user: AuthorDep,
    if_match: IfMatch = None,
) -> Response:
    cur = await svc.delete_line(session, user, row_id, line_id, if_match)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    with_etag(response, cur)
    return response


router = APIRouter()
router.include_router(public_router)
router.include_router(staff_router)
