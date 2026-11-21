"""Workflow générique de publication à double validation (SA-21, noyau partagé SA-20/SA-21).

Cycle (SA-3 P8, SA-12 §3, D-B, D-H) :

    (création) → draft ──submit──▶ pending_review ──publish──▶ published ──archive──▶ archived
                   ▲                      │
                   └──────reject──────────┘   (motif obligatoire ; submitted_by/at vidés)

Qui fait quoi (D-H, matrice SA-5 §4) :

- lire (staff) : responsable IIT/ISB (périmètre), direction, admin ; hors périmètre → 404 ;
- créer, modifier, supprimer un brouillon, soumettre, nouvelle version : responsable IIT/ISB
  de l'institution (jamais la direction ni l'admin) ;
- publier : un AUTRE responsable de la même institution, ou la direction ; publieur ≠
  soumetteur (403 FOUR_EYES_REQUIRED) ; l'admin ne publie jamais ;
- renvoyer en brouillon : mêmes rôles, relecteur ≠ soumetteur (SA-3 P8 n° 3) ;
- archiver : responsable de l'institution ou direction, seulement une ligne publiée.

Périmètre d'un responsable : `CurrentUser.institution_id` s'il est fourni, sinon l'institution
dont le `code` correspond au rôle (`iit_academic_lead` → `IIT`, `isb_academic_lead` → `ISB`).

Chaque transition écrit `status_history` (acteur staff, `requires_human = true` pour la
publication) ; le trigger `audit_catalogue()` écrit en plus `catalogue_audit_log` avec l'auteur
posé par `staff_transaction` (`tx.py`).

Lecture « officielle » : `official_filter(Model, as_of)` = publiée ET `validity @> as_of`
(SA-12 §0). C'est le seul filtre utilisé par les lectures publiques et les outils d'agent.

Pour brancher une entité (ex. SA-20 : programmes, cursus) : déclarer un `PublishableSpec`
puis appeler `run_transition(...)` depuis la route.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import ColumnElement, Select, func, inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ErrorCode
from app.core.security import CurrentUser, Role
from app.models import Institution, Programme, Speciality, StatusHistory
from app.schemas.catalogue_common import SourceRef
from app.services.catalogue.tx import flush_or_translate, staff_transaction

#: Fuseau de référence des dates « à aujourd'hui » (SA-5 : affichage et règles en heure de Tunis).
TUNIS = ZoneInfo("Africa/Tunis")


def today_tunis() -> date:
    """Date du jour à Tunis (défaut du paramètre `date` des lectures publiques)."""
    return datetime.now(TUNIS).date()


# --- Rôles et périmètre -----------------------------------------------------------------------

LEAD_ROLES: frozenset[Role] = frozenset({Role.IIT_ACADEMIC_LEAD, Role.ISB_ACADEMIC_LEAD})
#: Rôles qui peuvent publier, renvoyer en brouillon, archiver (D-H). Jamais l'admin.
REVIEWER_ROLES: frozenset[Role] = LEAD_ROLES | {Role.DIRECTION}
#: Rôles qui lisent les lignes de tous statuts (SA-5 §4 : Dir. L, Adm. ✓).
STAFF_READER_ROLES: frozenset[Role] = REVIEWER_ROLES | {Role.PLATFORM_ADMIN}
#: Code d'institution déduit du rôle quand `CurrentUser.institution_id` est absent.
ROLE_INSTITUTION_CODE: dict[Role, str] = {
    Role.IIT_ACADEMIC_LEAD: "IIT",
    Role.ISB_ACADEMIC_LEAD: "ISB",
}


class Action(StrEnum):
    """Actions staff sur une ligne publiable."""

    READ = "read"
    CREATE = "create"
    EDIT = "edit"
    DELETE = "delete"
    SUBMIT = "submit"
    PUBLISH = "publish"
    REJECT = "reject"
    ARCHIVE = "archive"
    NEW_VERSION = "new_version"


AUTHOR_ACTIONS = frozenset(
    {Action.CREATE, Action.EDIT, Action.DELETE, Action.SUBMIT, Action.NEW_VERSION}
)
REVIEW_ACTIONS = frozenset({Action.PUBLISH, Action.REJECT, Action.ARCHIVE})


async def lead_institution_ids(session: AsyncSession, user: CurrentUser) -> set[uuid.UUID]:
    """Institutions dans le périmètre d'un responsable académique (vide sinon)."""
    lead_roles = user.roles & LEAD_ROLES
    if not lead_roles:
        return set()
    if user.institution_id is not None:
        return {user.institution_id}
    codes = [ROLE_INSTITUTION_CODE[r] for r in lead_roles]
    rows = await session.scalars(select(Institution.id).where(Institution.code.in_(codes)))
    return set(rows)


async def staff_scope(session: AsyncSession, user: CurrentUser) -> set[uuid.UUID] | None:
    """Filtre de lecture staff : `None` = toutes les institutions (direction, admin),
    sinon l'ensemble des institutions du responsable."""
    if user.has_any_role(Role.DIRECTION, Role.PLATFORM_ADMIN):
        return None
    return await lead_institution_ids(session, user)


async def authorize(
    session: AsyncSession,
    user: CurrentUser,
    action: Action,
    institution_id: uuid.UUID | None,
    *,
    existing: bool = True,
) -> None:
    """Vérifie le rôle et le périmètre pour `action` sur une ligne de l'institution donnée.

    - rôle absent → 403 FORBIDDEN ;
    - ligne existante hors périmètre → 404 NOT_FOUND (SA-5 §1.3 règle S) ;
    - création hors périmètre → 403 FORBIDDEN (`details.reason = out_of_scope`).
    """
    in_scope = institution_id in await lead_institution_ids(session, user)

    def out_of_scope() -> AppError:
        if existing:
            return AppError(ErrorCode.NOT_FOUND)
        return AppError(
            ErrorCode.FORBIDDEN,
            message="Cette formation n'est pas dans votre périmètre.",
            details={"reason": "out_of_scope"},
        )

    if action == Action.READ:
        if user.has_any_role(Role.DIRECTION, Role.PLATFORM_ADMIN) or in_scope:
            return
        if user.roles & LEAD_ROLES:
            raise out_of_scope()
        raise AppError(ErrorCode.FORBIDDEN)

    if action in AUTHOR_ACTIONS:
        if not user.roles & LEAD_ROLES:
            raise AppError(ErrorCode.FORBIDDEN)
        if not in_scope:
            raise out_of_scope()
        return

    # Relecture : publier, renvoyer, archiver.
    if user.has_any_role(Role.DIRECTION):
        return
    if not user.roles & LEAD_ROLES:
        raise AppError(ErrorCode.FORBIDDEN)  # admin, responsable entretiens, candidat
    if not in_scope:
        raise out_of_scope()


# --- Déclaration d'une entité publiable ------------------------------------------------------


@dataclass(frozen=True)
class PublishableSpec:
    """Description d'une table publiable pour le workflow générique.

    - `entity_type` : valeur de `status_history.entity_type` (ex. `fee_schedule`) ;
    - `model` : classe ORM avec `PublicationBlock` ;
    - `institution_expr` : expression SQL corrélée à `model` donnant l'institution
      (périmètre) ; ex. `programme_institution_expr(FeeSchedule.programme_id)` ;
    - `business_key` : `row → [conditions]` sélectionnant les lignes de la même clé métier
      (celle de la contrainte d'exclusion). `None` pour les entités stables (A) ;
    - `copy_exclude` : colonnes à ne pas copier dans `/new-version` ;
    - `copy_children` : copie des enfants (plans de paiement, notes minimales…) ;
    - `submit_checks` : contrôles métier supplémentaires avant `submit`.
    """

    entity_type: str
    model: type[Any]
    institution_expr: Callable[[], ColumnElement[Any]]
    business_key: Callable[[Any], list[ColumnElement[bool]]] | None = None
    label_fr: str = ""
    copy_exclude: frozenset[str] = field(default_factory=frozenset)
    copy_children: Callable[[AsyncSession, Any, Any], Awaitable[None]] | None = None
    submit_checks: Callable[[AsyncSession, Any], Awaitable[None]] | None = None


def programme_institution_expr(programme_id_column: Any) -> ColumnElement[Any]:
    """Sous-requête scalaire : institution de la formation référencée par la colonne."""
    return (
        select(Programme.institution_id)
        .where(Programme.id == programme_id_column)
        .correlate_except(Programme)
        .scalar_subquery()
    )


async def programme_institution_id(
    session: AsyncSession, programme_id: uuid.UUID
) -> uuid.UUID | None:
    """Institution d'une formation (`None` si la formation n'existe pas)."""
    return await session.scalar(
        select(Programme.institution_id).where(Programme.id == programme_id)
    )


async def institution_of(session: AsyncSession, spec: PublishableSpec, row: Any) -> uuid.UUID:
    return await session.scalar(select(spec.institution_expr()).where(spec.model.id == row.id))


def scope_filter(spec: PublishableSpec, scope: set[uuid.UUID] | None) -> ColumnElement[bool] | None:
    """Condition SQL de périmètre pour une liste staff (`None` = pas de filtre)."""
    if scope is None:
        return None
    return spec.institution_expr().in_(scope or {uuid.UUID(int=0)})


# --- Lecture officielle (publiée et valide) ---------------------------------------------------


def official_filter(model: Any, as_of: date) -> ColumnElement[bool]:
    """`publication_status = 'published' AND validity @> as_of` (SA-12 §0)."""
    return (model.publication_status == "published") & model.validity.contains(as_of)


def official_select(model: Any, as_of: date, academic_year: str | None = None) -> Select[Any]:
    """`SELECT model WHERE publié et valide à as_of [AND academic_year = …]`."""
    stmt = select(model).where(official_filter(model, as_of))
    if academic_year is not None:
        stmt = stmt.where(model.academic_year == academic_year)
    return stmt


async def ensure_official_programme(
    session: AsyncSession,
    programme_id: uuid.UUID,
    as_of: date,
    speciality_id: uuid.UUID | None = None,
) -> Programme:
    """La formation (et son institution, et la spécialité demandée) doit être publiée et
    valide à `as_of` ; sinon 404 NOT_FOUND (rien d'officiel à montrer)."""
    programme = await session.scalar(
        select(Programme)
        .join(Institution, Institution.id == Programme.institution_id)
        .where(
            Programme.id == programme_id,
            official_filter(Programme, as_of),
            official_filter(Institution, as_of),
        )
    )
    if programme is None:
        raise AppError(
            ErrorCode.NOT_FOUND,
            message="Formation introuvable ou non publiée à cette date.",
            details={"programme_id": str(programme_id), "as_of": as_of.isoformat()},
        )
    if speciality_id is not None:
        found = await session.scalar(
            select(Speciality.id).where(
                Speciality.id == speciality_id,
                Speciality.programme_id == programme_id,
                official_filter(Speciality, as_of),
            )
        )
        if found is None:
            raise AppError(
                ErrorCode.NOT_FOUND,
                message="Spécialité introuvable pour cette formation ou non publiée à cette date.",
                details={"speciality_id": str(speciality_id), "as_of": as_of.isoformat()},
            )
    return programme


async def official_academic_years(
    session: AsyncSession, model: Any, as_of: date, *conditions: ColumnElement[bool]
) -> list[str]:
    """Années universitaires des lignes officielles à `as_of` (D-J : proposées au candidat)."""
    rows = await session.scalars(
        select(model.academic_year)
        .where(official_filter(model, as_of), *conditions)
        .distinct()
        .order_by(model.academic_year)
    )
    return list(rows)


def academic_year_required(available: list[str]) -> AppError:
    """422 ACADEMIC_YEAR_REQUIRED avec `details.available_academic_years` (D-J)."""
    return AppError(
        ErrorCode.ACADEMIC_YEAR_REQUIRED,
        details={"available_academic_years": available},
    )


def most_specific[T](
    rows: Sequence[T],
    bucket: Callable[[T], Any],
    specificity: Callable[[T], tuple[int, ...]],
) -> list[T]:
    """Précédence SA-12 D7 : dans chaque groupe `bucket`, garde la ligne la plus spécifique
    (plus grand tuple `specificity`, ex. `(spécialité?, année d'études?)`)."""
    best: dict[Any, T] = {}
    for row in rows:
        key = bucket(row)
        if key not in best or specificity(row) > specificity(best[key]):
            best[key] = row
    return list(best.values())


async def version_number(session: AsyncSession, spec: PublishableSpec, row: Any) -> int | None:
    """Rang de publication de `row` dans sa clé métier (1 = première version publiée).

    `None` pour une ligne jamais publiée. Calculé (pas de colonne `version` dans SA-12).
    """
    if row.published_at is None:
        return None
    if spec.business_key is None:
        return 1
    model = spec.model
    count = await session.scalar(
        select(func.count())
        .select_from(model)
        .where(
            *spec.business_key(row),
            model.publication_status.in_(("published", "archived")),
            model.published_at <= row.published_at,
        )
    )
    return int(count or 1)


async def source_ref(session: AsyncSession, spec: PublishableSpec, row: Any) -> SourceRef:
    """Carte source officielle (id, version, publication, validité)."""
    return SourceRef(
        entity_type=spec.entity_type,
        entity_id=row.id,
        version=await version_number(session, spec, row),
        published_at=row.published_at,
        valid_from=row.valid_from,
        valid_to=row.valid_to,
    )


# --- ETag / If-Match (SA-5 §1.6) --------------------------------------------------------------


def compute_etag(row: Any) -> str:
    """ETag faible calculé sur le **contenu** de la ligne (toutes ses colonnes).

    Basé sur le contenu et non sur `updated_at` : deux écritures dans la même transaction
    (même `now()`) changent quand même l'ETag.
    """
    mapper = inspect(row).mapper
    parts = [f"{col.key}={getattr(row, col.key, None)!r}" for col in mapper.column_attrs]
    digest = hashlib.sha256("|".join(parts).encode()).hexdigest()[:20]
    return f'W/"{digest}"'


def _normalize_etag(value: str) -> str:
    value = value.strip()
    if value.startswith("W/"):
        value = value[2:]
    return value.strip('"')


def check_if_match(row: Any, if_match: str | None, *, required: bool) -> None:
    """428 PRECONDITION_REQUIRED si l'en-tête manque (et est exigé) ; 412 s'il est périmé."""
    if if_match is None or not if_match.strip():
        if required:
            raise AppError(ErrorCode.PRECONDITION_REQUIRED)
        return
    if if_match.strip() == "*":
        return
    current = _normalize_etag(compute_etag(row))
    candidates = {_normalize_etag(part) for part in if_match.split(",")}
    if current not in candidates:
        raise AppError(
            ErrorCode.PRECONDITION_FAILED,
            details={"current_etag": compute_etag(row)},
        )


# --- Contrôles d'état -------------------------------------------------------------------------

#: Transitions permises (SA-3 P8). La création est hors machine.
TRANSITIONS: dict[str, tuple[str, ...]] = {
    "draft": ("pending_review",),
    "pending_review": ("published", "draft"),
    "published": ("archived",),
    "archived": (),
}


def transition_error(row: Any, target: str, *, reason: str | None = None) -> AppError:
    details: dict[str, Any] = {
        "current_status": row.publication_status,
        "target_status": target,
        "allowed": list(TRANSITIONS.get(row.publication_status, ())),
    }
    if reason:
        details["reason"] = reason
    return AppError(ErrorCode.INVALID_STATUS_TRANSITION, details=details)


def ensure_draft(row: Any) -> None:
    """Seul un brouillon est modifiable (SA-5 PATCH ; une ligne `pending_review` doit d'abord
    être renvoyée en brouillon ; une ligne publiée est figée)."""
    if row.publication_status != "draft":
        raise AppError(
            ErrorCode.INVALID_STATUS_TRANSITION,
            message="Seul un brouillon est modifiable.",
            details={
                "current_status": row.publication_status,
                "reason": "only_draft_editable",
                "hint": (
                    "new_version"
                    if row.publication_status in ("published", "archived")
                    else "reject"
                ),
            },
        )


async def record_status(
    session: AsyncSession,
    spec: PublishableSpec,
    row: Any,
    from_status: str | None,
    to_status: str,
    user: CurrentUser,
    *,
    reason: str | None = None,
    requires_human: bool = False,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Écrit une ligne `status_history` (journal des transitions, SA-3 C9)."""
    session.add(
        StatusHistory(
            entity_type=spec.entity_type,
            entity_id=row.id,
            from_status=from_status,
            to_status=to_status,
            actor_type="staff",
            actor_user_id=user.id,
            requires_human=requires_human,
            reason=reason,
            metadata_=metadata or {},
        )
    )


def _now() -> datetime:
    return datetime.now(UTC)


# --- Transitions (à appeler dans une staff_transaction) ---------------------------------------


async def submit(session: AsyncSession, spec: PublishableSpec, row: Any, user: CurrentUser) -> Any:
    """`draft → pending_review` : champs obligatoires et période cohérente (SA-3 P8 n° 2)."""
    if row.publication_status != "draft":
        raise transition_error(row, "pending_review")
    problems: list[dict[str, Any]] = []
    if row.valid_from is None:
        problems.append({"field": "valid_from", "issue": "required"})
    elif row.valid_to is not None and row.valid_to <= row.valid_from:
        problems.append({"field": "valid_to", "issue": "must_be_after_valid_from"})
    if problems:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            message="Impossible de soumettre : informations manquantes ou incohérentes.",
            details=problems,
        )
    if spec.submit_checks is not None:
        await spec.submit_checks(session, row)
    row.publication_status = "pending_review"
    row.submitted_by = user.id
    row.submitted_at = _now()
    await record_status(session, spec, row, "draft", "pending_review", user)
    await flush_or_translate(session)
    return row


async def _overlapping_published(session: AsyncSession, spec: PublishableSpec, row: Any) -> list:
    """Versions publiées de la même clé métier dont la validité chevauche celle de `row`."""
    if spec.business_key is None:
        return []
    model = spec.model
    new_range = func.daterange(row.valid_from, row.valid_to, "[)")
    rows = await session.scalars(
        select(model)
        .where(
            *spec.business_key(row),
            model.id != row.id,
            model.publication_status == "published",
            model.validity.op("&&")(new_range),
        )
        .with_for_update()
    )
    return list(rows)


async def publish(
    session: AsyncSession,
    spec: PublishableSpec,
    row: Any,
    user: CurrentUser,
    *,
    replace_current: bool = False,
) -> Any:
    """`pending_review → published` par une AUTRE personne (4 yeux, D-B).

    Chevauchement avec une version publiée de la même clé : 409 VALIDITY_OVERLAP, sauf
    `replace_current` (remplacement de version dans la même transaction, SA-12 §3).
    """
    if row.publication_status != "pending_review":
        raise transition_error(row, "published")
    if row.submitted_by == user.id:
        raise AppError(ErrorCode.FOUR_EYES_REQUIRED, details={"submitted_by": str(user.id)})

    conflicts = await _overlapping_published(session, spec, row)
    if conflicts and not replace_current:
        raise AppError(
            ErrorCode.VALIDITY_OVERLAP,
            details={
                "conflicting": [
                    {
                        "id": str(c.id),
                        "valid_from": c.valid_from.isoformat() if c.valid_from else None,
                        "valid_to": c.valid_to.isoformat() if c.valid_to else None,
                    }
                    for c in conflicts
                ],
                "hint": "replace_current",
            },
        )
    for old in conflicts:
        if old.valid_from is not None and old.valid_from < row.valid_from:
            # Raccourcir valid_to : seule modification permise sur une version publiée (garde) ;
            # la trace est dans catalogue_audit_log (pas une transition de statut).
            old.valid_to = row.valid_from
        else:
            old.publication_status = "archived"
            await record_status(
                session,
                spec,
                old,
                "published",
                "archived",
                user,
                reason="Remplacée par une nouvelle version.",
                metadata={"replaced_by": str(row.id)},
            )
    if conflicts:
        await flush_or_translate(session)  # libère la plage avant de publier la nouvelle

    row.publication_status = "published"
    row.published_by = user.id
    row.published_at = _now()
    await record_status(
        session,
        spec,
        row,
        "pending_review",
        "published",
        user,
        requires_human=True,
        metadata={"replaced": [str(c.id) for c in conflicts]} if conflicts else None,
    )
    await flush_or_translate(session)
    return row


async def reject(
    session: AsyncSession, spec: PublishableSpec, row: Any, user: CurrentUser, reason: str
) -> Any:
    """`pending_review → draft` avec motif, par un relecteur ≠ soumetteur ; vide submitted_*."""
    if row.publication_status != "pending_review":
        raise transition_error(row, "draft")
    if row.submitted_by == user.id:
        raise AppError(
            ErrorCode.FOUR_EYES_REQUIRED,
            message="Le renvoi en brouillon doit être fait par un relecteur, pas par l'auteur.",
            details={"submitted_by": str(user.id)},
        )
    previous_submitter = row.submitted_by
    row.publication_status = "draft"
    row.submitted_by = None
    row.submitted_at = None
    await record_status(
        session,
        spec,
        row,
        "pending_review",
        "draft",
        user,
        reason=reason,
        metadata={"submitted_by": str(previous_submitter) if previous_submitter else None},
    )
    await flush_or_translate(session)
    return row


async def archive(
    session: AsyncSession,
    spec: PublishableSpec,
    row: Any,
    user: CurrentUser,
    reason: str | None = None,
) -> Any:
    """`published → archived` : retirée des lectures officielles, conservée pour l'historique."""
    if row.publication_status != "published":
        raise transition_error(row, "archived")
    row.publication_status = "archived"
    await record_status(session, spec, row, "published", "archived", user, reason=reason)
    await flush_or_translate(session)
    return row


#: Colonnes jamais copiées par `/new-version` (identité, bloc de publication, colonnes générées).
_NEVER_COPIED = frozenset(
    {
        "id",
        "publication_status",
        "validity",
        "created_by",
        "submitted_by",
        "submitted_at",
        "published_by",
        "published_at",
        "created_at",
        "updated_at",
    }
)


async def new_version(
    session: AsyncSession,
    spec: PublishableSpec,
    row: Any,
    user: CurrentUser,
    overrides: dict[str, Any] | None = None,
) -> Any:
    """Copie une ligne publiée (ou archivée) en nouveau brouillon, enfants compris."""
    if row.publication_status not in ("published", "archived"):
        raise AppError(
            ErrorCode.INVALID_STATUS_TRANSITION,
            message="Seule une version publiée ou archivée peut servir de base.",
            details={"current_status": row.publication_status, "reason": "source_not_published"},
        )
    mapper = inspect(spec.model)
    skip = _NEVER_COPIED | spec.copy_exclude
    values: dict[str, Any] = {}
    for col in mapper.column_attrs:
        column = col.columns[0]
        if col.key in skip or column.computed is not None:
            continue
        values[col.key] = getattr(row, col.key)
    values.update({k: v for k, v in (overrides or {}).items() if v is not None})
    values["created_by"] = user.id
    values["publication_status"] = "draft"
    copy = spec.model(**values)
    session.add(copy)
    await flush_or_translate(session)
    if spec.copy_children is not None:
        await spec.copy_children(session, row, copy)
        await flush_or_translate(session)
    return copy


# --- Orchestration HTTP / outils ---------------------------------------------------------------


async def load_for_update(session: AsyncSession, spec: PublishableSpec, row_id: uuid.UUID) -> Any:
    """Charge la ligne verrouillée (FOR UPDATE) ou 404."""
    row = await session.scalar(
        select(spec.model)
        .where(spec.model.id == row_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise AppError(ErrorCode.NOT_FOUND)
    return row


async def run_transition(
    session: AsyncSession,
    spec: PublishableSpec,
    row_id: uuid.UUID,
    user: CurrentUser,
    action: Action,
    *,
    if_match: str | None = None,
    if_match_required: bool = False,
    reason: str | None = None,
    replace_current: bool = False,
    overrides: dict[str, Any] | None = None,
) -> Any:
    """Exécute une action de publication de bout en bout et renvoie la ligne à jour.

    Ordre des contrôles (SA-5 §1.3) : existence et périmètre, rôle, ETag, état, 4 yeux,
    chevauchement. Tout se passe dans une `staff_transaction` (audit + commit).
    """
    handlers: dict[Action, Callable[..., Awaitable[Any]]] = {
        Action.SUBMIT: lambda r: submit(session, spec, r, user),
        Action.PUBLISH: lambda r: publish(session, spec, r, user, replace_current=replace_current),
        Action.REJECT: lambda r: reject(session, spec, r, user, reason or ""),
        Action.ARCHIVE: lambda r: archive(session, spec, r, user, reason),
        Action.NEW_VERSION: lambda r: new_version(session, spec, r, user, overrides),
    }
    if action not in handlers:
        raise ValueError(f"action non gérée par run_transition : {action}")
    async with staff_transaction(session, user):
        row = await load_for_update(session, spec, row_id)
        await authorize(session, user, action, await institution_of(session, spec, row))
        check_if_match(row, if_match, required=if_match_required)
        result = await handlers[action](row)
    await session.refresh(result)
    return result


async def get_for_staff(
    session: AsyncSession, spec: PublishableSpec, row_id: uuid.UUID, user: CurrentUser
) -> Any:
    """Lecture staff d'une ligne (tous statuts) avec contrôle du périmètre."""
    row = await session.get(spec.model, row_id, populate_existing=True)
    if row is None:
        raise AppError(ErrorCode.NOT_FOUND)
    await authorize(session, user, Action.READ, await institution_of(session, spec, row))
    return row


def same_key(*pairs: tuple[Any, Any]) -> list[ColumnElement[bool]]:
    """Construit les conditions « même clé métier » : `col IS NOT DISTINCT FROM valeur`."""
    return [col.is_not_distinct_from(value) for col, value in pairs]


__all__: Sequence[str] = [
    "LEAD_ROLES",
    "REVIEWER_ROLES",
    "STAFF_READER_ROLES",
    "TUNIS",
    "Action",
    "PublishableSpec",
    "archive",
    "authorize",
    "check_if_match",
    "compute_etag",
    "ensure_draft",
    "get_for_staff",
    "institution_of",
    "lead_institution_ids",
    "load_for_update",
    "new_version",
    "official_filter",
    "official_select",
    "programme_institution_expr",
    "programme_institution_id",
    "publish",
    "record_status",
    "reject",
    "run_transition",
    "same_key",
    "scope_filter",
    "source_ref",
    "staff_scope",
    "submit",
    "today_tunis",
    "transition_error",
    "version_number",
]
