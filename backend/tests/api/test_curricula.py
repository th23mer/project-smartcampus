"""Tests SA-20 : cursus et matières du cursus (API publique et staff)."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import httpx
import pytest

from app.models import Curriculum, CurriculumSubject, Prerequisite, Programme, Subject
from tests.api.conftest import World
from tests.api.test_programmes import err, published_via_api

pytestmark = pytest.mark.db


async def add_subject(w: World, code: str, name: str, institution: uuid.UUID | None = None):
    row = Subject(institution_id=institution or w.iit, code=code, name_fr=name)
    w.session.add(row)
    await w.session.flush()
    return row


async def published_curriculum(
    w: World,
    *,
    speciality: uuid.UUID | None = None,
    status: str = "published",
    label: str = "v2020",
):
    pub = w._published() if status == "published" else w.publication(status)
    cur = Curriculum(
        programme_id=w.programme,
        speciality_id=speciality,
        version_label=label,
        academic_year="2020-2021",
        total_ects=10,
        **pub,
    )
    w.session.add(cur)
    await w.session.flush()
    s1 = await add_subject(w, f"A{label[-2:]}{uuid.uuid4().hex[:4]}".upper(), "Algorithmique 1")
    s2 = await add_subject(w, f"B{label[-2:]}{uuid.uuid4().hex[:4]}".upper(), "Analyse 1")
    l1 = CurriculumSubject(
        curriculum_id=cur.id,
        subject_id=s1.id,
        semester=1,
        coefficient=Decimal(2),
        ects_credits=Decimal(5),
        hours_lecture=Decimal(21),
        hours_tutorial=Decimal(21),
    )
    l2 = CurriculumSubject(
        curriculum_id=cur.id,
        subject_id=s2.id,
        semester=2,
        coefficient=Decimal(2),
        ects_credits=Decimal("5.0"),
        hours_lecture=Decimal(30),
    )
    w.session.add_all([l1, l2])
    await w.session.flush()
    w.session.add(
        Prerequisite(
            curriculum_id=cur.id,
            curriculum_subject_id=l2.id,
            required_subject_id=s1.id,
            is_mandatory=True,
        )
    )
    await w.session.flush()
    return cur, (s1, s2)


def curriculum_body(w: World, **kw: Any) -> dict[str, Any]:
    body = {
        "programme_id": str(w.programme),
        "version_label": "v2027",
        "academic_year": "2027-2028",
        "total_ects": 6,
        "valid_from": "2026-09-01",
    }
    body.update(kw)
    return body


def line_body(subject_id: uuid.UUID, **kw: Any) -> dict[str, Any]:
    body = {
        "subject_id": str(subject_id),
        "semester": 1,
        "coefficient": "2",
        "ects_credits": "6",
        "hours_lecture": "21",
        "hours_tutorial": "10.5",
    }
    body.update(kw)
    return body


# ============ Public ============


async def test_cursus_public_par_semestre(api: httpx.AsyncClient, world: World):
    w = world
    cur, (s1, _) = await published_curriculum(w)
    await published_curriculum(w, status="draft", label="v2099")
    await w.commit()
    resp = await api.get(f"/catalogue/programmes/{w.programme}/curricula")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert [c["id"] for c in items] == [str(cur.id)]
    c = items[0]
    assert c["computed_total_credits"] == "10.0" and c["total_ects"] == 10
    assert [s["semester"] for s in c["semesters"]] == [1, 2]
    assert [s["year_of_study"] for s in c["semesters"]] == [1, 1]
    first = c["semesters"][0]["subjects"][0]
    assert first["code"] == s1.code and first["hours"] == "42.0" and first["credits"] == "5.0"
    prereq = c["semesters"][1]["subjects"][0]["prerequisites"]
    assert prereq == [
        {
            "subject_code": s1.code,
            "subject_name": "Algorithmique 1",
            "knowledge": None,
            "is_mandatory": True,
        }
    ]
    assert c["source"]["entity_type"] == "curriculum" and c["source"]["version"] == 1


async def test_cursus_specialite_et_formation_non_publiee(api: httpx.AsyncClient, world: World):
    w = world
    common, _ = await published_curriculum(w)
    spec_cur, _ = await published_curriculum(w, speciality=w.speciality, label="v2021")
    draft_prog = Programme(
        institution_id=w.iit,
        code=f"DR-{w.tag}",
        name_fr="Brouillon",
        programme_type="licence",
        duration_years=3,
        **w.publication("draft"),
    )
    w.session.add(draft_prog)
    await w.commit()
    items = (await api.get(f"/catalogue/programmes/{w.programme}/curricula")).json()["items"]
    assert [c["id"] for c in items] == [str(common.id), str(spec_cur.id)]
    assert items[1]["speciality"]["code"] == "GL"
    resp = await api.get(
        f"/catalogue/programmes/{w.programme}/curricula",
        params={"speciality_id": str(uuid.uuid4())},
    )
    assert [c["id"] for c in resp.json()["items"]] == [str(common.id)]
    resp = await api.get(f"/catalogue/programmes/{draft_prog.id}/curricula")
    assert resp.status_code == 404 and err(resp) == "NOT_FOUND"


# ============ Staff ============


async def test_cursus_brouillon_matieres_et_publication(api: httpx.AsyncClient, world: World):
    w = world
    algo = await add_subject(w, "ALGO", "Algorithmique")
    other = await add_subject(w, "COMPTA", "Comptabilité", institution=w.isb)
    await w.commit()
    h = w.h_lead_a()

    # Spécialité d'une autre formation → 422 ; ISB → 403 ; candidat → 403.
    resp = await api.post(
        "/staff/catalogue/curricula",
        json=curriculum_body(w, programme_id=str(w.isb_programme), speciality_id=str(w.speciality)),
        headers=w.h_isb(),
    )
    assert resp.status_code == 422
    assert (
        await api.post("/staff/catalogue/curricula", json=curriculum_body(w), headers=w.h_isb())
    ).status_code == 403
    assert (
        await api.post(
            "/staff/catalogue/curricula", json=curriculum_body(w), headers=w.h_candidate()
        )
    ).status_code == 403
    resp = await api.post(
        "/staff/catalogue/curricula", json=curriculum_body(w, academic_year="2027-2029"), headers=h
    )
    assert resp.status_code == 422

    resp = await api.post("/staff/catalogue/curricula", json=curriculum_body(w), headers=h)
    assert resp.status_code == 201, resp.text
    cid, etag = resp.json()["id"], resp.headers["ETag"]
    assert resp.json()["subjects"] == []
    base = f"/staff/catalogue/curricula/{cid}"

    # Soumission sans matière : refusée.
    resp = await api.post(f"{base}/submit", headers={**h, "If-Match": etag})
    assert resp.status_code == 422
    assert resp.json()["error"]["details"][0] == {"field": "subjects", "issue": "required"}

    # Matières : If-Match obligatoire, établissement cohérent, pas de doublon, bornes.
    assert (
        await api.post(f"{base}/subjects", json=line_body(algo.id), headers=h)
    ).status_code == 428
    resp = await api.post(
        f"{base}/subjects", json=line_body(other.id), headers={**h, "If-Match": etag}
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["details"][0]["issue"] == "other_institution"
    resp = await api.post(
        f"{base}/subjects", json=line_body(algo.id, semester=11), headers={**h, "If-Match": etag}
    )
    assert resp.status_code == 422
    resp = await api.post(
        f"{base}/subjects", json=line_body(algo.id, ects_credits=4), headers={**h, "If-Match": etag}
    )
    assert resp.status_code == 201, resp.text
    line = resp.json()
    assert line["hours_total"] == "31.5"
    etag = resp.headers["ETag"]
    dup = await api.post(
        f"{base}/subjects", json=line_body(algo.id), headers={**h, "If-Match": etag}
    )
    assert dup.status_code == 409 and err(dup) == "CONFLICT"

    # Crédits incohérents avec total_ects (4 ≠ 6) → 422 ; correction de la ligne.
    resp = await api.post(f"{base}/submit", headers={**h, "If-Match": etag})
    assert resp.status_code == 422
    assert resp.json()["error"]["details"][0]["issue"] == "credits_mismatch"
    resp = await api.patch(
        f"{base}/subjects/{line['id']}", json={"ects_credits": "6"}, headers={**h, "If-Match": etag}
    )
    assert resp.status_code == 200 and resp.json()["ects_credits"] == "6.0"
    etag = resp.headers["ETag"]

    lst = await api.get(f"{base}/subjects", headers=w.h_direction())
    assert [x["id"] for x in lst.json()] == [line["id"]]
    detail = await api.get(base, headers=w.h_admin())
    assert detail.status_code == 200 and len(detail.json()["subjects"]) == 1

    await published_via_api(api, w, "curricula", cid)
    items = (await api.get(f"/catalogue/programmes/{w.programme}/curricula")).json()["items"]
    assert [c["id"] for c in items] == [cid]

    # Version publiée : matières figées.
    pub = await api.get(base, headers=h)
    resp = await api.post(
        f"{base}/subjects",
        json=line_body(algo.id, semester=2),
        headers={**h, "If-Match": pub.headers["ETag"]},
    )
    assert resp.status_code == 409 and err(resp) == "INVALID_STATUS_TRANSITION"
    resp = await api.delete(
        f"{base}/subjects/{line['id']}", headers={**h, "If-Match": pub.headers["ETag"]}
    )
    assert resp.status_code == 409


async def test_nouvelle_version_copie_les_matieres(api: httpx.AsyncClient, world: World):
    w = world
    cur, (s1, s2) = await published_curriculum(w)
    await w.commit()
    h = w.h_lead_a()
    base = f"/staff/catalogue/curricula/{cur.id}"
    resp = await api.post(f"{base}/new-version", json={}, headers=h)
    assert resp.status_code == 422  # version_label obligatoire
    resp = await api.post(f"{base}/new-version", json={"version_label": "v2020"}, headers=h)
    assert resp.status_code == 409  # libellé déjà utilisé
    resp = await api.post(
        f"{base}/new-version",
        json={"version_label": "v2027", "academic_year": "2027-2028", "valid_from": "2027-09-01"},
        headers=h,
    )
    assert resp.status_code == 201, resp.text
    v2 = resp.json()
    assert v2["publication_status"] == "draft" and v2["academic_year"] == "2027-2028"
    assert {x["subject_id"] for x in v2["subjects"]} == {str(s1.id), str(s2.id)}

    # Retirer une matière du brouillon, puis remplacer la version publiée.
    v2_base = f"/staff/catalogue/curricula/{v2['id']}"
    etag = (await api.get(v2_base, headers=h)).headers["ETag"]
    line_s2 = next(x for x in v2["subjects"] if x["subject_id"] == str(s2.id))
    resp = await api.delete(f"{v2_base}/subjects/{line_s2['id']}", headers={**h, "If-Match": etag})
    assert resp.status_code == 204
    resp = await api.patch(v2_base, json={"total_ects": 5}, headers={**h, "If-Match": etag})
    assert resp.status_code == 200
    sub = await api.post(f"{v2_base}/submit", headers={**h, "If-Match": resp.headers["ETag"]})
    assert sub.status_code == 200, sub.text
    resp = await api.post(
        f"{v2_base}/publish",
        json={"replace_current": True},
        headers={**w.h_lead_b(), "If-Match": sub.headers["ETag"]},
    )
    assert resp.status_code == 200, resp.text
    old = (await api.get(base, headers=h)).json()
    assert old["valid_to"] == "2027-09-01" and old["publication_status"] == "published"

    later = await api.get(
        f"/catalogue/programmes/{w.programme}/curricula", params={"date": "2027-10-01"}
    )
    item = later.json()["items"][0]
    assert item["id"] == v2["id"] and item["source"]["version"] == 2
    assert item["computed_total_credits"] == "5.0"
    today = await api.get(f"/catalogue/programmes/{w.programme}/curricula")
    assert today.json()["items"][0]["id"] == str(cur.id)


async def test_cursus_perimetre_et_liste_staff(api: httpx.AsyncClient, world: World):
    w = world
    cur, _ = await published_curriculum(w, status="draft")
    await w.commit()
    lst = await api.get(
        "/staff/catalogue/curricula",
        params={"programme_id": str(w.programme), "status": "draft"},
        headers=w.h_lead_a(),
    )
    assert [c["id"] for c in lst.json()["items"]] == [str(cur.id)]
    assert "subjects" not in lst.json()["items"][0]
    isb = await api.get(
        "/staff/catalogue/curricula", params={"programme_id": str(w.programme)}, headers=w.h_isb()
    )
    assert isb.json()["meta"]["total_items"] == 0
    assert (
        await api.get(f"/staff/catalogue/curricula/{cur.id}", headers=w.h_isb())
    ).status_code == 404
    resp = await api.patch(
        f"/staff/catalogue/curricula/{cur.id}",
        json={"notes_fr": "x"},
        headers={**w.h_isb(), "If-Match": "*"},
    )
    assert resp.status_code == 404
