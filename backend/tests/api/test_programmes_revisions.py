"""Tests SA-20 D1 (validée 17/11) : révisions des entités stables publiées."""

from __future__ import annotations

import uuid

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CatalogueAuditLog, StatusHistory
from tests.api.conftest import World
from tests.api.test_programmes import add_programme, err

pytestmark = pytest.mark.db

NEW_DESC = "Texte officiel révisé (fictif)."


def rev_url(w: World, rev_id: str | None = None, path: str = "programmes", eid=None) -> str:
    base = f"/staff/catalogue/{path}/{eid or w.programme}/revisions"
    return f"{base}/{rev_id}" if rev_id else base


async def propose(api: httpx.AsyncClient, w: World, changes: dict, **kw) -> httpx.Response:
    return await api.post(
        rev_url(w, path=kw.get("path", "programmes"), eid=kw.get("eid")),
        json={"changes": changes, "reason_fr": "Mise à jour (fictive)"},
        headers=kw.get("headers") or w.h_lead_a(),
    )


async def test_revision_cycle_complet_quatre_yeux(
    api: httpx.AsyncClient, world: World, db_session: AsyncSession
):
    w = world
    await w.commit()
    resp = await propose(api, w, {"description_fr": NEW_DESC, "name_fr": "Licence révisée"})
    assert resp.status_code == 201, resp.text
    rev = resp.json()
    assert rev["status"] == "draft" and rev["entity_type"] == "programme"
    assert rev["current"] == {"description_fr": None, "name_fr": "Licence informatique (fictive)"}
    rid, etag = rev["id"], resp.headers["ETag"]

    # Lecture publique inchangée tant que la révision n'est pas publiée.
    public = (await api.get(f"/catalogue/programmes/{w.programme}")).json()
    assert public["name"] == "Licence informatique (fictive)" and public["description"] is None

    assert (await api.post(f"{rev_url(w, rid)}/submit", headers=w.h_lead_a())).status_code == 428
    sub = await api.post(f"{rev_url(w, rid)}/submit", headers={**w.h_lead_a(), "If-Match": etag})
    assert sub.status_code == 200 and sub.json()["status"] == "pending_review"
    etag = sub.headers["ETag"]
    public = (await api.get(f"/catalogue/programmes/{w.programme}")).json()
    assert public["name"] == "Licence informatique (fictive)"

    url = f"{rev_url(w, rid)}/publish"
    resp = await api.post(url, headers={**w.h_lead_a(), "If-Match": etag})
    assert resp.status_code == 403 and err(resp) == "FOUR_EYES_REQUIRED"
    resp = await api.post(url, headers={**w.h_admin(), "If-Match": etag})
    assert resp.status_code == 403 and err(resp) == "FORBIDDEN"
    resp = await api.post(url, headers={**w.h_isb(), "If-Match": etag})
    assert resp.status_code == 404
    resp = await api.post(url, headers={**w.h_lead_b(), "If-Match": 'W/"perime"'})
    assert resp.status_code == 412
    resp = await api.post(url, headers={**w.h_lead_b(), "If-Match": etag})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "published" and body["published_by"] == str(w.lead_b)
    assert body["current"]["description_fr"] == NEW_DESC

    public = (await api.get(f"/catalogue/programmes/{w.programme}")).json()
    assert public["name"] == "Licence révisée" and public["description"] == NEW_DESC
    staff = (
        await api.get(f"/staff/catalogue/programmes/{w.programme}", headers=w.h_lead_a())
    ).json()
    assert staff["publication_status"] == "published"

    # Re-publier : transition invalide.
    resp = await api.post(url, headers={**w.h_direction(), "If-Match": resp.headers["ETag"]})
    assert resp.status_code == 409 and err(resp) == "INVALID_STATUS_TRANSITION"

    history = (
        await db_session.scalars(
            select(StatusHistory).where(StatusHistory.entity_id == w.programme)
        )
    ).all()
    revs = [h for h in history if h.metadata_.get("kind") == "revision"]
    assert {(h.from_status, h.to_status, h.requires_human) for h in revs} == {
        ("published", "pending_review", False),
        ("pending_review", "published", True),
    }
    audit = (
        await db_session.scalars(
            select(CatalogueAuditLog).where(
                CatalogueAuditLog.row_id == w.programme, CatalogueAuditLog.action == "update"
            )
        )
    ).all()
    assert len(audit) == 1 and audit[0].actor_id == w.lead_b
    assert set(audit[0].changed_fields) == {"description_fr", "name_fr"}

    lst = await api.get(rev_url(w), headers=w.h_direction())
    assert [r["id"] for r in lst.json()] == [rid]


async def test_revision_validations_et_autorisations(api: httpx.AsyncClient, world: World):
    w = world
    draft = await add_programme(w, f"DR-{w.tag}", "Licence brouillon", status="draft")
    await w.commit()
    resp = await propose(api, w, {"name_fr": "Nouveau"}, eid=draft.id)
    assert resp.status_code == 409 and err(resp) == "INVALID_STATUS_TRANSITION"
    assert resp.json()["error"]["details"]["hint"] == "patch"
    for changes, issue in (
        ({"valid_to": "2030-09-01"}, "not_revisable"),
        ({"inconnu": 1}, "extra_forbidden"),
        ({"name_fr": None}, "null_not_allowed"),
        ({"duration_years": 9}, "less_than_equal"),
    ):
        resp = await propose(api, w, changes)
        assert resp.status_code == 422, changes
        assert resp.json()["error"]["details"][0]["issue"] == issue
    resp = await api.post(rev_url(w), json={"changes": {}}, headers=w.h_lead_a())
    assert resp.status_code == 422
    for h, code in ((w.h_direction(), 403), (w.h_candidate(), 403), (w.h_isb(), 404)):
        resp = await propose(api, w, {"name_fr": "Interdit"}, headers=h)
        assert resp.status_code == code, h
    assert (await propose(api, w, {"name_fr": "Première"})).status_code == 201
    resp = await propose(api, w, {"name_fr": "Seconde"})
    assert resp.status_code == 409 and err(resp) == "CONFLICT"
    assert (await api.get(rev_url(w, str(uuid.uuid4())), headers=w.h_lead_a())).status_code == 404


async def test_rejet_abandonne_la_revision(api: httpx.AsyncClient, world: World):
    w = world
    await w.commit()
    created = await propose(api, w, {"description_fr": NEW_DESC})
    rid = created.json()["id"]
    sub = await api.post(
        f"{rev_url(w, rid)}/submit", headers={**w.h_lead_a(), "If-Match": created.headers["ETag"]}
    )
    url = f"{rev_url(w, rid)}/reject"
    assert (await api.post(url, json={}, headers=w.h_lead_b())).status_code == 422
    resp = await api.post(url, json={"reason": "Texte à revoir."}, headers=w.h_lead_a())
    assert resp.status_code == 403 and err(resp) == "FOUR_EYES_REQUIRED"
    resp = await api.post(url, json={"reason": "Texte à revoir."}, headers=w.h_direction())
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected" and resp.json()["rejection_reason"]
    public = (await api.get(f"/catalogue/programmes/{w.programme}")).json()
    assert public["description"] is None
    resp = await api.post(
        f"{rev_url(w, rid)}/publish", headers={**w.h_lead_b(), "If-Match": sub.headers["ETag"]}
    )
    assert resp.status_code == 412  # ETag périmé : la révision a changé (rejetée)

    # Après rejet, une nouvelle révision est possible ; l'auteur peut abandonner son brouillon.
    again = await propose(api, w, {"description_fr": "Autre texte (fictif)."})
    assert again.status_code == 201
    resp = await api.post(
        f"{rev_url(w, again.json()['id'])}/reject",
        json={"reason": "Abandon par l'auteur."},
        headers=w.h_lead_a(),
    )
    assert resp.status_code == 200 and resp.json()["status"] == "rejected"


async def test_revision_code_en_conflit_a_la_publication(api: httpx.AsyncClient, world: World):
    w = world
    other = await add_programme(w, f"OTH-{w.tag}", "Autre licence")
    await w.commit()
    created = await propose(api, w, {"code": other.code})
    rid = created.json()["id"]
    sub = await api.post(
        f"{rev_url(w, rid)}/submit", headers={**w.h_lead_a(), "If-Match": created.headers["ETag"]}
    )
    resp = await api.post(
        f"{rev_url(w, rid)}/publish", headers={**w.h_lead_b(), "If-Match": sub.headers["ETag"]}
    )
    assert resp.status_code == 409 and err(resp) == "CONFLICT"
    got = await api.get(rev_url(w, rid), headers=w.h_lead_a())
    assert got.json()["status"] == "pending_review"


async def test_revision_specialite_et_etablissement(api: httpx.AsyncClient, world: World):
    w = world
    await w.commit()
    created = await propose(
        api, w, {"name_fr": "Génie logiciel et IA"}, path="specialities", eid=w.speciality
    )
    assert created.status_code == 201, created.text
    url = rev_url(w, created.json()["id"], path="specialities", eid=w.speciality)
    sub = await api.post(
        f"{url}/submit", headers={**w.h_lead_a(), "If-Match": created.headers["ETag"]}
    )
    resp = await api.post(
        f"{url}/publish", headers={**w.h_direction(), "If-Match": sub.headers["ETag"]}
    )
    assert resp.status_code == 200, resp.text
    spec = (await api.get(f"/catalogue/specialities/{w.speciality}")).json()
    assert spec["name"] == "Génie logiciel et IA"

    created = await propose(
        api, w, {"website_url": "https://exemple.invalid"}, path="institutions", eid=w.iit
    )
    assert created.status_code == 201, created.text
    url = rev_url(w, created.json()["id"], path="institutions", eid=w.iit)
    sub = await api.post(
        f"{url}/submit", headers={**w.h_lead_a(), "If-Match": created.headers["ETag"]}
    )
    resp = await api.post(
        f"{url}/publish", headers={**w.h_lead_b(), "If-Match": sub.headers["ETag"]}
    )
    assert resp.status_code == 200
    insts = (await api.get("/catalogue/institutions")).json()["items"]
    assert (
        next(i for i in insts if i["id"] == str(w.iit))["website_url"] == "https://exemple.invalid"
    )
