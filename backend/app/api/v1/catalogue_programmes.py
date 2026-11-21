"""Routes des formations, spécialités, matières, établissements et passerelles (SA-20).

- `/catalogue/...` (public) : publié et valide seulement, recherche, filtres, tri, pagination ;
- `/staff/catalogue/...` : brouillons, ETag / If-Match, transitions de publication à double
  validation (noyau SA-21 `publication.py`), suppression des brouillons et des matières
  inutilisées (`deletion.py`, décision du 21/11).

`publication_routes(...)` est réutilisée par `catalogue_curricula.py`.
"""

import uuid
from collections.abc import Callable
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Header, Query, Response, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.pagination import Page, PageParamsDep
from app.core.security import CurrentUser, Role, require_roles
from app.schemas.catalogue_common import (
    OptionalReasonRequest,
    PublishRequest,
    ReasonRequest,
)
from app.schemas.common import ErrorResponse
from app.schemas.programmes import (
    BridgeCreate,
    BridgeNewVersion,
    BridgePublic,
    BridgeStaff,
    BridgeUpdate,
    InstitutionList,
    InstitutionStaff,
    ProgrammeCreate,
    ProgrammeDetail,
    ProgrammeStaff,
    ProgrammeSummary,
    ProgrammeUpdate,
    RevisionCreate,
    RevisionOut,
    SpecialityCreate,
    SpecialityPublic,
    SpecialityStaff,
    SpecialityUpdate,
    SubjectCreate,
    SubjectStaff,
    SubjectUpdate,
)
from app.services.catalogue import deletion as del_svc
from app.services.catalogue import programmes as svc
from app.services.catalogue import publication as pub
from app.services.catalogue import revisions as rev_svc
from app.services.catalogue.publication import Action, PublishableSpec, compute_etag

SessionDep = Annotated[AsyncSession, Depends(get_session)]

#: Rôles (matrice SA-5 §4) : lecture staff, rédaction (auteur), relecture (publication).
READERS = (Role.IIT_ACADEMIC_LEAD, Role.ISB_ACADEMIC_LEAD, Role.DIRECTION, Role.PLATFORM_ADMIN)
AUTHORS = (Role.IIT_ACADEMIC_LEAD, Role.ISB_ACADEMIC_LEAD)
REVIEWERS = (Role.IIT_ACADEMIC_LEAD, Role.ISB_ACADEMIC_LEAD, Role.DIRECTION)

ReaderDep = Annotated[CurrentUser, Depends(require_roles(*READERS))]
AuthorDep = Annotated[CurrentUser, Depends(require_roles(*AUTHORS))]
ReviewerDep = Annotated[CurrentUser, Depends(require_roles(*REVIEWERS))]

IfMatch = Annotated[
    str | None,
    Header(alias="If-Match", description="ETag reçu à la lecture (obligatoire, SA-5 §1.6)."),
]
IdempotencyKey = Annotated[
    str | None,
    Header(
        alias="Idempotency-Key",
        description="UUID client (SA-5 §1.6). Accepté ; le rejeu sera branché par le "
        "middleware d'idempotence commun.",
    ),
]
OnDate = Annotated[
    date | None,
    Query(
        alias="date",
        description="Date de référence « valide à la date D » (défaut : aujourd'hui à Tunis).",
    ),
]
Multi = Annotated[list[str] | None, Query()]

STAFF_ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "UNAUTHENTICATED"},
    403: {"model": ErrorResponse, "description": "FORBIDDEN, FOUR_EYES_REQUIRED"},
    404: {"model": ErrorResponse, "description": "NOT_FOUND (inexistant ou hors périmètre)"},
    409: {
        "model": ErrorResponse,
        "description": "INVALID_STATUS_TRANSITION, VALIDITY_OVERLAP, CONFLICT",
    },
    412: {"model": ErrorResponse, "description": "PRECONDITION_FAILED (If-Match périmé)"},
    428: {"model": ErrorResponse, "description": "PRECONDITION_REQUIRED (If-Match absent)"},
}
NOT_FOUND = {404: {"model": ErrorResponse, "description": "NOT_FOUND"}}

public_router = APIRouter(prefix="/catalogue", tags=["Catalogue public (publié et valide)"])
staff_router = APIRouter(
    prefix="/staff/catalogue",
    tags=["Catalogue : écriture et publication (staff)"],
    responses=STAFF_ERRORS,
)


def with_etag(response: Response, row: Any) -> None:
    response.headers["ETag"] = compute_etag(row)


# ============ Public ============


@public_router.get(
    "/institutions", response_model=InstitutionList, summary="Établissements publiés (IIT, ISB)"
)
async def public_institutions(session: SessionDep, on_date: OnDate = None) -> dict:
    return {"items": await svc.list_institutions(session, on_date or svc.today_tunis())}


@public_router.get(
    "/programmes",
    response_model=Page[ProgrammeSummary],
    summary="Rechercher des formations publiées et valides",
    description=(
        "Filtres combinables : `q` (mots-clés FR/AR, insensible à la casse et aux accents ; "
        "chaque mot doit apparaître dans la formation ou une de ses spécialités), "
        "`institution` (code ou UUID, répétable), `level` (preparatory|prepa, licence, "
        "engineering|ingenieur, master, other ; répétable), `speciality` (code ou nom). "
        "Tri : `relevance` (défaut avec `q`), `name` (défaut), `code`, `duration_years`, "
        "préfixe `-` pour décroissant."
    ),
)
async def public_programmes(
    session: SessionDep,
    params: PageParamsDep,
    q: Annotated[str | None, Query(max_length=200)] = None,
    institution: Multi = None,
    level: Multi = None,
    speciality: Annotated[str | None, Query(max_length=100)] = None,
    sort: str | None = None,
    on_date: OnDate = None,
) -> dict:
    items, meta = await svc.search_programmes(
        session,
        svc.ProgrammeFilters(
            q=q,
            institution=institution or [],
            level=level or [],
            speciality=speciality,
            sort=sort,
            on_date=on_date,
        ),
        params,
    )
    return {"items": items, "meta": meta}


@public_router.get(
    "/programmes/{programme_id}",
    response_model=ProgrammeDetail,
    responses=NOT_FOUND,
    summary="Fiche formation (spécialités, passerelles)",
)
async def public_programme(
    programme_id: uuid.UUID, session: SessionDep, on_date: OnDate = None
) -> dict:
    return await svc.get_programme_detail(session, programme_id, on_date)


@public_router.get(
    "/specialities",
    response_model=Page[SpecialityPublic],
    summary="Spécialités publiées et valides",
)
async def public_specialities(
    session: SessionDep,
    params: PageParamsDep,
    programme_id: uuid.UUID | None = None,
    institution: Multi = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    on_date: OnDate = None,
) -> dict:
    items, meta = await svc.list_specialities(
        session,
        params,
        programme_id=programme_id,
        institution=institution,
        q=q,
        on_date=on_date,
    )
    return {"items": items, "meta": meta}


@public_router.get(
    "/specialities/{speciality_id}",
    response_model=SpecialityPublic,
    responses=NOT_FOUND,
    summary="Fiche spécialité",
)
async def public_speciality(
    speciality_id: uuid.UUID, session: SessionDep, on_date: OnDate = None
) -> dict:
    return await svc.get_speciality(session, speciality_id, on_date)


@public_router.get(
    "/bridges",
    response_model=Page[BridgePublic],
    summary="Passerelles entre parcours",
    description="Filtres : `from_programme_id`, `to_programme_id`, `institution` (départ ou "
    "arrivée), `to_level`. Tri : `from` (défaut), `to`, `entry_level`.",
)
async def public_bridges(
    session: SessionDep,
    params: PageParamsDep,
    from_programme_id: uuid.UUID | None = None,
    to_programme_id: uuid.UUID | None = None,
    institution: Multi = None,
    to_level: Multi = None,
    sort: str | None = None,
    on_date: OnDate = None,
) -> dict:
    items, meta = await svc.list_bridges(
        session,
        params,
        from_programme_id=from_programme_id,
        to_programme_id=to_programme_id,
        institution=institution,
        to_level=to_level,
        sort=sort,
        on_date=on_date,
    )
    return {"items": items, "meta": meta}


# ============ Staff : fabrique des routes de lecture et de publication ============


def publication_routes(
    router: APIRouter,
    path: str,
    spec: PublishableSpec,
    out: type[BaseModel],
    *,
    serialize: Callable[[AsyncSession, Any], Any] | None = None,
    new_version_body: type[BaseModel] | None = None,
) -> None:
    """Ajoute submit / publish / reject / archive (et new-version) pour une entité publiable.

    Contrôles : rôle (route) puis périmètre, If-Match, état, 4 yeux, chevauchement
    (`publication.run_transition`, SA-21).
    """

    async def _render(session: AsyncSession, response: Response, row: Any) -> Any:
        with_etag(response, row)
        return await serialize(session, row) if serialize else row

    @router.post(
        f"/{path}/{{row_id}}/submit",
        response_model=out,
        summary=f"Soumettre ({spec.label_fr}) à la relecture",
    )
    async def submit(
        row_id: uuid.UUID,
        session: SessionDep,
        user: AuthorDep,
        response: Response,
        if_match: IfMatch = None,
        _idem: IdempotencyKey = None,
    ) -> Any:
        row = await pub.run_transition(
            session, spec, row_id, user, Action.SUBMIT, if_match=if_match, if_match_required=True
        )
        return await _render(session, response, row)

    @router.post(
        f"/{path}/{{row_id}}/publish",
        response_model=out,
        summary=f"Publier ({spec.label_fr}) : seconde personne (4 yeux)",
    )
    async def publish(
        row_id: uuid.UUID,
        session: SessionDep,
        user: ReviewerDep,
        response: Response,
        body: Annotated[PublishRequest | None, Body()] = None,
        if_match: IfMatch = None,
        _idem: IdempotencyKey = None,
    ) -> Any:
        row = await pub.run_transition(
            session,
            spec,
            row_id,
            user,
            Action.PUBLISH,
            if_match=if_match,
            if_match_required=True,
            replace_current=bool(body and body.replace_current),
        )
        return await _render(session, response, row)

    @router.post(
        f"/{path}/{{row_id}}/reject",
        response_model=out,
        summary=f"Renvoyer ({spec.label_fr}) en brouillon (motif)",
    )
    async def reject(
        row_id: uuid.UUID,
        body: ReasonRequest,
        session: SessionDep,
        user: ReviewerDep,
        response: Response,
        if_match: IfMatch = None,
        _idem: IdempotencyKey = None,
    ) -> Any:
        row = await pub.run_transition(
            session, spec, row_id, user, Action.REJECT, if_match=if_match, reason=body.reason
        )
        return await _render(session, response, row)

    @router.post(
        f"/{path}/{{row_id}}/archive",
        response_model=out,
        summary=f"Archiver ({spec.label_fr}) une ligne publiée",
    )
    async def archive(
        row_id: uuid.UUID,
        session: SessionDep,
        user: ReviewerDep,
        response: Response,
        body: Annotated[OptionalReasonRequest | None, Body()] = None,
        if_match: IfMatch = None,
        _idem: IdempotencyKey = None,
    ) -> Any:
        row = await pub.run_transition(
            session,
            spec,
            row_id,
            user,
            Action.ARCHIVE,
            if_match=if_match,
            reason=body.reason if body else None,
        )
        return await _render(session, response, row)

    if new_version_body is not None:
        body_type = new_version_body

        @router.post(
            f"/{path}/{{row_id}}/new-version",
            response_model=out,
            status_code=status.HTTP_201_CREATED,
            summary=f"Nouvelle version ({spec.label_fr}) en brouillon",
        )
        async def new_version(
            row_id: uuid.UUID,
            session: SessionDep,
            user: AuthorDep,
            response: Response,
            body: body_type,  # type: ignore[valid-type]
            _idem: IdempotencyKey = None,
        ) -> Any:
            row = await pub.run_transition(
                session,
                spec,
                row_id,
                user,
                Action.NEW_VERSION,
                overrides=body.model_dump(exclude_unset=True),
            )
            return await _render(session, response, row)


def delete_route(
    router: APIRouter, path: str, spec: PublishableSpec, *, publishable: bool = True
) -> None:
    """DELETE d'une ligne (décision du 21/11) : brouillon jamais publié pour une entité
    publiable, matière inutilisée pour le référentiel. Mêmes rôles et périmètre que la
    modification ; If-Match facultatif (vérifié s'il est fourni) ; 204 sans corps."""
    if publishable:
        summary = f"Supprimer ({spec.label_fr}) un brouillon jamais publié"
        description = (
            "Seul un brouillon (`draft`) se supprime : une ligne publiée s'archive "
            "(`POST …/archive`), une ligne en relecture doit d'abord être renvoyée en "
            "brouillon (409 `INVALID_STATUS_TRANSITION`, `details.hint`). Une ligne encore "
            "utilisée par d'autres données → 409 `CONFLICT` (`details.reason = "
            "still_referenced`, `details.referenced_by`)."
        )
    else:
        summary = f"Supprimer ({spec.label_fr}) inutilisée"
        description = (
            "Autorisé seulement si aucun cursus, prérequis ou équivalence ne l'utilise ; "
            "sinon 409 `CONFLICT` (`details.reason = still_referenced`)."
        )

    @router.delete(
        f"/{path}/{{row_id}}",
        status_code=status.HTTP_204_NO_CONTENT,
        summary=summary,
        description=description,
    )
    async def delete_row(
        row_id: uuid.UUID,
        session: SessionDep,
        user: AuthorDep,
        if_match: IfMatch = None,
    ) -> Response:
        await del_svc.delete_row(session, user, spec, row_id, if_match, publishable=publishable)
        return Response(status_code=status.HTTP_204_NO_CONTENT)


def read_routes(
    router: APIRouter,
    path: str,
    spec: PublishableSpec,
    out: type[BaseModel],
    *,
    serialize: Callable[[AsyncSession, Any], Any] | None = None,
    list_out: type[BaseModel] | None = None,
) -> None:
    """GET liste (tous statuts, périmètre ; schéma `list_out` sans enfants) et GET ligne
    (schéma `out`, avec ETag)."""

    @router.get(
        f"/{path}",
        response_model=Page[list_out or out],  # type: ignore[valid-type]
        summary=f"Lister ({spec.label_fr}), tous statuts",
    )
    async def list_rows(
        session: SessionDep,
        user: ReaderDep,
        params: PageParamsDep,
        status_: Annotated[list[str] | None, Query(alias="status")] = None,
        institution: Multi = None,
        programme_id: uuid.UUID | None = None,
        q: Annotated[str | None, Query(max_length=200)] = None,
        sort: str | None = None,
    ) -> dict:
        rows, meta = await svc.staff_list(
            session,
            user,
            spec,
            params,
            statuses=status_,
            institution=institution,
            programme_id=programme_id,
            q=q,
            sort=sort,
        )
        return {"items": rows, "meta": meta}

    @router.get(
        f"/{path}/{{row_id}}", response_model=out, summary=f"Lire ({spec.label_fr}) avec son ETag"
    )
    async def get_row(
        row_id: uuid.UUID, session: SessionDep, user: ReaderDep, response: Response
    ) -> Any:
        row = await svc.staff_get(session, user, spec, row_id)
        with_etag(response, row)
        return await serialize(session, row) if serialize else row


def revision_routes(router: APIRouter, path: str, entity_type: str, label: str) -> None:
    """Révisions d'une entité stable publiée (SA-20 D1, validée 17/11) : proposer, soumettre,
    publier (4 yeux), rejeter. L'ETag renvoyé est celui de la révision."""
    base = f"/{path}/{{entity_id}}/revisions"

    @router.get(base, response_model=list[RevisionOut], summary=f"Révisions ({label})")
    async def list_revisions(entity_id: uuid.UUID, session: SessionDep, user: ReaderDep) -> Any:
        return await rev_svc.list_revisions(session, user, entity_type, entity_id)

    @router.post(
        base,
        response_model=RevisionOut,
        status_code=status.HTTP_201_CREATED,
        summary=f"Proposer une révision ({label} publiée)",
    )
    async def propose(
        entity_id: uuid.UUID,
        body: RevisionCreate,
        session: SessionDep,
        user: AuthorDep,
        response: Response,
        _idem: IdempotencyKey = None,
    ) -> Any:
        data, rev = await rev_svc.propose(
            session, user, entity_type, entity_id, body.changes, body.reason_fr
        )
        with_etag(response, rev)
        return data

    @router.get(f"{base}/{{revision_id}}", response_model=RevisionOut, summary="Lire une révision")
    async def get_revision(
        entity_id: uuid.UUID,
        revision_id: uuid.UUID,
        session: SessionDep,
        user: ReaderDep,
        response: Response,
    ) -> Any:
        data, rev = await rev_svc.get_revision(session, user, entity_type, entity_id, revision_id)
        with_etag(response, rev)
        return data

    @router.post(
        f"{base}/{{revision_id}}/submit",
        response_model=RevisionOut,
        summary="Soumettre la révision à la relecture (If-Match)",
    )
    async def submit(
        entity_id: uuid.UUID,
        revision_id: uuid.UUID,
        session: SessionDep,
        user: AuthorDep,
        response: Response,
        if_match: IfMatch = None,
        _idem: IdempotencyKey = None,
    ) -> Any:
        data, rev = await rev_svc.submit(
            session, user, entity_type, entity_id, revision_id, if_match
        )
        with_etag(response, rev)
        return data

    @router.post(
        f"{base}/{{revision_id}}/publish",
        response_model=RevisionOut,
        summary="Publier la révision : seconde personne (4 yeux), If-Match",
    )
    async def publish(
        entity_id: uuid.UUID,
        revision_id: uuid.UUID,
        session: SessionDep,
        user: ReviewerDep,
        response: Response,
        if_match: IfMatch = None,
        _idem: IdempotencyKey = None,
    ) -> Any:
        data, rev = await rev_svc.publish(
            session, user, entity_type, entity_id, revision_id, if_match
        )
        with_etag(response, rev)
        return data

    @router.post(
        f"{base}/{{revision_id}}/reject",
        response_model=RevisionOut,
        summary="Rejeter (abandonner) la révision, motif obligatoire",
    )
    async def reject(
        entity_id: uuid.UUID,
        revision_id: uuid.UUID,
        body: ReasonRequest,
        session: SessionDep,
        user: ReviewerDep,
        response: Response,
        _idem: IdempotencyKey = None,
    ) -> Any:
        data, rev = await rev_svc.reject(
            session, user, entity_type, entity_id, revision_id, body.reason
        )
        with_etag(response, rev)
        return data


# ============ Staff : établissements (lecture seule) ============

read_routes(staff_router, "institutions", svc.INSTITUTION_SPEC, InstitutionStaff)
revision_routes(staff_router, "institutions", "institution", "établissement")

# ============ Staff : formations ============

read_routes(staff_router, "programmes", svc.PROGRAMME_SPEC, ProgrammeStaff)


@staff_router.post(
    "/programmes",
    response_model=ProgrammeStaff,
    status_code=status.HTTP_201_CREATED,
    summary="Créer une formation (brouillon)",
)
async def create_programme(
    body: ProgrammeCreate,
    session: SessionDep,
    user: AuthorDep,
    response: Response,
    _idem: IdempotencyKey = None,
) -> Any:
    row = await svc.create_programme(session, user, body)
    with_etag(response, row)
    return row


@staff_router.patch(
    "/programmes/{row_id}",
    response_model=ProgrammeStaff,
    summary="Modifier une formation (brouillon, If-Match)",
)
async def update_programme(
    row_id: uuid.UUID,
    body: ProgrammeUpdate,
    session: SessionDep,
    user: AuthorDep,
    response: Response,
    if_match: IfMatch = None,
) -> Any:
    row = await svc.update_programme(session, user, row_id, body, if_match)
    with_etag(response, row)
    return row


delete_route(staff_router, "programmes", svc.PROGRAMME_SPEC)
publication_routes(staff_router, "programmes", svc.PROGRAMME_SPEC, ProgrammeStaff)
revision_routes(staff_router, "programmes", "programme", "formation")

# ============ Staff : spécialités ============

read_routes(staff_router, "specialities", svc.SPECIALITY_SPEC, SpecialityStaff)


@staff_router.post(
    "/specialities",
    response_model=SpecialityStaff,
    status_code=status.HTTP_201_CREATED,
    summary="Créer une spécialité (brouillon)",
)
async def create_speciality(
    body: SpecialityCreate,
    session: SessionDep,
    user: AuthorDep,
    response: Response,
    _idem: IdempotencyKey = None,
) -> Any:
    row = await svc.create_speciality(session, user, body)
    with_etag(response, row)
    return row


@staff_router.patch(
    "/specialities/{row_id}",
    response_model=SpecialityStaff,
    summary="Modifier une spécialité (brouillon, If-Match)",
)
async def update_speciality(
    row_id: uuid.UUID,
    body: SpecialityUpdate,
    session: SessionDep,
    user: AuthorDep,
    response: Response,
    if_match: IfMatch = None,
) -> Any:
    row = await svc.update_speciality(session, user, row_id, body, if_match)
    with_etag(response, row)
    return row


delete_route(staff_router, "specialities", svc.SPECIALITY_SPEC)
publication_routes(staff_router, "specialities", svc.SPECIALITY_SPEC, SpecialityStaff)
revision_routes(staff_router, "specialities", "speciality", "spécialité")

# ============ Staff : matières (référentiel interne, sans publication) ============

read_routes(staff_router, "subjects", svc.SUBJECT_SPEC, SubjectStaff)


@staff_router.post(
    "/subjects",
    response_model=SubjectStaff,
    status_code=status.HTTP_201_CREATED,
    summary="Créer une matière",
)
async def create_subject(
    body: SubjectCreate,
    session: SessionDep,
    user: AuthorDep,
    response: Response,
    _idem: IdempotencyKey = None,
) -> Any:
    row = await svc.create_subject(session, user, body)
    with_etag(response, row)
    return row


@staff_router.patch(
    "/subjects/{row_id}", response_model=SubjectStaff, summary="Modifier une matière (If-Match)"
)
async def update_subject(
    row_id: uuid.UUID,
    body: SubjectUpdate,
    session: SessionDep,
    user: AuthorDep,
    response: Response,
    if_match: IfMatch = None,
) -> Any:
    row = await svc.update_subject(session, user, row_id, body, if_match)
    with_etag(response, row)
    return row


delete_route(staff_router, "subjects", svc.SUBJECT_SPEC, publishable=False)


# ============ Staff : passerelles ============

read_routes(staff_router, "bridges", svc.BRIDGE_SPEC, BridgeStaff)


@staff_router.post(
    "/bridges",
    response_model=BridgeStaff,
    status_code=status.HTTP_201_CREATED,
    summary="Créer une passerelle (brouillon)",
)
async def create_bridge(
    body: BridgeCreate,
    session: SessionDep,
    user: AuthorDep,
    response: Response,
    _idem: IdempotencyKey = None,
) -> Any:
    row = await svc.create_bridge(session, user, body)
    with_etag(response, row)
    return row


@staff_router.patch(
    "/bridges/{row_id}",
    response_model=BridgeStaff,
    summary="Modifier une passerelle (brouillon, If-Match)",
)
async def update_bridge(
    row_id: uuid.UUID,
    body: BridgeUpdate,
    session: SessionDep,
    user: AuthorDep,
    response: Response,
    if_match: IfMatch = None,
) -> Any:
    row = await svc.update_bridge(session, user, row_id, body, if_match)
    with_etag(response, row)
    return row


delete_route(staff_router, "bridges", svc.BRIDGE_SPEC)
publication_routes(
    staff_router, "bridges", svc.BRIDGE_SPEC, BridgeStaff, new_version_body=BridgeNewVersion
)

router = APIRouter()
router.include_router(public_router)
router.include_router(staff_router)

__all__ = ["delete_route", "publication_routes", "read_routes", "router", "with_etag"]
