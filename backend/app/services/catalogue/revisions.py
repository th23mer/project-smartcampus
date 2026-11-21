"""Révisions des entités stables publiées : institution, formation, spécialité (SA-20 D1,
validée le 17/11/2026).

Une entité stable (SA-12 catégorie A) publiée ne se modifie pas par PATCH et ne peut pas être
dupliquée (code unique). Une **révision** stocke à part les champs proposés
(`catalogue_revision.changes`) :

    draft ──submit──▶ pending_review ──publish──▶ published   (changements appliqués sur place)
      │                     │
      └──────reject─────────┴──────────▶ rejected             (révision abandonnée)

- la ligne publiée reste visible **telle quelle** jusqu'à la publication de la révision ;
- rôles et 4 yeux identiques à la publication (D-B, D-H) : un responsable de l'établissement
  propose et soumet ; un AUTRE responsable du même établissement, ou la direction, publie ou
  rejette ; l'admin jamais ; l'auteur peut abandonner son brouillon ;
- au plus une révision ouverte (draft ou pending_review) par entité (index unique partiel) ;
- traces : `status_history` sur l'entité (`metadata.kind = "revision"`, transitions
  published → pending_review → published) et `catalogue_audit_log` (mise à jour de l'entité,
  auteur = publieur) via le trigger `audit_catalogue()`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ValidationError
from pydantic_core import to_jsonable_python
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ErrorCode
from app.core.security import CurrentUser
from app.models import CatalogueRevision
from app.schemas.programmes import InstitutionUpdate, ProgrammeUpdate, SpecialityUpdate
from app.services.catalogue import publication as pub
from app.services.catalogue.programmes import (
    INSTITUTION_SPEC,
    PROGRAMME_SPEC,
    SPECIALITY_SPEC,
    apply_patch,
)
from app.services.catalogue.publication import Action, PublishableSpec, authorize
from app.services.catalogue.tx import flush_or_translate, staff_transaction

#: entity_type → (spec, schéma des champs révisables, colonnes non nulles)
REVISABLE: dict[str, tuple[PublishableSpec, type[BaseModel], tuple[str, ...]]] = {
    "institution": (INSTITUTION_SPEC, InstitutionUpdate, ("name_fr", "city")),
    "programme": (
        PROGRAMME_SPEC,
        ProgrammeUpdate,
        ("code", "name_fr", "programme_type", "duration_years"),
    ),
    "speciality": (SPECIALITY_SPEC, SpecialityUpdate, ("code", "name_fr")),
}
#: Champs jamais révisables : la période de validité d'une entité publiée (archiver à la place).
NOT_REVISABLE = frozenset({"valid_from", "valid_to"})
OPEN_STATUSES = ("draft", "pending_review")


def _now() -> datetime:
    return datetime.now(UTC)


def validate_changes(entity_type: str, changes: dict[str, Any]) -> dict[str, Any]:
    """Valide les champs proposés avec le schéma du PATCH de l'entité ; 422 sinon."""
    _spec, schema, non_nullable = REVISABLE[entity_type]
    blocked = sorted(set(changes) & NOT_REVISABLE)
    if blocked:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            message="La période de validité d'une entité publiée ne se révise pas : archivez-la.",
            details=[
                {"field": f"changes.{k}", "issue": "not_revisable", "location": "body"}
                for k in blocked
            ],
        )
    try:
        model = schema.model_validate(changes)
    except ValidationError as exc:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            details=[
                {
                    "field": "changes." + ".".join(str(p) for p in e["loc"]),
                    "issue": "required" if e["type"] == "missing" else e["type"],
                    "location": "body",
                }
                for e in exc.errors()
            ],
        ) from exc
    data = model.model_dump(mode="json", exclude_unset=True)
    nulls = [k for k, v in data.items() if v is None and k in non_nullable]
    if nulls:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            details=[
                {"field": f"changes.{k}", "issue": "null_not_allowed", "location": "body"}
                for k in nulls
            ],
        )
    return data


def render(rev: CatalogueRevision, entity: Any) -> dict[str, Any]:
    """Révision + valeurs publiées actuelles des champs proposés (aide à la relecture)."""
    data = {c.key: getattr(rev, c.key) for c in CatalogueRevision.__table__.columns}
    data["current"] = {k: to_jsonable_python(getattr(entity, k, None)) for k in rev.changes}
    return data


async def _entity(session: AsyncSession, entity_type: str, entity_id: uuid.UUID) -> Any:
    spec = REVISABLE[entity_type][0]
    return await pub.load_for_update(session, spec, entity_id)


async def _institution(session: AsyncSession, entity_type: str, row: Any) -> uuid.UUID:
    return await pub.institution_of(session, REVISABLE[entity_type][0], row)


async def _revision(
    session: AsyncSession, entity_type: str, entity_id: uuid.UUID, revision_id: uuid.UUID
) -> CatalogueRevision:
    rev = await session.scalar(
        select(CatalogueRevision)
        .where(
            CatalogueRevision.id == revision_id,
            CatalogueRevision.entity_type == entity_type,
            CatalogueRevision.entity_id == entity_id,
        )
        .with_for_update()
    )
    if rev is None:
        raise AppError(ErrorCode.NOT_FOUND)
    return rev


def _transition_error(rev: CatalogueRevision, target: str) -> AppError:
    allowed = {"draft": ["pending_review", "rejected"], "pending_review": ["published", "rejected"]}
    return AppError(
        ErrorCode.INVALID_STATUS_TRANSITION,
        details={
            "current_status": rev.status,
            "target_status": target,
            "allowed": allowed.get(rev.status, []),
        },
    )


def _history_meta(rev: CatalogueRevision, **extra: Any) -> dict[str, Any]:
    return {"kind": "revision", "revision_id": str(rev.id), "fields": sorted(rev.changes), **extra}


# --- Lecture -----------------------------------------------------------------------------------


async def list_revisions(
    session: AsyncSession, user: CurrentUser, entity_type: str, entity_id: uuid.UUID
) -> list[dict[str, Any]]:
    entity = await pub.get_for_staff(session, REVISABLE[entity_type][0], entity_id, user)
    revs = (
        await session.scalars(
            select(CatalogueRevision)
            .where(
                CatalogueRevision.entity_type == entity_type,
                CatalogueRevision.entity_id == entity_id,
            )
            .order_by(CatalogueRevision.created_at.desc(), CatalogueRevision.id)
        )
    ).all()
    return [render(r, entity) for r in revs]


async def get_revision(
    session: AsyncSession,
    user: CurrentUser,
    entity_type: str,
    entity_id: uuid.UUID,
    revision_id: uuid.UUID,
) -> tuple[dict[str, Any], CatalogueRevision]:
    entity = await pub.get_for_staff(session, REVISABLE[entity_type][0], entity_id, user)
    rev = await session.scalar(
        select(CatalogueRevision).where(
            CatalogueRevision.id == revision_id,
            CatalogueRevision.entity_type == entity_type,
            CatalogueRevision.entity_id == entity_id,
        )
    )
    if rev is None:
        raise AppError(ErrorCode.NOT_FOUND)
    return render(rev, entity), rev


# --- Écriture ----------------------------------------------------------------------------------


async def propose(
    session: AsyncSession,
    user: CurrentUser,
    entity_type: str,
    entity_id: uuid.UUID,
    changes: dict[str, Any],
    reason: str | None,
) -> tuple[dict[str, Any], CatalogueRevision]:
    """Crée une révision `draft` d'une entité **publiée** (auteur : responsable du périmètre)."""
    async with staff_transaction(session, user):
        entity = await _entity(session, entity_type, entity_id)
        await authorize(
            session, user, Action.EDIT, await _institution(session, entity_type, entity)
        )
        if entity.publication_status != "published":
            raise AppError(
                ErrorCode.INVALID_STATUS_TRANSITION,
                message="Seule une entité publiée se révise ; un brouillon se modifie par PATCH.",
                details={
                    "current_status": entity.publication_status,
                    "hint": "patch" if entity.publication_status == "draft" else None,
                },
            )
        data = validate_changes(entity_type, changes)
        open_rev = await session.scalar(
            select(CatalogueRevision.id).where(
                CatalogueRevision.entity_type == entity_type,
                CatalogueRevision.entity_id == entity_id,
                CatalogueRevision.status.in_(OPEN_STATUSES),
            )
        )
        if open_rev is not None:
            raise AppError(
                ErrorCode.CONFLICT,
                message="Une révision est déjà en cours pour cette entité.",
                details={"open_revision_id": str(open_rev)},
            )
        rev = CatalogueRevision(
            entity_type=entity_type,
            entity_id=entity_id,
            changes=data,
            reason_fr=reason,
            created_by=user.id,
        )
        session.add(rev)
        await flush_or_translate(session)
    await session.refresh(rev)
    return render(rev, entity), rev


async def submit(
    session: AsyncSession,
    user: CurrentUser,
    entity_type: str,
    entity_id: uuid.UUID,
    revision_id: uuid.UUID,
    if_match: str | None,
) -> tuple[dict[str, Any], CatalogueRevision]:
    """`draft → pending_review` ; l'entité publiée reste inchangée et visible."""
    spec = REVISABLE[entity_type][0]
    async with staff_transaction(session, user):
        entity = await _entity(session, entity_type, entity_id)
        rev = await _revision(session, entity_type, entity_id, revision_id)
        await authorize(
            session, user, Action.SUBMIT, await _institution(session, entity_type, entity)
        )
        pub.check_if_match(rev, if_match, required=True)
        if rev.status != "draft":
            raise _transition_error(rev, "pending_review")
        rev.status = "pending_review"
        rev.submitted_by = user.id
        rev.submitted_at = _now()
        await pub.record_status(
            session,
            spec,
            entity,
            "published",
            "pending_review",
            user,
            reason=rev.reason_fr,
            metadata=_history_meta(rev),
        )
        await flush_or_translate(session)
    await session.refresh(rev)
    return render(rev, entity), rev


async def publish(
    session: AsyncSession,
    user: CurrentUser,
    entity_type: str,
    entity_id: uuid.UUID,
    revision_id: uuid.UUID,
    if_match: str | None,
) -> tuple[dict[str, Any], CatalogueRevision]:
    """`pending_review → published` par une AUTRE personne : changements appliqués sur place."""
    spec, schema, non_nullable = REVISABLE[entity_type]
    async with staff_transaction(session, user):
        entity = await _entity(session, entity_type, entity_id)
        rev = await _revision(session, entity_type, entity_id, revision_id)
        await authorize(
            session, user, Action.PUBLISH, await _institution(session, entity_type, entity)
        )
        pub.check_if_match(rev, if_match, required=True)
        if rev.status != "pending_review":
            raise _transition_error(rev, "published")
        if rev.submitted_by == user.id:
            raise AppError(ErrorCode.FOUR_EYES_REQUIRED, details={"submitted_by": str(user.id)})
        if entity.publication_status != "published":
            raise AppError(
                ErrorCode.INVALID_STATUS_TRANSITION,
                message="L'entité n'est plus publiée : la révision ne peut pas être appliquée.",
                details={"current_status": entity.publication_status, "reason": "entity_changed"},
            )
        # Revalidation (le schéma a pu évoluer), puis application sur la ligne publiée.
        apply_patch(
            entity,
            schema.model_validate(validate_changes(entity_type, rev.changes)),
            non_nullable=non_nullable,
        )
        rev.status = "published"
        rev.published_by = user.id
        rev.published_at = _now()
        await pub.record_status(
            session,
            spec,
            entity,
            "pending_review",
            "published",
            user,
            requires_human=True,
            metadata=_history_meta(rev),
        )
        await flush_or_translate(session)
    await session.refresh(rev)
    await session.refresh(entity)
    return render(rev, entity), rev


async def reject(
    session: AsyncSession,
    user: CurrentUser,
    entity_type: str,
    entity_id: uuid.UUID,
    revision_id: uuid.UUID,
    reason: str,
) -> tuple[dict[str, Any], CatalogueRevision]:
    """Abandon de la révision : l'entité reste publiée telle quelle.

    - `pending_review` : relecteur (autre responsable ou direction), différent du soumetteur ;
    - `draft` : l'auteur (responsable du périmètre) abandonne son brouillon.
    """
    spec = REVISABLE[entity_type][0]
    async with staff_transaction(session, user):
        entity = await _entity(session, entity_type, entity_id)
        rev = await _revision(session, entity_type, entity_id, revision_id)
        inst = await _institution(session, entity_type, entity)
        if rev.status == "pending_review":
            await authorize(session, user, Action.REJECT, inst)
            if rev.submitted_by == user.id:
                raise AppError(
                    ErrorCode.FOUR_EYES_REQUIRED,
                    message="Le rejet doit être fait par un relecteur, pas par l'auteur.",
                    details={"submitted_by": str(user.id)},
                )
        elif rev.status == "draft":
            await authorize(session, user, Action.EDIT, inst)
        else:
            raise _transition_error(rev, "rejected")
        previous = rev.status
        rev.status = "rejected"
        rev.rejected_by = user.id
        rev.rejected_at = _now()
        rev.rejection_reason = reason
        if previous == "pending_review":
            await pub.record_status(
                session,
                spec,
                entity,
                "pending_review",
                "published",
                user,
                reason=reason,
                metadata=_history_meta(rev, outcome="rejected"),
            )
        await flush_or_translate(session)
    await session.refresh(rev)
    return render(rev, entity), rev


__all__ = [
    "NOT_REVISABLE",
    "REVISABLE",
    "get_revision",
    "list_revisions",
    "propose",
    "publish",
    "reject",
    "submit",
    "validate_changes",
]
