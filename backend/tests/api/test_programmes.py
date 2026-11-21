"""Tests SA-20 : formations, spécialités, matières, passerelles (API publique et staff).

Base réelle db-test, une transaction annulée par test (fixtures `tests/api/conftest.py`).
Lancement : `flock <verrou> ~/.local/bin/uv run pytest tests/api/test_programmes.py`
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

import httpx
import pytest

from app.models import Bridge, Institution, Programme, Speciality
from tests.api.conftest import World, headers

pytestmark = pytest.mark.db


# --- Aides ---------------------------------------------------------------------------------------


def err(resp: httpx.Response) -> str:
    return resp.json()["error"]["code"]


async def add_programme(
    w: World,
    code: str,
    name: str,
    *,
    ptype: str = "licence",
    status: str = "published",
    institution: uuid.UUID | None = None,
    duration: int = 3,
    **extra: Any,
) -> Programme:
    pub = w._published() if status == "published" else w.publication(status)
    pub.update(
        {k: date.fromisoformat(extra.pop(k)) for k in ("valid_from", "valid_to") if k in extra}
    )
    row = Programme(
        institution_id=institution or w.iit,
        code=code,
        name_fr=name,
        programme_type=ptype,
        duration_years=duration,
        **pub,
        **extra,
    )
    w.session.add(row)
    await w.session.flush()
    return row


async def add_bridge(
    w: World,
    src: uuid.UUID,
    tgt: uuid.UUID,
    *,
    status: str = "published",
    entry: int = 1,
    after: int = 2,
    **extra: Any,
) -> Bridge:
    pub = w._published() if status == "published" else w.publication(status)
    row = Bridge(
        source_programme_id=src,
        source_min_completed_years=after,
        target_programme_id=tgt,
        target_entry_level=entry,
        access_mode="on_application",
        conditions_summary_fr="Sur dossier (fictif).",
        **pub,
        **extra,
    )
    w.session.add(row)
    await w.session.flush()
    return row


def new_programme_body(w: World, code: str | None = None, **kw: Any) -> dict[str, Any]:
    body = {
        "institution_id": str(w.iit),
        "code": code or f"NEW-{w.tag}",
        "name_fr": "Licence test",
        "programme_type": "licence",
        "duration_years": 3,
        "valid_from": "2026-09-01",
    }
    body.update(kw)
    return body


async def published_via_api(api: httpx.AsyncClient, w: World, path: str, row_id: str) -> dict:
    """Soumission par le responsable A puis publication par le responsable B (4 yeux)."""
    get = await api.get(f"/staff/catalogue/{path}/{row_id}", headers=w.h_lead_a())
    sub = await api.post(
        f"/staff/catalogue/{path}/{row_id}/submit",
        headers={**w.h_lead_a(), "If-Match": get.headers["ETag"]},
    )
    assert sub.status_code == 200, sub.text
    pub = await api.post(
        f"/staff/catalogue/{path}/{row_id}/publish",
        headers={**w.h_lead_b(), "If-Match": sub.headers["ETag"]},
    )
    assert pub.status_code == 200, pub.text
    return pub.json()


# ============ Public : lecture et recherche ============


async def test_liste_publique_filtree_par_institution(api: httpx.AsyncClient, world: World):
    w = world
    await add_programme(w, f"DRAFT-{w.tag}", "Licence brouillon", status="draft")
    await w.commit()
    resp = await api.get("/catalogue/programmes", params={"institution": f"t{w.tag}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"] == {"page": 1, "page_size": 20, "total_items": 1, "total_pages": 1}
    item = body["items"][0]
    assert item["id"] == str(w.programme)
    assert item["level"] == "licence" and item["speciality_count"] == 1
    assert item["institution"] == f"T{w.tag}"
    assert item["source"]["entity_type"] == "programme"
    assert item["source"]["entity_id"] == str(w.programme)
    assert item["source"]["valid_from"] == "2020-09-01"


async def test_brouillon_invisible_en_public(api: httpx.AsyncClient, world: World):
    w = world
    draft = await add_programme(w, f"DRAFT-{w.tag}", "Licence cachée", status="draft")
    pending = await add_programme(
        w, f"PEND-{w.tag}", "Licence en relecture", status="pending_review"
    )
    await w.commit()
    for row in (draft, pending):
        assert (await api.get(f"/catalogue/programmes/{row.id}")).status_code == 404
    resp = await api.get("/catalogue/programmes", params={"q": "cachée relecture"})
    assert resp.json()["meta"]["total_items"] == 0


async def test_validite_et_parametre_date(api: httpx.AsyncClient, world: World):
    w = world
    old = await add_programme(
        w, f"OLD-{w.tag}", "Licence fermée", valid_from="2019-09-01", valid_to="2024-09-01"
    )
    await w.commit()
    assert (await api.get(f"/catalogue/programmes/{old.id}")).status_code == 404
    past = await api.get(f"/catalogue/programmes/{old.id}", params={"date": "2023-01-15"})
    assert past.status_code == 200
    assert past.json()["source"]["valid_to"] == "2024-09-01"


async def test_recherche_insensible_aux_accents_et_specialites(
    api: httpx.AsyncClient, world: World
):
    w = world
    await w.commit()
    scope = {"institution": f"T{w.tag}"}
    for q in ("informatique", "INFORMATIQUE", "génie logiciel", "GENIE", "logiciel fictif"):
        resp = await api.get("/catalogue/programmes", params={**scope, "q": q})
        assert resp.json()["meta"]["total_items"] == 1, q
    resp = await api.get("/catalogue/programmes", params={**scope, "q": "chimie"})
    assert resp.json()["meta"]["total_items"] == 0
    # Les jokers SQL saisis sont échappés.
    resp = await api.get("/catalogue/programmes", params={**scope, "q": "%"})
    assert resp.json()["meta"]["total_items"] == 0


async def test_recherche_en_arabe_normalisee(api: httpx.AsyncClient, world: World):
    w = world
    await add_programme(w, f"AR-{w.tag}", "Licence en sciences", name_ar="الإجازة في الإعلامية")
    await w.commit()
    for q in ("الاعلامية", "الإعلاميّة"):  # sans hamza ; avec chadda
        resp = await api.get("/catalogue/programmes", params={"q": q, "institution": f"T{w.tag}"})
        assert resp.json()["meta"]["total_items"] == 1, q


async def test_filtres_niveau_specialite_tri_pagination(api: httpx.AsyncClient, world: World):
    w = world
    eng = await add_programme(
        w, f"ING-{w.tag}", "Cycle ingénieur (fictif)", ptype="engineering", duration=3
    )
    await add_programme(
        w, f"PREP-{w.tag}", "Prépa intégrée (fictive)", ptype="preparatory", duration=2
    )
    await w.commit()
    scope = {"institution": f"T{w.tag}"}

    resp = await api.get("/catalogue/programmes", params={**scope, "level": "ingenieur"})
    assert [i["id"] for i in resp.json()["items"]] == [str(eng.id)]
    resp = await api.get(
        "/catalogue/programmes",
        params=[("institution", f"T{w.tag}"), ("level", "prepa"), ("level", "engineering")],
    )
    assert resp.json()["meta"]["total_items"] == 2

    resp = await api.get("/catalogue/programmes", params={**scope, "speciality": "gl"})
    assert [i["id"] for i in resp.json()["items"]] == [str(w.programme)]

    resp = await api.get("/catalogue/programmes", params={**scope, "sort": "duration_years"})
    assert resp.json()["items"][0]["level"] == "preparatory"
    resp = await api.get("/catalogue/programmes", params={**scope, "sort": "-name"})
    names = [i["name"] for i in resp.json()["items"]]
    assert names == sorted(names, reverse=True)

    page2 = await api.get("/catalogue/programmes", params={**scope, "page": 2, "page_size": 2})
    assert page2.json()["meta"] == {"page": 2, "page_size": 2, "total_items": 3, "total_pages": 2}
    assert len(page2.json()["items"]) == 1

    both = await api.get(
        "/catalogue/programmes", params=[("institution", f"T{w.tag}"), ("institution", str(w.isb))]
    )
    assert both.json()["meta"]["total_items"] == 4


async def test_filtres_invalides(api: httpx.AsyncClient, world: World):
    for params in ({"level": "doctorat"}, {"sort": "prix"}, {"page_size": 500}, {"page": 0}):
        resp = await api.get("/catalogue/programmes", params=params)
        assert resp.status_code == 422, params
        assert err(resp) == "VALIDATION_ERROR"


async def test_pertinence_nom_avant_description(api: httpx.AsyncClient, world: World):
    w = world
    await add_programme(
        w,
        f"DESC-{w.tag}",
        "Licence gestion",
        description_fr="Ouverture vers le réseau et la sécurité.",
    )
    net = await add_programme(w, f"NET-{w.tag}", "Réseaux et télécoms")
    await w.commit()
    resp = await api.get(
        "/catalogue/programmes", params={"q": "reseau", "institution": f"T{w.tag}"}
    )
    items = resp.json()["items"]
    assert len(items) == 2 and items[0]["id"] == str(net.id)


async def test_fiche_formation_specialites_et_passerelles(api: httpx.AsyncClient, world: World):
    w = world
    eng = await add_programme(w, f"ING-{w.tag}", "Cycle ingénieur (fictif)", ptype="engineering")
    bridge = await add_bridge(w, w.programme, eng.id, entry=1, after=3)
    await add_bridge(w, w.programme, eng.id, entry=2, after=3, status="draft")
    await w.commit()
    resp = await api.get(f"/catalogue/programmes/{w.programme}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["institution_name"] == "IIT (fictif)"
    assert [s["code"] for s in body["specialities"]] == ["GL"]
    assert body["specialities"][0]["source"]["entity_type"] == "speciality"
    assert [b["id"] for b in body["bridges_from"]] == [str(bridge.id)]
    assert body["bridges_from"][0]["to_programme"]["level"] == "engineering"
    assert body["bridges_from"][0]["source"]["version"] == 1
    assert "to_duration_years" not in body["bridges_from"][0]
    eng_detail = (await api.get(f"/catalogue/programmes/{eng.id}")).json()
    assert [b["id"] for b in eng_detail["bridges_to"]] == [str(bridge.id)]


async def test_passerelles_publiques_et_filtres(api: httpx.AsyncClient, world: World):
    w = world
    eng = await add_programme(w, f"ING-{w.tag}", "Cycle ingénieur (fictif)", ptype="engineering")
    hidden_target = await add_programme(w, f"HID-{w.tag}", "Cible brouillon", status="draft")
    b1 = await add_bridge(w, w.programme, eng.id)
    await add_bridge(w, w.programme, hidden_target.id)  # cible non publiée → masquée
    await w.commit()
    resp = await api.get("/catalogue/bridges", params={"from_programme_id": str(w.programme)})
    assert resp.status_code == 200
    assert [b["id"] for b in resp.json()["items"]] == [str(b1.id)]
    resp = await api.get(
        "/catalogue/bridges", params={"institution": f"T{w.tag}", "to_level": "ingenieur"}
    )
    assert resp.json()["meta"]["total_items"] == 1
    resp = await api.get(
        "/catalogue/bridges", params={"institution": f"T{w.tag}", "to_level": "master"}
    )
    assert resp.json()["meta"]["total_items"] == 0


async def test_specialites_et_institutions_publiques(api: httpx.AsyncClient, world: World):
    w = world
    draft_spec = Speciality(
        programme_id=w.programme, code="IA", name_fr="IA (brouillon)", **w.publication("draft")
    )
    w.session.add(draft_spec)
    await w.commit()
    resp = await api.get("/catalogue/specialities", params={"programme_id": str(w.programme)})
    assert [s["code"] for s in resp.json()["items"]] == ["GL"]
    resp = await api.get(
        "/catalogue/specialities", params={"q": "genie", "institution": f"T{w.tag}"}
    )
    assert resp.json()["meta"]["total_items"] == 1
    assert (await api.get(f"/catalogue/specialities/{w.speciality}")).status_code == 200
    assert (await api.get(f"/catalogue/specialities/{draft_spec.id}")).status_code == 404
    inst = await api.get("/catalogue/institutions")
    codes = [i["code"] for i in inst.json()["items"]]
    assert f"T{w.tag}" in codes and f"S{w.tag}" in codes


async def test_institution_non_publiee_masque_ses_formations(api: httpx.AsyncClient, world: World):
    w = world
    inst = Institution(
        code=f"X{w.tag}", name_fr="Institut brouillon", city="Sfax", **w.publication("draft")
    )
    w.session.add(inst)
    await w.session.flush()
    prog = await add_programme(w, f"XP-{w.tag}", "Licence orpheline", institution=inst.id)
    await w.commit()
    assert (await api.get(f"/catalogue/programmes/{prog.id}")).status_code == 404


# ============ Staff : autorisations ============


async def test_creation_roles_et_perimetre(api: httpx.AsyncClient, world: World):
    w = world
    await w.commit()
    body = new_programme_body(w)
    assert (await api.post("/staff/catalogue/programmes", json=body)).status_code == 401
    for h in (
        w.h_candidate(),
        w.h_direction(),
        w.h_admin(),
        headers("interview_lead", user=w.lead_a),
    ):
        resp = await api.post("/staff/catalogue/programmes", json=body, headers=h)
        assert resp.status_code == 403 and err(resp) == "FORBIDDEN"
    resp = await api.post("/staff/catalogue/programmes", json=body, headers=w.h_isb())
    assert resp.status_code == 403
    assert resp.json()["error"]["details"]["reason"] == "out_of_scope"
    # Compte inconnu de user_account : refusé (cible des FK d'auteur).
    ghost = headers("iit_academic_lead", user=uuid.uuid4(), institution=w.iit)
    assert (
        await api.post("/staff/catalogue/programmes", json=body, headers=ghost)
    ).status_code == 403

    resp = await api.post("/staff/catalogue/programmes", json=body, headers=w.h_lead_a())
    assert resp.status_code == 201, resp.text
    created = resp.json()
    assert created["publication_status"] == "draft"
    assert created["created_by"] == str(w.lead_a)
    assert resp.headers["ETag"].startswith('W/"')


async def test_lecture_staff_perimetre(api: httpx.AsyncClient, world: World):
    w = world
    await add_programme(w, f"DRAFT-{w.tag}", "Licence brouillon", status="draft")
    await w.commit()
    scope = {"institution": [f"T{w.tag}", f"S{w.tag}"]}
    iit = await api.get("/staff/catalogue/programmes", params=scope, headers=w.h_lead_a())
    assert iit.status_code == 200 and iit.json()["meta"]["total_items"] == 2
    isb = await api.get("/staff/catalogue/programmes", params=scope, headers=w.h_isb())
    assert [p["id"] for p in isb.json()["items"]] == [str(w.isb_programme)]
    for h in (w.h_direction(), w.h_admin()):
        resp = await api.get("/staff/catalogue/programmes", params=scope, headers=h)
        assert resp.json()["meta"]["total_items"] == 3
    drafts = await api.get(
        "/staff/catalogue/programmes", params={**scope, "status": "draft"}, headers=w.h_direction()
    )
    assert drafts.json()["meta"]["total_items"] == 1
    # Hors périmètre : 404 (pas de fuite d'existence) ; candidat : 403.
    assert (
        await api.get(f"/staff/catalogue/programmes/{w.programme}", headers=w.h_isb())
    ).status_code == 404
    assert (
        await api.get(f"/staff/catalogue/programmes/{w.programme}", headers=w.h_candidate())
    ).status_code == 403
    inst = await api.get("/staff/catalogue/institutions", headers=w.h_lead_a())
    assert inst.status_code == 200
    assert {i["code"] for i in inst.json()["items"]} == {f"T{w.tag}"}
    one = await api.get(f"/staff/catalogue/institutions/{w.iit}", headers=w.h_admin())
    assert one.status_code == 200 and one.headers["ETag"]


# ============ Staff : validations ============


async def test_validations_creation(api: httpx.AsyncClient, world: World):
    w = world
    await w.commit()
    h = w.h_lead_a()
    cases = [
        ({k: v for k, v in new_programme_body(w).items() if k != "name_fr"}, "name_fr"),
        (new_programme_body(w, code="minuscule"), "code"),
        (new_programme_body(w, duration_years=9), "duration_years"),
        (new_programme_body(w, programme_type="doctorat"), "programme_type"),
        (new_programme_body(w, valid_to="2026-01-01"), None),
        (new_programme_body(w, unknown_field=1), "unknown_field"),
    ]
    for body, field in cases:
        resp = await api.post("/staff/catalogue/programmes", json=body, headers=h)
        assert resp.status_code == 422, body
        assert err(resp) == "VALIDATION_ERROR"
        if field:
            assert field in {d["field"] for d in resp.json()["error"]["details"]}
    resp = await api.post(
        "/staff/catalogue/programmes",
        json=new_programme_body(w, institution_id=str(uuid.uuid4())),
        headers=h,
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["details"][0] == {
        "field": "institution_id",
        "issue": "not_found",
        "location": "body",
    }


async def test_code_en_double_conflit(api: httpx.AsyncClient, world: World):
    w = world
    await w.commit()
    resp = await api.post(
        "/staff/catalogue/programmes",
        json=new_programme_body(w, code=w.programme_code),
        headers=w.h_lead_a(),
    )
    assert resp.status_code == 409 and err(resp) == "CONFLICT"


async def test_patch_if_match_et_brouillon_seulement(api: httpx.AsyncClient, world: World):
    w = world
    await w.commit()
    h = w.h_lead_a()
    created = await api.post("/staff/catalogue/programmes", json=new_programme_body(w), headers=h)
    pid, etag = created.json()["id"], created.headers["ETag"]
    url = f"/staff/catalogue/programmes/{pid}"

    resp = await api.patch(url, json={"name_fr": "Licence renommée"}, headers=h)
    assert resp.status_code == 428 and err(resp) == "PRECONDITION_REQUIRED"
    resp = await api.patch(
        url, json={"name_fr": "Licence renommée"}, headers={**h, "If-Match": 'W/"perime"'}
    )
    assert resp.status_code == 412 and err(resp) == "PRECONDITION_FAILED"
    resp = await api.patch(url, json={"name_fr": None}, headers={**h, "If-Match": etag})
    assert resp.status_code == 422
    assert resp.json()["error"]["details"][0]["issue"] == "null_not_allowed"
    resp = await api.patch(url, json={"valid_to": "2020-01-01"}, headers={**h, "If-Match": etag})
    assert resp.status_code == 422

    resp = await api.patch(
        url, json={"name_fr": "Licence renommée"}, headers={**h, "If-Match": etag}
    )
    assert resp.status_code == 200
    assert resp.json()["name_fr"] == "Licence renommée"
    assert resp.headers["ETag"] != etag
    # L'ancien ETag est désormais périmé.
    stale = await api.patch(url, json={"name_fr": "Encore"}, headers={**h, "If-Match": etag})
    assert stale.status_code == 412
    # Autre établissement : 404 ; direction : 403 (pas auteur).
    resp = await api.patch(
        url, json={"name_fr": "x" * 5}, headers={**w.h_isb(), "If-Match": resp.headers["ETag"]}
    )
    assert resp.status_code == 404
    assert (await api.patch(url, json={}, headers=w.h_direction())).status_code == 403

    # Une formation publiée n'est pas modifiable par PATCH.
    pub = await api.get(f"/staff/catalogue/programmes/{w.programme}", headers=h)
    resp = await api.patch(
        f"/staff/catalogue/programmes/{w.programme}",
        json={"name_fr": "Interdit"},
        headers={**h, "If-Match": pub.headers["ETag"]},
    )
    assert resp.status_code == 409 and err(resp) == "INVALID_STATUS_TRANSITION"


# ============ Staff : cycle de publication ============


async def test_cycle_publication_quatre_yeux(api: httpx.AsyncClient, world: World):
    w = world
    await w.commit()
    created = await api.post(
        "/staff/catalogue/programmes", json=new_programme_body(w), headers=w.h_lead_a()
    )
    pid = created.json()["id"]
    base = f"/staff/catalogue/programmes/{pid}"

    resp = await api.post(f"{base}/submit", headers=w.h_lead_a())
    assert resp.status_code == 428
    resp = await api.post(
        f"{base}/submit", headers={**w.h_lead_a(), "If-Match": created.headers["ETag"]}
    )
    assert resp.status_code == 200 and resp.json()["publication_status"] == "pending_review"
    etag = resp.headers["ETag"]

    # Auteur qui publie : 403 FOUR_EYES_REQUIRED ; admin : 403 ; autre institution : 404.
    resp = await api.post(f"{base}/publish", headers={**w.h_lead_a(), "If-Match": etag})
    assert resp.status_code == 403 and err(resp) == "FOUR_EYES_REQUIRED"
    resp = await api.post(f"{base}/publish", headers={**w.h_admin(), "If-Match": etag})
    assert resp.status_code == 403 and err(resp) == "FORBIDDEN"
    resp = await api.post(f"{base}/publish", headers={**w.h_isb(), "If-Match": etag})
    assert resp.status_code == 404
    # Toujours invisible côté public.
    assert (await api.get(f"/catalogue/programmes/{pid}")).status_code == 404

    resp = await api.post(f"{base}/publish", headers={**w.h_lead_b(), "If-Match": etag})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["publication_status"] == "published"
    assert body["published_by"] == str(w.lead_b) and body["submitted_by"] == str(w.lead_a)
    assert (await api.get(f"/catalogue/programmes/{pid}")).status_code == 200

    # Re-publier : transition invalide ; archiver (direction) : invisible ensuite.
    resp = await api.post(
        f"{base}/publish", headers={**w.h_direction(), "If-Match": resp.headers["ETag"]}
    )
    assert resp.status_code == 409 and err(resp) == "INVALID_STATUS_TRANSITION"
    resp = await api.post(
        f"{base}/archive", json={"reason": "Fermeture (fictif)"}, headers=w.h_direction()
    )
    assert resp.status_code == 200 and resp.json()["publication_status"] == "archived"
    assert (await api.get(f"/catalogue/programmes/{pid}")).status_code == 404


async def test_rejet_avec_motif_et_soumission_incomplete(api: httpx.AsyncClient, world: World):
    w = world
    await w.commit()
    body = new_programme_body(w)
    body.pop("valid_from")
    created = await api.post("/staff/catalogue/programmes", json=body, headers=w.h_lead_a())
    pid, etag = created.json()["id"], created.headers["ETag"]
    base = f"/staff/catalogue/programmes/{pid}"
    resp = await api.post(f"{base}/submit", headers={**w.h_lead_a(), "If-Match": etag})
    assert resp.status_code == 422
    assert resp.json()["error"]["details"][0]["field"] == "valid_from"

    resp = await api.patch(
        base, json={"valid_from": "2026-09-01"}, headers={**w.h_lead_a(), "If-Match": etag}
    )
    resp = await api.post(
        f"{base}/submit", headers={**w.h_lead_a(), "If-Match": resp.headers["ETag"]}
    )
    assert resp.status_code == 200
    resp = await api.post(f"{base}/reject", json={}, headers=w.h_lead_b())
    assert resp.status_code == 422  # motif obligatoire
    resp = await api.post(f"{base}/reject", json={"reason": "Nom à revoir."}, headers=w.h_lead_b())
    assert resp.status_code == 200
    assert resp.json()["publication_status"] == "draft"
    assert resp.json()["submitted_by"] is None


# ============ Staff : spécialités, matières ============


async def test_specialite_creation_et_perimetre(api: httpx.AsyncClient, world: World):
    w = world
    await w.commit()
    body = {
        "programme_id": str(w.programme),
        "code": "IA",
        "name_fr": "Intelligence artificielle",
        "valid_from": "2026-09-01",
    }
    resp = await api.post("/staff/catalogue/specialities", json=body, headers=w.h_isb())
    assert resp.status_code == 403
    resp = await api.post(
        "/staff/catalogue/specialities",
        json={**body, "programme_id": str(uuid.uuid4())},
        headers=w.h_lead_a(),
    )
    assert resp.status_code == 422
    resp = await api.post("/staff/catalogue/specialities", json=body, headers=w.h_lead_a())
    assert resp.status_code == 201
    sid = resp.json()["id"]
    dup = await api.post("/staff/catalogue/specialities", json=body, headers=w.h_lead_a())
    assert dup.status_code == 409
    await published_via_api(api, w, "specialities", sid)
    detail = (await api.get(f"/catalogue/programmes/{w.programme}")).json()
    assert {s["code"] for s in detail["specialities"]} == {"GL", "IA"}


async def test_matieres_crud(api: httpx.AsyncClient, world: World):
    w = world
    await w.commit()
    body = {"institution_id": str(w.iit), "code": "ASD1", "name_fr": "Algorithmique 1"}
    assert (
        await api.post("/staff/catalogue/subjects", json=body, headers=w.h_isb())
    ).status_code == 403
    resp = await api.post("/staff/catalogue/subjects", json=body, headers=w.h_lead_a())
    assert resp.status_code == 201
    sid, etag = resp.json()["id"], resp.headers["ETag"]
    resp = await api.patch(
        f"/staff/catalogue/subjects/{sid}",
        json={"domain": "informatique"},
        headers={**w.h_lead_a(), "If-Match": etag},
    )
    assert resp.status_code == 200 and resp.json()["domain"] == "informatique"
    lst = await api.get("/staff/catalogue/subjects", params={"q": "algo"}, headers=w.h_lead_a())
    assert [s["id"] for s in lst.json()["items"]] == [sid]
    assert (await api.get(f"/staff/catalogue/subjects/{sid}", headers=w.h_isb())).status_code == 404


# ============ Staff : passerelles ============


async def test_passerelle_fk_composite_et_nouvelle_version(api: httpx.AsyncClient, world: World):
    w = world
    eng = await add_programme(w, f"ING-{w.tag}", "Cycle ingénieur (fictif)", ptype="engineering")
    await w.commit()
    body = {
        "source_programme_id": str(w.programme),
        "source_min_completed_years": 3,
        "target_programme_id": str(eng.id),
        "target_entry_level": 1,
        "access_mode": "on_application",
        "conditions_summary_fr": "Sur dossier (fictif).",
        "valid_from": "2026-09-01",
    }
    # Spécialité qui n'appartient pas à la formation source → 422 (FK composite).
    resp = await api.post(
        "/staff/catalogue/bridges",
        json={**body, "target_speciality_id": str(w.speciality)},
        headers=w.h_lead_a(),
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["details"][0]["issue"] == "not_in_programme"
    resp = await api.post(
        "/staff/catalogue/bridges",
        json={**body, "target_programme_id": str(w.programme)},
        headers=w.h_lead_a(),
    )
    assert resp.status_code == 422  # départ = arrivée

    resp = await api.post(
        "/staff/catalogue/bridges",
        json={**body, "source_speciality_id": str(w.speciality)},
        headers=w.h_lead_a(),
    )
    assert resp.status_code == 201, resp.text
    v1 = await published_via_api(api, w, "bridges", resp.json()["id"])

    # Nouvelle version : brouillon copié ; publier en chevauchement → 409 VALIDITY_OVERLAP.
    resp = await api.post(
        f"/staff/catalogue/bridges/{v1['id']}/new-version",
        json={"valid_from": "2027-09-01"},
        headers=w.h_lead_a(),
    )
    assert resp.status_code == 201
    v2 = resp.json()
    assert v2["publication_status"] == "draft" and v2["valid_from"] == "2027-09-01"
    assert v2["source_speciality_id"] == str(w.speciality)
    get = await api.get(f"/staff/catalogue/bridges/{v2['id']}", headers=w.h_lead_a())
    sub = await api.post(
        f"/staff/catalogue/bridges/{v2['id']}/submit",
        headers={**w.h_lead_a(), "If-Match": get.headers["ETag"]},
    )
    resp = await api.post(
        f"/staff/catalogue/bridges/{v2['id']}/publish",
        headers={**w.h_lead_b(), "If-Match": sub.headers["ETag"]},
    )
    assert resp.status_code == 409 and err(resp) == "VALIDITY_OVERLAP"
    resp = await api.post(
        f"/staff/catalogue/bridges/{v2['id']}/publish",
        json={"replace_current": True},
        headers={**w.h_lead_b(), "If-Match": sub.headers["ETag"]},
    )
    assert resp.status_code == 200, resp.text
    old = await api.get(f"/staff/catalogue/bridges/{v1['id']}", headers=w.h_lead_a())
    assert old.json()["valid_to"] == "2027-09-01"
    # Nouvelle version depuis une version publiée : oui ; depuis un brouillon : 409.
    resp = await api.post(
        f"/staff/catalogue/bridges/{v2['id']}/new-version", json={}, headers=w.h_lead_a()
    )
    assert resp.status_code == 201  # v2 publiée : nouvelle version autorisée
    draft_id = resp.json()["id"]
    resp = await api.post(
        f"/staff/catalogue/bridges/{draft_id}/new-version", json={}, headers=w.h_lead_a()
    )
    assert resp.status_code == 409


async def test_publication_journalisee(api: httpx.AsyncClient, world: World, db_session):
    from sqlalchemy import select

    from app.models import CatalogueAuditLog, StatusHistory

    w = world
    await w.commit()
    created = await api.post(
        "/staff/catalogue/programmes", json=new_programme_body(w), headers=w.h_lead_a()
    )
    pid = created.json()["id"]
    await published_via_api(api, w, "programmes", pid)
    history = (
        await db_session.scalars(
            select(StatusHistory)
            .where(StatusHistory.entity_id == uuid.UUID(pid))
            .order_by(StatusHistory.changed_at, StatusHistory.to_status.desc())
        )
    ).all()
    assert {(h.to_status, h.requires_human) for h in history} == {
        ("pending_review", False),
        ("published", True),
    }
    actions = (
        await db_session.scalars(
            select(CatalogueAuditLog.action).where(CatalogueAuditLog.row_id == uuid.UUID(pid))
        )
    ).all()
    assert set(actions) == {"insert", "submit", "publish"}
    actors = (
        await db_session.scalars(
            select(CatalogueAuditLog.actor_id).where(CatalogueAuditLog.row_id == uuid.UUID(pid))
        )
    ).all()
    assert set(actors) == {w.lead_a, w.lead_b}
