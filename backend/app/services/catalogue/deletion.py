"""Suppression des brouillons et des matières du référentiel (SA-20, décision du 21/11).

Règle (SA-12 §0, décision de Thamer du 21/11) :
- une ligne publiable (formation, spécialité, cursus, passerelle) ne se **supprime** que tant
  qu'elle est en `draft` (jamais publiée) ; une ligne publiée s'**archive** (`POST …/archive`),
  une ligne en relecture doit d'abord être renvoyée en brouillon ;
- une matière du référentiel (sans publication) se supprime si aucune donnée ne l'utilise ;
- dans tous les cas, une ligne encore référencée (FK RESTRICT / NO ACTION) donne un 409
  `CONFLICT` explicite (`details.reason = still_referenced`, liste des tables) au lieu d'une
  erreur 500 ; les enfants propres (matières d'un cursus, prérequis) partent en cascade.

Contrôles, dans l'ordre : ligne existante (404), rôle et périmètre (403 / 404 hors périmètre,
comme la modification), If-Match facultatif mais vérifié s'il est fourni (412, SA-5 §1.6),
statut (409), références (409). Le trigger `audit_catalogue()` journalise le DELETE avec
l'auteur posé par `staff_transaction`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ErrorCode
from app.core.security import CurrentUser
from app.models import (
    AdmissionCondition,
    Bridge,
    Curriculum,
    CurriculumSubject,
    DocumentProgramme,
    EquivalenceItem,
    EquivalenceRequest,
    FeeSchedule,
    McqQuestion,
    Preregistration,
    Prerequisite,
    RecommendationItem,
    Speciality,
)
from app.services.catalogue import publication as pub
from app.services.catalogue.publication import Action, PublishableSpec, authorize
from app.services.catalogue.tx import staff_transaction


@dataclass(frozen=True)
class Reference:
    """Colonne d'une autre table qui pointe vers l'entité (FK sans cascade)."""

    column: Any
    label_fr: str

    @property
    def table(self) -> str:
        return self.column.class_.__tablename__


#: Références bloquantes par type d'entité (FK RESTRICT ou NO ACTION ; les FK CASCADE, comme
#: `curriculum_subject.curriculum_id`, ne bloquent pas et ne figurent pas ici).
REFERENCES: dict[str, tuple[Reference, ...]] = {
    "programme": (
        Reference(Speciality.programme_id, "spécialités"),
        Reference(Curriculum.programme_id, "cursus"),
        Reference(AdmissionCondition.programme_id, "conditions d'admission"),
        Reference(FeeSchedule.programme_id, "grilles de frais"),
        Reference(Bridge.source_programme_id, "passerelles (départ)"),
        Reference(Bridge.target_programme_id, "passerelles (arrivée)"),
        Reference(DocumentProgramme.programme_id, "documents"),
        Reference(McqQuestion.programme_id, "questions de QCM"),
        Reference(RecommendationItem.programme_id, "recommandations"),
        Reference(Preregistration.programme_id, "préinscriptions"),
    ),
    "speciality": (
        Reference(Curriculum.speciality_id, "cursus"),
        Reference(AdmissionCondition.speciality_id, "conditions d'admission"),
        Reference(FeeSchedule.speciality_id, "grilles de frais"),
        Reference(Bridge.source_speciality_id, "passerelles (départ)"),
        Reference(Bridge.target_speciality_id, "passerelles (arrivée)"),
        Reference(RecommendationItem.speciality_id, "recommandations"),
        Reference(Preregistration.speciality_id, "préinscriptions"),
    ),
    "curriculum": (Reference(EquivalenceRequest.target_curriculum_id, "demandes d'équivalence"),),
    "subject": (
        Reference(CurriculumSubject.subject_id, "matières de cursus"),
        Reference(Prerequisite.required_subject_id, "prérequis"),
        Reference(EquivalenceItem.ai_target_subject_id, "équivalences (proposition IA)"),
        Reference(EquivalenceItem.final_target_subject_id, "équivalences (décision)"),
    ),
    "bridge": (),
}


async def find_references(
    session: AsyncSession, entity_type: str, row_id: uuid.UUID
) -> list[dict[str, Any]]:
    """Références bloquantes (une seule requête) : `[{table, label_fr, count}]`, non nulles."""
    refs = REFERENCES.get(entity_type, ())
    if not refs:
        return []
    counts = (
        await session.execute(
            select(
                *(
                    select(func.count()).where(ref.column == row_id).scalar_subquery()
                    for ref in refs
                )
            )
        )
    ).one()
    found: dict[tuple[str, str], int] = {}
    for ref, count in zip(refs, counts, strict=True):
        if count:
            key = (ref.table, ref.label_fr)
            found[key] = found.get(key, 0) + int(count)
    return [{"table": t, "label_fr": label, "count": n} for (t, label), n in found.items()]


async def ensure_unreferenced(
    session: AsyncSession, spec: PublishableSpec, row_id: uuid.UUID
) -> None:
    """409 CONFLICT si une autre donnée utilise encore la ligne (message en français)."""
    refs = await find_references(session, spec.entity_type, row_id)
    if refs:
        used_by = ", ".join(f"{r['label_fr']} ({r['count']})" for r in refs)
        raise AppError(
            ErrorCode.CONFLICT,
            message=(
                f"Suppression impossible : cette ligne ({spec.label_fr}) est encore utilisée par "
                f"{used_by}. "
                "Supprimez d'abord ces éléments (ou archivez la ligne si elle est publiée)."
            ),
            details={"reason": "still_referenced", "referenced_by": refs},
        )


def ensure_deletable(row: Any, *, child: bool = False) -> None:
    """Seul un brouillon jamais publié se supprime ; sinon 409 INVALID_STATUS_TRANSITION avec
    l'action à utiliser (`archive` pour une ligne publiée, `reject` pour une ligne en relecture).

    Même réponse pour tous les DELETE du catalogue (SA-20 et SA-21, décision du 21/11).
    `child=True` : `row` est le **parent** d'un enfant supprimé (plan de paiement, prérequis,
    matière d'un cursus) ; un parent publié ou archivé se corrige par `new_version`."""
    current = row.publication_status
    if current == "draft":
        return
    if child:
        hint = {"pending_review": "reject"}.get(current, "new_version")
    else:
        hint = {"published": "archive", "pending_review": "reject"}.get(current)
    raise AppError(
        ErrorCode.INVALID_STATUS_TRANSITION,
        message=(
            "Seul un brouillon peut être supprimé : une ligne publiée s'archive, une ligne en "
            "relecture doit d'abord être renvoyée en brouillon."
        ),
        details={"current_status": current, "reason": "only_draft_deletable", "hint": hint},
    )


async def delete_row(
    session: AsyncSession,
    user: CurrentUser,
    spec: PublishableSpec,
    row_id: uuid.UUID,
    if_match: str | None,
    *,
    publishable: bool = True,
) -> None:
    """Supprime un brouillon (`publishable=True`) ou une matière du référentiel (`False`)."""
    async with staff_transaction(session, user):
        row = await pub.load_for_update(session, spec, row_id)
        await authorize(session, user, Action.DELETE, await pub.institution_of(session, spec, row))
        pub.check_if_match(row, if_match, required=False)
        if publishable:
            ensure_deletable(row)
        await ensure_unreferenced(session, spec, row.id)
        await session.execute(delete(spec.model).where(spec.model.id == row.id))
    session.expunge(row)


__all__ = [
    "REFERENCES",
    "Reference",
    "delete_row",
    "ensure_deletable",
    "ensure_unreferenced",
    "find_references",
]
