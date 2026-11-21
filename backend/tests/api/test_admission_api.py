"""API des conditions d'admission et des prérequis (SA-21)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.models import Curriculum, Subject
from tests.api.conftest import World

pytestmark = pytest.mark.db

D = "2026-11-17"


def cond_body(w: World, year: str = "2027-2028", **kw) -> dict:
    body = {
        "programme_id": str(w.programme),
        "academic_year": year,
        "accepted_bac_sections": ["mathematiques", "sciences_informatique"],
        "min_average": "12.00",
        "average_basis": "bac_average",
        "requires_test": True,
        "summary_fr": "Bac Mathématiques ou Informatique, moyenne 12 (fictif).",
        "subject_requirements": [
            {"subject_key": "mathematiques", "subject_name_fr": "Mathématiques", "min_grade": "11"}
        ],
        "valid_from": "2026-06-01",
    }
    body.update(kw)
    return body


async def test_cycle_nominal(api, world: World):
    w = world
    r = await api.post(
        "/staff/catalogue/admission-conditions", json=cond_body(w), headers=w.h_lead_a()
    )
    assert r.status_code == 201, r.text
    rid, etag = r.json()["id"], r.headers["ETag"]
    assert r.json()["subject_requirements"][0]["min_grade"] == "11.00"

    r = await api.patch(
        f"/staff/catalogue/admission-conditions/{rid}",
        json={"subject_requirements": [
            {"subject_key": "mathematiques", "subject_name_fr": "Mathématiques", "min_grade": "12"},
            {"subject_key": "physique", "subject_name_fr": "Physique", "min_grade": "10"},
        ]},
        headers=w.h_lead_a() | {"If-Match": etag},
    )  # fmt: skip
    assert r.status_code == 200, r.text
    assert [s["subject_key"] for s in r.json()["subject_requirements"]] == [
        "mathematiques",
        "physique",
    ]

    r = await api.post(
        f"/staff/catalogue/admission-conditions/{rid}/submit",
        headers=w.h_lead_a() | {"If-Match": r.headers["ETag"]},
    )
    assert r.status_code == 200, r.text
    etag = r.headers["ETag"]

    r = await api.post(
        f"/staff/catalogue/admission-conditions/{rid}/publish",
        headers=w.h_lead_a() | {"If-Match": etag},
    )
    assert r.status_code == 403 and r.json()["error"]["code"] == "FOUR_EYES_REQUIRED"
    r = await api.post(
        f"/staff/catalogue/admission-conditions/{rid}/publish",
        headers=w.h_admin() | {"If-Match": etag},
    )
    assert r.status_code == 403 and r.json()["error"]["code"] == "FORBIDDEN"
    r = await api.post(
        f"/staff/catalogue/admission-conditions/{rid}/publish",
        headers=w.h_lead_b() | {"If-Match": etag},
    )
    assert r.status_code == 200, r.text

    r = await api.get(
        f"/catalogue/programmes/{w.programme}/admission-conditions",
        params={"academic_year": "2027-2028", "date": D},
    )
    assert r.status_code == 200, r.text
    [c] = r.json()["conditions"]
    assert c["id"] == rid
    assert c["label"].startswith("Bac Mathématiques")
    assert c["accepted_bac_sections"] == ["mathematiques", "sciences_informatique"]
    assert c["source"]["entity_type"] == "admission_condition"
    assert c["source"]["version"] == 1


async def test_annee_obligatoire_et_invisibles(api, world: World):
    w = world
    await w.condition("2026-2027", "published")
    await w.condition("2027-2028", "pending_review")
    await w.condition("2028-2029", "draft")
    await w.commit()
    url = f"/catalogue/programmes/{w.programme}/admission-conditions"
    r = await api.get(url, params={"date": D})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "ACADEMIC_YEAR_REQUIRED"
    assert r.json()["error"]["details"]["available_academic_years"] == ["2026-2027"]
    r = await api.get(url, params={"academic_year": "2027-2028", "date": D})
    assert r.json()["conditions"] == []


async def test_deux_annees_en_parallele_et_precedence(api, world: World):
    w = world
    a = await w.condition("2026-2027", "published", min_average="10")
    b = await w.condition("2027-2028", "published", min_average="12")
    gl = await w.condition("2027-2028", "published", speciality=w.speciality, min_average="13")
    await w.commit()
    url = f"/catalogue/programmes/{w.programme}/admission-conditions"
    r1 = (await api.get(url, params={"academic_year": "2026-2027", "date": D})).json()
    assert [c["id"] for c in r1["conditions"]] == [str(a.id)]
    r2 = (await api.get(url, params={"academic_year": "2027-2028", "date": D})).json()
    assert [c["id"] for c in r2["conditions"]] == [str(b.id)]
    r3 = (
        await api.get(
            url,
            params={"academic_year": "2027-2028", "date": D, "speciality_id": str(w.speciality)},
        )
    ).json()
    assert [(c["id"], c["scope"]) for c in r3["conditions"]] == [(str(gl.id), "speciality")]


async def test_chevauchement_et_figee(api, world: World):
    w = world
    old = await w.condition("2027-2028", "published")
    new = await w.condition("2027-2028", "pending_review", valid_from="2026-06-01")
    await w.commit()
    url = f"/staff/catalogue/admission-conditions/{new.id}"
    etag = (await api.get(url, headers=w.h_lead_b())).headers["ETag"]
    r = await api.post(f"{url}/publish", headers=w.h_lead_b() | {"If-Match": etag})
    assert r.status_code == 409 and r.json()["error"]["code"] == "VALIDITY_OVERLAP"

    old_url = f"/staff/catalogue/admission-conditions/{old.id}"
    etag = (await api.get(old_url, headers=w.h_lead_a())).headers["ETag"]
    r = await api.patch(
        old_url, json={"min_average": "8"}, headers=w.h_lead_a() | {"If-Match": etag}
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "INVALID_STATUS_TRANSITION"


async def test_autorisations(api, world: World):
    w = world
    row = await w.condition("2026-2027", "draft")
    await w.commit()
    url = f"/staff/catalogue/admission-conditions/{row.id}"
    assert (await api.get(url)).status_code == 401
    assert (await api.get(url, headers=w.h_candidate())).status_code == 403
    assert (await api.get(url, headers=w.h_isb())).status_code == 404
    assert (await api.get(url, headers=w.h_direction())).status_code == 200
    r = await api.post(
        "/staff/catalogue/admission-conditions", json=cond_body(w), headers=w.h_direction()
    )
    assert r.status_code == 403
    r = await api.post(
        "/staff/catalogue/admission-conditions",
        json=cond_body(w, accepted_bac_sections=["math"]),
        headers=w.h_lead_a(),
    )
    assert r.status_code == 422  # clé anglaise / inconnue refusée (C1)


async def test_prerequis_du_cursus(api, world: World, db_session):
    w = world
    subject = Subject(institution_id=w.iit, code="ALGO1", name_fr="Algorithmique 1")
    draft_cur = Curriculum(
        programme_id=w.programme, version_label="v-brouillon", academic_year="2027-2028",
        publication_status="draft", created_by=w.lead_a,
    )  # fmt: skip
    pub_cur = Curriculum(
        programme_id=w.programme,
        version_label="v-publiee",
        academic_year="2026-2027",
        publication_status="published",
        valid_from=datetime(2026, 3, 1).date(),
        created_by=w.lead_a,
        submitted_by=w.lead_a,
        submitted_at=datetime(2026, 2, 1, tzinfo=UTC),
        published_by=w.lead_b,
        published_at=datetime(2026, 2, 2, tzinfo=UTC),
    )
    db_session.add_all([subject, draft_cur, pub_cur])
    await db_session.flush()
    await w.condition("2026-2027", "published")
    await w.commit()

    body = {"curriculum_id": str(draft_cur.id), "required_knowledge_fr": "Bases d'algèbre"}
    r = await api.post("/staff/catalogue/prerequisites", json=body, headers=w.h_lead_a())
    assert r.status_code == 201, r.text
    pid, cur_etag = r.json()["id"], r.headers["ETag"]  # ETag du cursus parent
    patch = {"required_subject_id": str(subject.id), "is_mandatory": False}
    url = f"/staff/catalogue/prerequisites/{pid}"
    # A2 : If-Match du CURSUS obligatoire sur le PATCH d'un prérequis (428 / 412)
    r = await api.patch(url, json=patch, headers=w.h_lead_a())
    assert r.status_code == 428
    r = await api.patch(url, json=patch, headers=w.h_lead_a() | {"If-Match": 'W/"perime"'})
    assert r.status_code == 412
    r = await api.patch(url, json=patch, headers=w.h_lead_a() | {"If-Match": cur_etag})
    assert r.status_code == 200 and r.json()["is_mandatory"] is False
    assert "ETag" in r.headers
    r = await api.get(
        "/staff/catalogue/prerequisites",
        params={"curriculum_id": str(draft_cur.id)},
        headers=w.h_direction(),
    )
    assert r.json()[0]["required_subject_name_fr"] == "Algorithmique 1"

    # Cursus publié : enfants figés
    body = {"curriculum_id": str(pub_cur.id), "required_knowledge_fr": "Logique"}
    r = await api.post("/staff/catalogue/prerequisites", json=body, headers=w.h_lead_a())
    assert r.status_code == 409

    # A3 : cursus inexistant → 422 `not_found` + location (comme SA-20)
    body = {"curriculum_id": str(subject.id), "required_knowledge_fr": "X"}
    r = await api.post("/staff/catalogue/prerequisites", json=body, headers=w.h_lead_a())
    assert r.status_code == 422
    assert r.json()["error"]["details"] == [
        {"field": "curriculum_id", "issue": "not_found", "location": "body"}
    ]

    # Lecture publique : prérequis du cursus entier de la version publiée
    from app.models import Prerequisite

    db_session.add(Prerequisite(curriculum_id=pub_cur.id, required_knowledge_fr="Logique"))
    await db_session.commit()
    r = await api.get(
        f"/catalogue/programmes/{w.programme}/admission-conditions",
        params={"academic_year": "2026-2027", "date": D},
    )
    [p] = r.json()["prerequisites"]
    assert p["label"] == "Logique"
    assert p["source"]["entity_type"] == "curriculum"
    assert p["source"]["entity_id"] == str(pub_cur.id)

    r = await api.delete(f"/staff/catalogue/prerequisites/{pid}", headers=w.h_lead_a())
    assert r.status_code == 204


async def test_eligibilite_http(api, world: World):
    w = world
    await w.condition("2026-2027", "published")
    await w.commit()
    body = {
        "programme_id": str(w.programme),
        "academic_year": "2026-2027",
        "as_of": D,
        "bac_section": "mathematiques",
        "bac_average": "14.20",
        "subject_grades": {"mathematiques": "15"},
    }
    r = await api.post("/catalogue/eligibility-check", json=body)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] == "met"
    assert data["computed_by"] == "code"
    assert all(c["met"] is True for c in data["criteria"])

    r = await api.post("/catalogue/eligibility-check", json=body | {"academic_year": None})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "ACADEMIC_YEAR_REQUIRED"
    assert r.json()["error"]["details"]["available_academic_years"] == ["2026-2027"]
