"""Tests SA-20 : suppression des brouillons et des matières (décision du 21/11).

Règles vérifiées : DELETE seulement en `draft` (409 sinon, avec l'action à utiliser), 409
`CONFLICT` explicite si la ligne est encore utilisée, cascade des enfants propres d'un cursus,
rôles et périmètre de la modification (403 / 404), If-Match facultatif mais vérifié, 404 sur
une ligne inexistante, journal d'audit du DELETE.

Lancement : `flock <verrou> ~/.local/bin/uv run pytest tests/api/test_suppression_catalogue.py`
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import func, select

from app.core.errors import ErrorCode
from app.models import (
    CatalogueAuditLog,
    CurriculumSubject,
    PaymentPlan,
    Prerequisite,
    Speciality,
    Subject,
)
from app.services.catalogue.tx import translate_db_error
from tests.api.conftest import World, headers
from tests.api.test_curricula import add_subject, curriculum_body, line_body, published_curriculum
from tests.api.test_programmes import add_bridge, add_programme, err, new_programme_body

pytestmark = pytest.mark.db

STAFF = "/staff/catalogue"


async def draft_programme(api: httpx.AsyncClient, w: World) -> str:
    resp = await api.post(f"{STAFF}/programmes", json=new_programme_body(w), headers=w.h_lead_a())
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def count(session, model, *conds) -> int:
    return await session.scalar(select(func.count()).select_from(model).where(*conds))


# ============ Formations ============


async def test_formation_brouillon_supprimee_et_journalisee(
    api: httpx.AsyncClient, world: World, db_session
):
    w = world
    await w.commit()
    pid = await draft_programme(api, w)
    url = f"{STAFF}/programmes/{pid}"

    resp = await api.delete(url, headers=w.h_lead_a())
    assert resp.status_code == 204 and resp.content == b""
    assert (await api.get(url, headers=w.h_lead_a())).status_code == 404
    # Rejouer la suppression : la ligne n'existe plus.
    again = await api.delete(url, headers=w.h_lead_a())
    assert again.status_code == 404 and err(again) == "NOT_FOUND"

    logs = (
        await db_session.execute(
            select(CatalogueAuditLog.action, CatalogueAuditLog.actor_id).where(
                CatalogueAuditLog.row_id == uuid.UUID(pid)
            )
        )
    ).all()
    assert {(a, actor) for a, actor in logs} == {("insert", w.lead_a), ("delete", w.lead_a)}


async def test_formation_publiee_ou_en_relecture_non_supprimable(
    api: httpx.AsyncClient, world: World
):
    w = world
    pending = await add_programme(w, f"PEN-{w.tag}", "En relecture", status="pending_review")
    archived = await add_programme(w, f"ARC-{w.tag}", "Archivée", status="archived")
    await w.commit()

    resp = await api.delete(f"{STAFF}/programmes/{w.programme}", headers=w.h_lead_a())
    assert resp.status_code == 409 and err(resp) == "INVALID_STATUS_TRANSITION"
    details = resp.json()["error"]["details"]
    assert details == {
        "current_status": "published",
        "reason": "only_draft_deletable",
        "hint": "archive",
    }
    resp = await api.delete(f"{STAFF}/programmes/{pending.id}", headers=w.h_lead_a())
    assert resp.status_code == 409
    assert resp.json()["error"]["details"]["hint"] == "reject"
    resp = await api.delete(f"{STAFF}/programmes/{archived.id}", headers=w.h_lead_a())
    assert resp.status_code == 409
    assert resp.json()["error"]["details"]["hint"] is None


async def test_formation_utilisee_par_une_specialite(api: httpx.AsyncClient, world: World):
    w = world
    await w.commit()
    pid = await draft_programme(api, w)
    spec = await api.post(
        f"{STAFF}/specialities",
        json={"programme_id": pid, "code": "IA", "name_fr": "Intelligence artificielle"},
        headers=w.h_lead_a(),
    )
    assert spec.status_code == 201, spec.text

    resp = await api.delete(f"{STAFF}/programmes/{pid}", headers=w.h_lead_a())
    assert resp.status_code == 409 and err(resp) == "CONFLICT"
    error = resp.json()["error"]
    assert error["details"]["reason"] == "still_referenced"
    assert error["details"]["referenced_by"] == [
        {"table": "speciality", "label_fr": "spécialités", "count": 1}
    ]
    assert "spécialités (1)" in error["message"]

    # Supprimer d'abord la spécialité (brouillon), puis la formation.
    resp = await api.delete(f"{STAFF}/specialities/{spec.json()['id']}", headers=w.h_lead_a())
    assert resp.status_code == 204
    assert (await api.delete(f"{STAFF}/programmes/{pid}", headers=w.h_lead_a())).status_code == 204


async def test_roles_perimetre_et_if_match(api: httpx.AsyncClient, world: World):
    w = world
    await w.commit()
    pid = await draft_programme(api, w)
    url = f"{STAFF}/programmes/{pid}"

    assert (await api.delete(url)).status_code == 401
    for h in (w.h_direction(), w.h_admin(), w.h_candidate()):
        resp = await api.delete(url, headers=h)
        assert resp.status_code == 403 and err(resp) == "FORBIDDEN"
    resp = await api.delete(url, headers=headers("interview_lead", user=uuid.uuid4()))
    assert resp.status_code == 403
    # Autre établissement : 404 (règle S, la ligne n'est pas révélée).
    resp = await api.delete(url, headers=w.h_isb())
    assert resp.status_code == 404 and err(resp) == "NOT_FOUND"
    # If-Match facultatif, mais vérifié s'il est fourni.
    resp = await api.delete(url, headers={**w.h_lead_a(), "If-Match": 'W/"perime"'})
    assert resp.status_code == 412 and err(resp) == "PRECONDITION_FAILED"
    etag = (await api.get(url, headers=w.h_lead_a())).headers["ETag"]
    # Un autre responsable du même établissement peut supprimer le brouillon.
    resp = await api.delete(url, headers={**w.h_lead_b(), "If-Match": etag})
    assert resp.status_code == 204
    # Inexistant : 404.
    resp = await api.delete(f"{STAFF}/programmes/{uuid.uuid4()}", headers=w.h_lead_a())
    assert resp.status_code == 404


# ============ Spécialités et passerelles ============


async def test_specialite_brouillon_et_publiee(api: httpx.AsyncClient, world: World):
    w = world
    draft = Speciality(
        programme_id=w.programme, code="DS", name_fr="Science des données", **w.publication("draft")
    )
    w.session.add(draft)
    await w.session.flush()
    await w.commit()

    # Publiée (et utilisée par aucun cursus) : 409 statut, l'archivage reste la voie.
    resp = await api.delete(f"{STAFF}/specialities/{w.speciality}", headers=w.h_lead_a())
    assert resp.status_code == 409 and err(resp) == "INVALID_STATUS_TRANSITION"
    assert (
        await api.delete(f"{STAFF}/specialities/{draft.id}", headers=w.h_isb())
    ).status_code == 404
    resp = await api.delete(f"{STAFF}/specialities/{draft.id}", headers=w.h_lead_a())
    assert resp.status_code == 204


async def test_specialite_brouillon_utilisee_par_un_cursus(api: httpx.AsyncClient, world: World):
    w = world
    draft = Speciality(
        programme_id=w.programme, code="RS", name_fr="Réseaux", **w.publication("draft")
    )
    w.session.add(draft)
    await w.session.flush()
    await published_curriculum(w, speciality=draft.id, status="draft", label="v2031")
    await w.commit()
    resp = await api.delete(f"{STAFF}/specialities/{draft.id}", headers=w.h_lead_a())
    assert resp.status_code == 409 and err(resp) == "CONFLICT"
    assert resp.json()["error"]["details"]["referenced_by"][0]["table"] == "curriculum"


async def test_passerelle_brouillon(api: httpx.AsyncClient, world: World):
    w = world
    draft = await add_bridge(w, w.programme, w.isb_programme, status="draft")
    published = await add_bridge(w, w.isb_programme, w.programme)
    await w.commit()
    resp = await api.delete(f"{STAFF}/bridges/{published.id}", headers=w.h_isb())
    assert resp.status_code == 409 and err(resp) == "INVALID_STATUS_TRANSITION"
    assert (
        await api.delete(f"{STAFF}/bridges/{draft.id}", headers=w.h_direction())
    ).status_code == 403
    assert (
        await api.delete(f"{STAFF}/bridges/{draft.id}", headers=w.h_lead_a())
    ).status_code == 204


# ============ Cursus ============


async def test_cursus_brouillon_supprime_avec_ses_matieres(
    api: httpx.AsyncClient, world: World, db_session
):
    w = world
    published, _ = await published_curriculum(w)
    draft, (s1, s2) = await published_curriculum(w, status="draft", label="v2030")
    await w.commit()

    resp = await api.delete(f"{STAFF}/curricula/{published.id}", headers=w.h_lead_a())
    assert resp.status_code == 409 and err(resp) == "INVALID_STATUS_TRANSITION"

    resp = await api.delete(f"{STAFF}/curricula/{draft.id}", headers=w.h_lead_a())
    assert resp.status_code == 204
    # Enfants propres supprimés en cascade ; les matières du référentiel restent.
    assert (
        await count(db_session, CurriculumSubject, CurriculumSubject.curriculum_id == draft.id) == 0
    )
    assert await count(db_session, Prerequisite, Prerequisite.curriculum_id == draft.id) == 0
    assert await count(db_session, Subject, Subject.id.in_([s1.id, s2.id])) == 2


async def test_cursus_cree_par_api_puis_supprime(api: httpx.AsyncClient, world: World):
    w = world
    subj = await add_subject(w, f"M{w.tag}", "Mathématiques")
    await w.commit()
    h = w.h_lead_a()
    created = await api.post(f"{STAFF}/curricula", json=curriculum_body(w), headers=h)
    assert created.status_code == 201, created.text
    cid = created.json()["id"]
    line = await api.post(
        f"{STAFF}/curricula/{cid}/subjects",
        json=line_body(subj.id),
        headers={**h, "If-Match": created.headers["ETag"]},
    )
    assert line.status_code == 201, line.text
    # Rôle interdit puis suppression par l'auteur.
    assert (await api.delete(f"{STAFF}/curricula/{cid}", headers=w.h_admin())).status_code == 403
    assert (await api.delete(f"{STAFF}/curricula/{cid}", headers=h)).status_code == 204
    assert (await api.get(f"{STAFF}/curricula/{cid}", headers=h)).status_code == 404


# ============ Matières du référentiel ============


async def test_matiere_inutilisee_ou_utilisee(api: httpx.AsyncClient, world: World):
    w = world
    _, (used_by_line, _) = await published_curriculum(w, status="draft", label="v2032")
    free = await add_subject(w, f"F{w.tag}", "Matière libre")
    isb_subject = await add_subject(w, f"I{w.tag}", "Matière ISB", institution=w.isb)
    await w.commit()

    resp = await api.delete(f"{STAFF}/subjects/{used_by_line.id}", headers=w.h_lead_a())
    assert resp.status_code == 409 and err(resp) == "CONFLICT"
    refs = resp.json()["error"]["details"]["referenced_by"]
    # Matière d'une ligne de cursus et matière exigée par un prérequis.
    assert {r["table"] for r in refs} == {"curriculum_subject", "prerequisite"}

    assert (
        await api.delete(f"{STAFF}/subjects/{free.id}", headers=w.h_direction())
    ).status_code == 403
    assert (
        await api.delete(f"{STAFF}/subjects/{isb_subject.id}", headers=w.h_lead_a())
    ).status_code == 404
    resp = await api.delete(f"{STAFF}/subjects/{free.id}", headers=w.h_lead_a())
    assert resp.status_code == 204
    assert (await api.get(f"{STAFF}/subjects/{free.id}", headers=w.h_lead_a())).status_code == 404
    assert (
        await api.delete(f"{STAFF}/subjects/{uuid.uuid4()}", headers=w.h_lead_a())
    ).status_code == 404


# ============ Conditions d'admission (route SA-21 existante) ============


async def test_condition_admission_brouillon_seulement(api: httpx.AsyncClient, world: World):
    w = world
    published = await w.condition("2026-2027", "published")
    draft = await w.condition("2027-2028", "draft", valid_from="2027-03-01")
    await w.commit()
    url = f"{STAFF}/admission-conditions"
    resp = await api.delete(f"{url}/{published.id}", headers=w.h_lead_a())
    assert resp.status_code == 409 and err(resp) == "INVALID_STATUS_TRANSITION"
    assert resp.json()["error"]["details"]["reason"] == "only_draft_deletable"
    assert resp.json()["error"]["details"]["hint"] == "archive"
    assert (await api.delete(f"{url}/{draft.id}", headers=w.h_direction())).status_code == 403
    assert (await api.delete(f"{url}/{draft.id}", headers=w.h_isb())).status_code == 404
    assert (await api.delete(f"{url}/{draft.id}", headers=w.h_lead_a())).status_code == 204
    assert (await api.delete(f"{url}/{draft.id}", headers=w.h_lead_a())).status_code == 404


# ============ Réponse commune SA-20 / SA-21 (décision du 21/11) ============


async def test_meme_refus_pour_tous_les_delete(api: httpx.AsyncClient, world: World, db_session):
    """Formations, frais, conditions, plans de paiement, prérequis et matières d'un cursus :
    même code, même message, même `reason` ; le `hint` dit quoi faire."""
    w = world
    fee_pub = await w.fee("2026-2027", "published")
    fee_pending = await w.fee("2027-2028", "pending_review", valid_from="2027-03-01")
    cond_pub = await w.condition("2026-2027", "published")
    cur, _ = await published_curriculum(w)
    await w.commit()
    plan_id = await db_session.scalar(
        select(PaymentPlan.id).where(PaymentPlan.fee_schedule_id == fee_pub.id)
    )
    prereq_id = await db_session.scalar(
        select(Prerequisite.id).where(Prerequisite.curriculum_id == cur.id)
    )
    line_id = await db_session.scalar(
        select(CurriculumSubject.id).where(CurriculumSubject.curriculum_id == cur.id)
    )
    cases = {
        f"{STAFF}/programmes/{w.programme}": "archive",
        f"{STAFF}/fee-schedules/{fee_pub.id}": "archive",
        f"{STAFF}/fee-schedules/{fee_pending.id}": "reject",
        f"{STAFF}/admission-conditions/{cond_pub.id}": "archive",
        # Enfants d'un parent publié : on corrige par une nouvelle version du parent.
        f"{STAFF}/payment-plans/{plan_id}": "new_version",
        f"{STAFF}/prerequisites/{prereq_id}": "new_version",
        f"{STAFF}/curricula/{cur.id}/subjects/{line_id}": "new_version",
    }
    # Matière d'un cursus : If-Match du cursus obligatoire (SA-20 D7, inchangé).
    cur_etag = (await api.get(f"{STAFF}/curricula/{cur.id}", headers=w.h_lead_a())).headers["ETag"]
    messages = set()
    for url, hint in cases.items():
        h = w.h_lead_a()
        if "/subjects/" in url:
            h = {**h, "If-Match": cur_etag}
        resp = await api.delete(url, headers=h)
        assert resp.status_code == 409, (url, resp.text)
        error = resp.json()["error"]
        assert error["code"] == "INVALID_STATUS_TRANSITION", url
        assert error["details"]["reason"] == "only_draft_deletable", url
        assert error["details"]["hint"] == hint, url
        messages.add(error["message"])
    assert len(messages) == 1


async def test_enfants_supprimables_si_parent_brouillon(
    api: httpx.AsyncClient, world: World, db_session
):
    """Le parent en brouillon : plan de paiement et prérequis se suppriment (204)."""
    w = world
    fee = await w.fee("2027-2028", "draft", valid_from="2027-03-01")
    cur, _ = await published_curriculum(w, status="draft", label="v2033")
    await w.commit()
    plan_id = await db_session.scalar(
        select(PaymentPlan.id).where(PaymentPlan.fee_schedule_id == fee.id)
    )
    prereq_id = await db_session.scalar(
        select(Prerequisite.id).where(Prerequisite.curriculum_id == cur.id)
    )
    resp = await api.delete(f"{STAFF}/payment-plans/{plan_id}", headers=w.h_lead_a())
    assert resp.status_code == 204, resp.text
    resp = await api.delete(f"{STAFF}/prerequisites/{prereq_id}", headers=w.h_lead_a())
    assert resp.status_code == 204, resp.text


# ============ Filet : FK violée à la suppression (concurrence) ============


def test_fk_a_la_suppression_traduite_en_conflit():
    """Si une référence apparaît entre le contrôle et le DELETE, la FK PostgreSQL bloque ;
    l'erreur asyncpg (« still referenced » dans le détail) devient 409 CONFLICT, pas 500."""
    cause = SimpleNamespace(
        sqlstate="23503",
        constraint_name="fk_recommendation_item_programme_id",
        table_name="programme",
        column_name=None,
        message='update or delete on table "programme" violates foreign key constraint '
        '"fk_recommendation_item_programme_id" on table "recommendation_item"',
        detail='Key (id)=(…) is still referenced from table "recommendation_item".',
    )
    exc = SimpleNamespace(orig=SimpleNamespace(__cause__=cause))
    error = translate_db_error(exc)  # type: ignore[arg-type]
    assert error is not None and error.code == ErrorCode.CONFLICT
    assert error.details["reason"] == "still_referenced"
