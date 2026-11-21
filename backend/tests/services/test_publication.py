"""Noyau partagé de publication (SA-21) : workflow 4 yeux, périmètre, ETag, erreurs SQL.

Testé sur `fee_schedule` (spécification `FEE_SPEC`) ; le même code sert à SA-20.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select, text

from app.core.errors import AppError, ErrorCode
from app.core.security import CurrentUser, Role
from app.models import CatalogueAuditLog, FeeSchedule, Institution, StatusHistory
from app.services.catalogue import publication as pub
from app.services.catalogue.fees import FEE_SPEC, load_plans
from app.services.catalogue.tx import staff_transaction, translate_db_error
from tests.api.conftest import World

pytestmark = pytest.mark.db


def lead(w: World, who: str = "a") -> CurrentUser:
    uid = w.lead_a if who == "a" else w.lead_b
    return CurrentUser(id=uid, roles=frozenset({Role.IIT_ACADEMIC_LEAD}), institution_id=w.iit)


def direction(w: World) -> CurrentUser:
    return CurrentUser(id=w.direction, roles=frozenset({Role.DIRECTION}))


def admin(w: World) -> CurrentUser:
    return CurrentUser(id=w.admin, roles=frozenset({Role.PLATFORM_ADMIN}))


async def _draft(w: World, **kw) -> FeeSchedule:
    row = await w.fee(status="draft", **kw)
    await w.commit()
    return row


async def test_cycle_complet_et_journaux(world: World, db_session):
    row = await _draft(world, academic_year="2028-2029")
    s = db_session
    await pub.run_transition(s, FEE_SPEC, row.id, lead(world, "a"), pub.Action.SUBMIT)
    assert row.publication_status == "pending_review"
    assert row.submitted_by == world.lead_a

    await pub.run_transition(s, FEE_SPEC, row.id, lead(world, "b"), pub.Action.PUBLISH)
    assert row.publication_status == "published"
    assert row.published_by == world.lead_b

    await pub.run_transition(
        s, FEE_SPEC, row.id, direction(world), pub.Action.ARCHIVE, reason="Retirée"
    )
    assert row.publication_status == "archived"

    history = list(
        await s.scalars(
            select(StatusHistory)
            .where(StatusHistory.entity_id == row.id)
            .order_by(StatusHistory.created_at, StatusHistory.to_status.desc())
        )
    )
    transitions = {(h.from_status, h.to_status, h.requires_human) for h in history}
    assert transitions == {
        ("draft", "pending_review", False),
        ("pending_review", "published", True),
        ("published", "archived", False),
    }
    audit = list(
        await s.scalars(
            select(CatalogueAuditLog).where(
                CatalogueAuditLog.row_id == row.id,
                CatalogueAuditLog.action.in_(("submit", "publish", "archive")),
            )
        )
    )
    actors = {a.action: a.actor_id for a in audit}
    assert actors == {
        "submit": world.lead_a,
        "publish": world.lead_b,
        "archive": world.direction,
    }


async def test_quatre_yeux_meme_personne(world: World, db_session):
    rid = (await _draft(world, academic_year="2028-2029")).id
    await pub.run_transition(db_session, FEE_SPEC, rid, lead(world), pub.Action.SUBMIT)
    with pytest.raises(AppError) as info:
        await pub.run_transition(db_session, FEE_SPEC, rid, lead(world), pub.Action.PUBLISH)
    assert info.value.code == ErrorCode.FOUR_EYES_REQUIRED
    with pytest.raises(AppError) as info:
        await pub.run_transition(
            db_session, FEE_SPEC, rid, lead(world), pub.Action.REJECT, reason="Erreur"
        )
    assert info.value.code == ErrorCode.FOUR_EYES_REQUIRED


async def test_admin_ne_publie_jamais(world: World, db_session):
    row = await _draft(world, academic_year="2028-2029")
    await pub.run_transition(db_session, FEE_SPEC, row.id, lead(world), pub.Action.SUBMIT)
    with pytest.raises(AppError) as info:
        await pub.run_transition(db_session, FEE_SPEC, row.id, admin(world), pub.Action.PUBLISH)
    assert info.value.code == ErrorCode.FORBIDDEN


async def test_rejet_vide_soumission(world: World, db_session):
    row = await _draft(world, academic_year="2028-2029")
    await pub.run_transition(db_session, FEE_SPEC, row.id, lead(world, "a"), pub.Action.SUBMIT)
    await pub.run_transition(
        db_session, FEE_SPEC, row.id, lead(world, "b"), pub.Action.REJECT, reason="À revoir"
    )
    assert row.publication_status == "draft"
    assert row.submitted_by is None and row.submitted_at is None


async def test_transition_invalide(world: World, db_session):
    row = await _draft(world, academic_year="2028-2029")
    with pytest.raises(AppError) as info:
        await pub.run_transition(db_session, FEE_SPEC, row.id, lead(world, "b"), pub.Action.PUBLISH)
    assert info.value.code == ErrorCode.INVALID_STATUS_TRANSITION
    assert info.value.details["current_status"] == "draft"
    assert info.value.details["allowed"] == ["pending_review"]


async def test_soumission_sans_valid_from(world: World, db_session):
    row = await _draft(world, academic_year="2028-2029", valid_from=None)
    with pytest.raises(AppError) as info:
        await pub.run_transition(db_session, FEE_SPEC, row.id, lead(world), pub.Action.SUBMIT)
    assert info.value.code == ErrorCode.VALIDATION_ERROR
    assert info.value.details == [{"field": "valid_from", "issue": "required"}]


async def test_chevauchement_puis_remplacement(world: World, db_session):
    old = await world.fee("2028-2029", "published", valid_from="2028-03-01")
    new = await world.fee("2028-2029", "pending_review", valid_from="2028-06-01", tuition="7000")
    old_id, new_id = old.id, new.id
    await world.commit()
    with pytest.raises(AppError) as info:
        await pub.run_transition(db_session, FEE_SPEC, new_id, lead(world, "b"), pub.Action.PUBLISH)
    assert info.value.code == ErrorCode.VALIDITY_OVERLAP
    assert info.value.details["conflicting"][0]["id"] == str(old_id)

    new = await pub.run_transition(
        db_session, FEE_SPEC, new_id, lead(world, "b"), pub.Action.PUBLISH, replace_current=True
    )
    old = await db_session.get(FeeSchedule, old_id, populate_existing=True)
    assert new.publication_status == "published"
    assert old.publication_status == "published"
    assert old.valid_to == date(2028, 6, 1)  # raccourcie, pas réécrite
    assert await pub.version_number(db_session, FEE_SPEC, old) == 1
    assert await pub.version_number(db_session, FEE_SPEC, new) == 2


async def test_remplacement_meme_date_archive(world: World, db_session):
    old = await world.fee("2028-2029", "published", valid_from="2028-03-01")
    new = await world.fee("2028-2029", "pending_review", valid_from="2028-03-01")
    await world.commit()
    await pub.run_transition(
        db_session, FEE_SPEC, new.id, direction(world), pub.Action.PUBLISH, replace_current=True
    )
    await db_session.refresh(old)
    assert old.publication_status == "archived"


async def test_contrainte_exclusion_traduite(world: World, db_session):
    """Filet de sécurité : la base refuse même si le service est contourné."""
    await world.fee("2028-2029", "published", valid_from="2028-03-01")
    await world.commit()
    with pytest.raises(AppError) as info:
        async with staff_transaction(db_session, lead(world, "b")):
            await world.fee("2028-2029", "published", valid_from="2028-05-01", plans=False)
    assert info.value.code == ErrorCode.VALIDITY_OVERLAP
    assert info.value.details["constraint"] == "ex_fee_schedule_one_published"


async def test_version_publiee_figee(world: World, db_session):
    row = await world.fee("2028-2029", "published", plans=False)
    await world.commit()
    with pytest.raises(AppError) as info:
        async with staff_transaction(db_session, lead(world, "a")):
            await db_session.execute(
                text("UPDATE fee_schedule SET annual_tuition_fee = 1 WHERE id = :id"),
                {"id": row.id},
            )
    assert info.value.code == ErrorCode.INVALID_STATUS_TRANSITION
    assert info.value.details["reason"] == "published_version_frozen"


async def test_four_eyes_base_traduit(world: World, db_session):
    with pytest.raises(AppError) as info:
        async with staff_transaction(db_session, lead(world, "a")):
            await world.fee(
                "2028-2029",
                "published",
                plans=False,
                published_by=world.lead_a,
                published_at=datetime(2026, 2, 2, tzinfo=UTC),
            )
    assert info.value.code == ErrorCode.FOUR_EYES_REQUIRED


async def test_if_match(world: World, db_session):
    row = await _draft(world, academic_year="2028-2029")
    with pytest.raises(AppError) as info:
        pub.check_if_match(row, None, required=True)  # pas d'accès base : row reste chargé
    assert info.value.code == ErrorCode.PRECONDITION_REQUIRED
    with pytest.raises(AppError) as info:
        pub.check_if_match(row, 'W/"perime"', required=True)
    assert info.value.code == ErrorCode.PRECONDITION_FAILED
    pub.check_if_match(row, pub.compute_etag(row), required=True)
    etag = pub.compute_etag(row)
    row.annual_tuition_fee = Decimal("1")
    assert pub.compute_etag(row) != etag


async def test_perimetre(world: World, db_session):
    row = await _draft(world, academic_year="2028-2029")
    isb = CurrentUser(
        id=world.isb_lead, roles=frozenset({Role.ISB_ACADEMIC_LEAD}), institution_id=world.isb
    )
    with pytest.raises(AppError) as info:
        await pub.get_for_staff(db_session, FEE_SPEC, row.id, isb)
    assert info.value.code == ErrorCode.NOT_FOUND
    # La direction et l'admin lisent tout.
    await pub.get_for_staff(db_session, FEE_SPEC, row.id, direction(world))
    await pub.get_for_staff(db_session, FEE_SPEC, row.id, admin(world))


async def test_perimetre_par_code_de_role(world: World, db_session):
    """Sans institution_id : le rôle iit_academic_lead vise l'institution de code IIT."""
    iit = await db_session.scalar(select(Institution).where(Institution.code == "IIT"))
    if iit is None:
        iit = Institution(code="IIT", name_fr="IIT (fictif)", city="Sfax", **world._published())
        db_session.add(iit)
        await db_session.flush()
    user = CurrentUser(id=world.lead_a, roles=frozenset({Role.IIT_ACADEMIC_LEAD}))
    assert await pub.lead_institution_ids(db_session, user) == {iit.id}


async def test_nouvelle_version_copie_les_plans(world: World, db_session):
    row = await world.fee("2028-2029", "published")
    await world.commit()
    copy = await pub.run_transition(
        db_session,
        FEE_SPEC,
        row.id,
        lead(world, "a"),
        pub.Action.NEW_VERSION,
        overrides={"academic_year": "2029-2030"},
    )
    assert copy.id != row.id
    assert copy.publication_status == "draft"
    assert copy.academic_year == "2029-2030"
    assert copy.created_by == world.lead_a
    assert copy.annual_total == row.annual_total
    plans = await load_plans(db_session, [copy.id])
    assert len(plans[copy.id]) == 1
    assert len(plans[copy.id][0][1]) == 2


async def test_traduction_inconnue_renvoie_none():
    class FakeError(Exception):
        sqlstate = "40001"

    exc = Exception()
    exc.orig = FakeError()  # type: ignore[attr-defined]
    assert translate_db_error(exc) is None


def test_most_specific():
    rows = [
        {"id": 1, "spec": None, "year": None},
        {"id": 2, "spec": uuid.uuid4(), "year": None},
        {"id": 3, "spec": None, "year": 1},
    ]
    best = pub.most_specific(
        rows,
        bucket=lambda r: 0,
        specificity=lambda r: (r["spec"] is not None, r["year"] is not None),
    )
    assert [r["id"] for r in best] == [2]
