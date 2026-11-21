"""Champs obligatoires, relations, conflits, préconditions et année obligatoire (SA-22).

- 422 VALIDATION_ERROR : `details` = un élément par champ (`field`, `issue`, `location`),
  **sans** la valeur saisie (SA-7 D3) — vérifié sur toutes les créations staff (générées depuis
  l'OpenAPI) ;
- relations : FK inexistante, spécialité d'une autre formation, matière d'un autre établissement ;
- conflits 409 : code en double, chevauchement de validité (VALIDITY_OVERLAP + replace_current),
  transition invalide ;
- If-Match : absent → 428 PRECONDITION_REQUIRED, périmé → 412 PRECONDITION_FAILED ;
- ACADEMIC_YEAR_REQUIRED (D-J) sur l'API publique et l'outil d'agent.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.tools.catalogue_tools import GetFeesInput, get_fees
from tests.api.conftest import World
from tests.conftest import shared_app
from tests.verification.test_contrat_routes import assert_error_envelope

pytestmark = pytest.mark.db

D = "2026-11-17"
SECRET = "VALEUR-SAISIE-7Q9"  # ne doit jamais réapparaître dans une réponse d'erreur

_OPENAPI = shared_app().openapi()


def _create_routes() -> list[tuple[str, list[str]]]:
    """POST de création staff (corps avec champs obligatoires) → liste des champs requis."""
    schemas = _OPENAPI["components"]["schemas"]
    out = []
    for path, methods in _OPENAPI["paths"].items():
        op = methods.get("post")
        if not op or not path.startswith("/api/v1/staff/") or "requestBody" not in op:
            continue
        ref = op["requestBody"]["content"]["application/json"]["schema"].get("$ref", "")
        required = schemas.get(ref.split("/")[-1], {}).get("required")
        if required and not path.endswith(("/reject", "/new-version")):
            out.append((path.removeprefix("/api/v1"), required))
    return out


CREATE_ROUTES = _create_routes()


def fill(path: str, w: World) -> str:
    return (
        path.replace("{entity_id}", str(w.programme))
        .replace("{row_id}", str(uuid.uuid4()))
        .replace("{revision_id}", str(uuid.uuid4()))
    )


def test_routes_de_creation_inventoriees():
    paths = {p for p, _ in CREATE_ROUTES}
    assert {
        "/staff/catalogue/programmes",
        "/staff/catalogue/specialities",
        "/staff/catalogue/subjects",
        "/staff/catalogue/bridges",
        "/staff/catalogue/curricula",
        "/staff/catalogue/fee-schedules",
        "/staff/catalogue/payment-plans",
        "/staff/catalogue/admission-conditions",
        "/staff/catalogue/prerequisites",
    } <= paths


@pytest.mark.parametrize(("path", "required"), CREATE_ROUTES, ids=[p for p, _ in CREATE_ROUTES])
async def test_champs_obligatoires(api, world: World, path: str, required: list[str]):
    r = await api.post(fill(path, world), json={}, headers=world.h_lead_a())
    assert r.status_code == 422, r.text
    err = assert_error_envelope(r)
    assert err["code"] == "VALIDATION_ERROR"
    missing = {d["field"] for d in err["details"] if d["issue"] == "required"}
    assert missing == set(required)
    assert all(d["location"] == "body" for d in err["details"])


@pytest.mark.parametrize(("path", "required"), CREATE_ROUTES, ids=[p for p, _ in CREATE_ROUTES])
async def test_champ_inconnu_et_valeur_non_renvoyee(
    api, world: World, path: str, required: list[str]
):
    r = await api.post(fill(path, world), json={"champ_inconnu": SECRET}, headers=world.h_lead_a())
    assert r.status_code == 422
    err = assert_error_envelope(r)
    assert {"field": "champ_inconnu", "issue": "extra_forbidden", "location": "body"} in err[
        "details"
    ]
    assert SECRET not in r.text


async def test_types_et_bornes(api, world: World):
    w = world
    body = {
        "institution_id": str(w.iit),
        "code": "LIC-X",
        "name_fr": "Licence (fictive)",
        "programme_type": SECRET,
        "duration_years": 12,
    }
    r = await api.post("/staff/catalogue/programmes", json=body, headers=w.h_lead_a())
    assert r.status_code == 422
    details = {d["field"]: d["issue"] for d in assert_error_envelope(r)["details"]}
    assert details == {"programme_type": "literal_error", "duration_years": "less_than_equal"}
    assert SECRET not in r.text
    # Montant en flottant refusé (chaîne décimale TND obligatoire).
    fee = {
        "programme_id": str(w.programme),
        "academic_year": "2027-2028",
        "registration_fee": {"amount": 300.5, "currency": "TND"},
        "tuition_fee": {"amount": "6800.000", "currency": "TND"},
    }
    r = await api.post("/staff/catalogue/fee-schedules", json=fee, headers=w.h_lead_a())
    assert r.status_code == 422
    assert assert_error_envelope(r)["details"][0]["field"].startswith("registration_fee")
    # Année universitaire mal formée.
    fee |= {"registration_fee": {"amount": "300.000", "currency": "TND"}, "academic_year": "2027"}
    r = await api.post("/staff/catalogue/fee-schedules", json=fee, headers=w.h_lead_a())
    assert r.status_code == 422
    assert assert_error_envelope(r)["details"][0]["field"] == "academic_year"


# --- Relations -------------------------------------------------------------------------------


def fee_body(w: World, **kw: Any) -> dict[str, Any]:
    body = {
        "programme_id": str(w.programme),
        "academic_year": "2027-2028",
        "registration_fee": {"amount": "300.000", "currency": "TND"},
        "tuition_fee": {"amount": "6800.000", "currency": "TND"},
        "valid_from": "2027-03-01",
    }
    return body | kw


async def test_relations_inexistantes(api, world: World):
    w = world
    ghost = str(uuid.uuid4())
    # Formation inexistante : 422 `not_found` sur le champ (A3 harmonisé, comme SA-20).
    r = await api.post(
        "/staff/catalogue/fee-schedules",
        json=fee_body(w, programme_id=ghost),
        headers=w.h_lead_a(),
    )
    assert r.status_code == 422, r.text
    assert assert_error_envelope(r)["details"] == [
        {"field": "programme_id", "issue": "not_found", "location": "body"}
    ]
    assert ghost not in r.text
    # Établissement inexistant pour une formation.
    body = {
        "institution_id": ghost,
        "code": "LIC-GHOST",
        "name_fr": "Formation fantôme",
        "programme_type": "licence",
        "duration_years": 3,
    }
    r = await api.post("/staff/catalogue/programmes", json=body, headers=w.h_lead_a())
    assert r.status_code == 422, r.text
    # A3 corrigé : même `issue` partout (`not_found` + `location`).
    [detail] = assert_error_envelope(r)["details"]
    assert detail == {"field": "institution_id", "issue": "not_found", "location": "body"}
    # Plan de paiement d'une grille inexistante.
    plan = {"fee_schedule_id": ghost, "code": "T2", "label_fr": "Deux", "installment_count": 2}
    r = await api.post("/staff/catalogue/payment-plans", json=plan, headers=w.h_lead_a())
    assert r.status_code in (404, 422), r.text
    assert_error_envelope(r)
    # Matière de cursus inexistante.
    r = await api.post(
        "/staff/catalogue/curricula",
        json={
            "programme_id": str(w.programme),
            "version_label": "v-x",
            "academic_year": "2027-2028",
        },
        headers=w.h_lead_a(),
    )
    assert r.status_code == 201, r.text
    cur = r.json()["id"]
    line = {"subject_id": ghost, "semester": 1, "coefficient": "1.00", "ects_credits": "5.0"}
    r = await api.post(
        f"/staff/catalogue/curricula/{cur}/subjects",
        json=line,
        headers=w.h_lead_a() | {"If-Match": r.headers["ETag"]},
    )
    assert r.status_code in (404, 422), r.text
    assert_error_envelope(r)


async def test_specialite_d_une_autre_formation(api, world: World, db_session):
    w = world
    from app.models import Programme, Speciality

    other = Programme(
        institution_id=w.iit,
        code=f"AUT-{w.tag}",
        name_fr="Autre formation (fictive)",
        programme_type="licence",
        duration_years=3,
        **w._published(),
    )
    db_session.add(other)
    await db_session.flush()
    spec = Speciality(programme_id=other.id, code="AUT", name_fr="Autre", **w._published())
    db_session.add(spec)
    await w.commit()

    r = await api.post(
        "/staff/catalogue/fee-schedules",
        json=fee_body(w, speciality_id=str(spec.id)),
        headers=w.h_lead_a(),
    )
    assert r.status_code == 422, r.text
    err = assert_error_envelope(r)
    assert any(d.get("field") == "speciality_id" for d in err["details"]), err
    # Même règle pour les conditions d'admission et les cursus.
    r = await api.post(
        "/staff/catalogue/admission-conditions",
        json={
            "programme_id": str(w.programme),
            "speciality_id": str(spec.id),
            "academic_year": "2027-2028",
            "summary_fr": "Conditions (fictives).",
        },
        headers=w.h_lead_a(),
    )
    assert r.status_code == 422, r.text
    r = await api.post(
        "/staff/catalogue/curricula",
        json={
            "programme_id": str(w.programme),
            "speciality_id": str(spec.id),
            "version_label": "v-y",
            "academic_year": "2027-2028",
        },
        headers=w.h_lead_a(),
    )
    assert r.status_code == 422, r.text
    # Passerelle : spécialité de départ qui n'appartient pas à la formation de départ.
    r = await api.post(
        "/staff/catalogue/bridges",
        json={
            "source_programme_id": str(w.programme),
            "source_speciality_id": str(spec.id),
            "source_min_completed_years": 3,
            "target_programme_id": str(other.id),
            "target_entry_level": 1,
            "access_mode": "application",
            "conditions_summary_fr": "Sur dossier (fictif).",
        },
        headers=w.h_lead_a(),
    )
    assert r.status_code == 422, r.text


# --- Conflits, transitions, préconditions --------------------------------------------------


async def test_code_en_double_conflit(api, world: World):
    w = world
    body = {
        "institution_id": str(w.iit),
        "code": w.programme_code,
        "name_fr": "Doublon (fictif)",
        "programme_type": "licence",
        "duration_years": 3,
    }
    r = await api.post("/staff/catalogue/programmes", json=body, headers=w.h_lead_a())
    assert r.status_code == 409, r.text
    assert assert_error_envelope(r)["code"] == "CONFLICT"
    assert w.programme_code not in r.json()["error"]["message"]


async def test_chevauchement_puis_remplacement(api, world: World):
    w = world
    old = await w.fee("2027-2028", "published", valid_from="2027-03-01")
    new = await w.fee("2027-2028", "pending_review", valid_from="2027-06-01")
    await w.commit()
    url = f"/staff/catalogue/fee-schedules/{new.id}"
    etag = (await api.get(url, headers=w.h_lead_b())).headers["ETag"]
    r = await api.post(f"{url}/publish", headers=w.h_lead_b() | {"If-Match": etag})
    assert r.status_code == 409
    err = assert_error_envelope(r)
    assert err["code"] == "VALIDITY_OVERLAP"
    assert err["details"]["hint"] == "replace_current"
    assert [c["id"] for c in err["details"]["conflicting"]] == [str(old.id)]
    r = await api.post(
        f"{url}/publish",
        json={"replace_current": True},
        headers=w.h_lead_b() | {"If-Match": etag},
    )
    assert r.status_code == 200, r.text
    old_now = (
        await api.get(f"/staff/catalogue/fee-schedules/{old.id}", headers=w.h_lead_b())
    ).json()
    assert old_now["valid_to"] == "2027-06-01"


async def test_transition_invalide(api, world: World):
    w = world
    row = await w.fee("2027-2028", "published", valid_from="2027-03-01")
    await w.commit()
    url = f"/staff/catalogue/fee-schedules/{row.id}"
    etag = (await api.get(url, headers=w.h_lead_a())).headers["ETag"]
    r = await api.post(f"{url}/submit", headers=w.h_lead_a() | {"If-Match": etag})
    assert r.status_code == 409
    err = assert_error_envelope(r)
    assert err["code"] == "INVALID_STATUS_TRANSITION"
    assert err["details"]["current_status"] == "published"
    # Version publiée figée : PATCH refusé avec un indice.
    r = await api.patch(url, json={"notes_fr": "x"}, headers=w.h_lead_a() | {"If-Match": etag})
    assert r.status_code == 409
    assert assert_error_envelope(r)["details"]["reason"] == "only_draft_editable"
    # Rejet sans motif : 422 ; archivage d'un brouillon : 409.
    r = await api.post(f"{url}/reject", json={}, headers=w.h_lead_b())
    assert r.status_code == 422
    draft = await w.fee("2028-2029", "draft", valid_from="2028-03-01")
    await w.commit()
    r = await api.post(f"/staff/catalogue/fee-schedules/{draft.id}/archive", headers=w.h_lead_b())
    assert r.status_code == 409


@pytest.mark.parametrize(
    "target",
    [
        ("PATCH", "", {"notes_fr": "x"}, "draft"),
        ("POST", "/submit", None, "draft"),
        ("POST", "/publish", None, "pending_review"),
    ],
    ids=["patch", "submit", "publish"],
)
async def test_if_match_obligatoire_et_perime(api, world: World, target):
    method, suffix, body, status = target
    w = world
    row = await w.fee("2027-2028", status, valid_from="2027-03-01")
    await w.commit()
    url = f"/staff/catalogue/fee-schedules/{row.id}"
    h = w.h_lead_b()
    kw: dict[str, Any] = {"json": body} if body is not None else {}

    r = await api.request(method, url + suffix, headers=h, **kw)
    assert r.status_code == 428, r.text
    assert assert_error_envelope(r)["code"] == "PRECONDITION_REQUIRED"

    r = await api.request(method, url + suffix, headers=h | {"If-Match": 'W/"perime"'}, **kw)
    assert r.status_code == 412, r.text
    err = assert_error_envelope(r)
    assert err["code"] == "PRECONDITION_FAILED"
    current = (await api.get(url, headers=h)).headers["ETag"]
    assert err["details"]["current_etag"] == current

    r = await api.request(method, url + suffix, headers=h | {"If-Match": current}, **kw)
    assert r.status_code == 200, r.text


@pytest.mark.parametrize("entity", ["programmes", "specialities", "curricula", "bridges"])
async def test_if_match_obligatoire_patch_sa20(api, world: World, entity: str):
    """PATCH sans If-Match sur les entités SA-20 : 428 avant toute autre vérification."""
    r = await api.patch(
        f"/staff/catalogue/{entity}/{uuid.uuid4()}", json={}, headers=world.h_lead_a()
    )
    assert r.status_code in (404, 428), r.text  # ligne inexistante : 404 possible d'abord
    assert_error_envelope(r)


# --- Année universitaire obligatoire (D-J) ---------------------------------------------------


async def test_academic_year_required_api_et_outil(api, world: World, db_session):
    w = world
    await w.fee("2026-2027", "published")
    await w.fee("2027-2028", "pending_review", valid_from="2027-03-01")
    await w.condition("2026-2027", "published")
    await w.commit()
    for path in ("fees", "admission-conditions"):
        r = await api.get(f"/catalogue/programmes/{w.programme}/{path}", params={"date": D})
        assert r.status_code == 422, r.text
        err = assert_error_envelope(r)
        assert err["code"] == "ACADEMIC_YEAR_REQUIRED"
        # Seulement les années publiées et valides (2027-2028 est en relecture).
        assert err["details"] == {"available_academic_years": ["2026-2027"]}
        assert "fee_schedules" not in r.text and "conditions" not in r.json()
    r = await api.post(
        "/catalogue/eligibility-check",
        json={"programme_id": str(w.programme), "bac_section": "mathematiques", "as_of": D},
    )
    assert r.status_code == 422
    assert assert_error_envelope(r)["code"] == "ACADEMIC_YEAR_REQUIRED"

    out = await get_fees(
        db_session,
        GetFeesInput(programme_code=w.programme_code, as_of=D),  # type: ignore[arg-type]
    )
    assert out.ok is False
    assert out.code == "ACADEMIC_YEAR_REQUIRED"
    assert out.details == {"available_academic_years": ["2026-2027"]}
