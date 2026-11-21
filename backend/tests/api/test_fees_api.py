"""API des frais (SA-21) : workflow staff à 4 yeux, lecture publique officielle, droits."""

from __future__ import annotations

import pytest

from tests.api.conftest import World

pytestmark = pytest.mark.db

D = "2026-11-17"  # date de référence fixe


def fee_body(w: World, year: str = "2027-2028", **kw) -> dict:
    body = {
        "programme_id": str(w.programme),
        "academic_year": year,
        "registration_fee": {"amount": "300.000", "currency": "TND"},
        "tuition_fee": {"amount": "6800.000", "currency": "TND"},
        "valid_from": "2026-06-01",
    }
    body.update(kw)
    return body


async def create_draft(api, w: World, **kw) -> tuple[str, str]:
    r = await api.post(
        "/staff/catalogue/fee-schedules", json=fee_body(w, **kw), headers=w.h_lead_a()
    )
    assert r.status_code == 201, r.text
    return r.json()["id"], r.headers["ETag"]


async def submit(api, w: World, rid: str) -> str:
    etag = (await api.get(f"/staff/catalogue/fee-schedules/{rid}", headers=w.h_lead_a())).headers[
        "ETag"
    ]
    r = await api.post(
        f"/staff/catalogue/fee-schedules/{rid}/submit", headers=w.h_lead_a() | {"If-Match": etag}
    )
    assert r.status_code == 200, r.text
    return r.headers["ETag"]


# --- Nominal ---------------------------------------------------------------------------------


async def test_cycle_nominal_et_lecture_publique(api, world: World):
    w = world
    rid, etag = await create_draft(api, w)

    # plan de paiement : 3 tranches dont la somme = total (7100.000)
    plan = {
        "fee_schedule_id": rid,
        "code": "TRANCHES-3",
        "label_fr": "Trois tranches",
        "installment_count": 3,
        "is_default": True,
        "installments": [
            {"installment_no": 1, "due_label_fr": "À l'inscription", "amount": "2900.000"},
            {"installment_no": 2, "due_date": "2028-01-15", "amount": "2100.000"},
            {"installment_no": 3, "due_date": "2028-04-15", "amount": "2100.000"},
        ],
    }
    r = await api.post("/staff/catalogue/payment-plans", json=plan, headers=w.h_lead_a())
    assert r.status_code == 201, r.text

    # PATCH avec If-Match (les frais changent, le total suit : colonne générée)
    etag = (await api.get(f"/staff/catalogue/fee-schedules/{rid}", headers=w.h_lead_a())).headers[
        "ETag"
    ]
    r = await api.patch(
        f"/staff/catalogue/fee-schedules/{rid}",
        json={"tuition_fee": {"amount": "6750.000", "currency": "TND"}},
        headers=w.h_lead_a() | {"If-Match": etag},
    )
    assert r.status_code == 200, r.text
    assert r.json()["annual_total"] == {"amount": "7050.000", "currency": "TND"}

    # Somme des tranches incohérente avec le nouveau total : soumission refusée
    r = await api.post(
        f"/staff/catalogue/fee-schedules/{rid}/submit",
        headers=w.h_lead_a() | {"If-Match": r.headers["ETag"]},
    )
    assert r.status_code == 422
    assert r.json()["error"]["details"][0]["issue"] == "sum_mismatch"

    plan_id = (
        await api.get(
            "/staff/catalogue/payment-plans", params={"fee_schedule_id": rid}, headers=w.h_lead_a()
        )
    ).json()[0]["id"]
    fix = {
        "installments": [
            {"installment_no": 1, "due_label_fr": "À l'inscription", "amount": "2850.000"},
            {"installment_no": 2, "due_date": "2028-01-15", "amount": "2100.000"},
            {"installment_no": 3, "due_date": "2028-04-15", "amount": "2100.000"},
        ]
    }
    plan_url = f"/staff/catalogue/payment-plans/{plan_id}"
    # A2 : If-Match de la GRILLE obligatoire sur le PATCH d'un plan (428 / 412)
    r = await api.patch(plan_url, json=fix, headers=w.h_lead_a())
    assert r.status_code == 428
    r = await api.patch(plan_url, json=fix, headers=w.h_lead_a() | {"If-Match": 'W/"perime"'})
    assert r.status_code == 412
    parent_etag = (
        await api.get(f"/staff/catalogue/fee-schedules/{rid}", headers=w.h_lead_a())
    ).headers["ETag"]
    r = await api.patch(plan_url, json=fix, headers=w.h_lead_a() | {"If-Match": parent_etag})
    assert r.status_code == 200, r.text
    assert r.headers["ETag"].startswith('W/"')  # nouvel ETag de la grille

    etag = await submit(api, w, rid)
    r = await api.post(
        f"/staff/catalogue/fee-schedules/{rid}/publish", headers=w.h_lead_b() | {"If-Match": etag}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["publication_status"] == "published"
    assert body["published_by"] == str(w.lead_b)
    assert body["submitted_by"] == str(w.lead_a)

    r = await api.get(
        f"/catalogue/programmes/{w.programme}/fees",
        params={"academic_year": "2027-2028", "date": D},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["academic_year"] == "2027-2028"
    [fee] = data["fee_schedules"]
    assert fee["id"] == rid
    assert fee["tuition_fee"] == {"amount": "6750.000", "currency": "TND"}
    assert fee["annual_total"] == {"amount": "7050.000", "currency": "TND"}
    assert fee["source"]["entity_type"] == "fee_schedule"
    assert fee["source"]["version"] == 1
    assert fee["source"]["valid_from"] == "2026-06-01"
    [plan_out] = fee["payment_plans"]
    assert [i["amount"]["amount"] for i in plan_out["installments"]] == [
        "2850.000",
        "2100.000",
        "2100.000",
    ]


# --- Quatre yeux et rôles ----------------------------------------------------------------------


async def test_quatre_yeux_et_admin(api, world: World):
    w = world
    rid, _ = await create_draft(api, w)
    etag = await submit(api, w, rid)
    url = f"/staff/catalogue/fee-schedules/{rid}/publish"

    r = await api.post(url, headers=w.h_lead_a() | {"If-Match": etag})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "FOUR_EYES_REQUIRED"

    r = await api.post(url, headers=w.h_admin() | {"If-Match": etag})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "FORBIDDEN"

    r = await api.post(url, headers=w.h_direction())
    assert r.status_code == 428  # If-Match obligatoire sur /publish

    r = await api.post(url, headers=w.h_direction() | {"If-Match": 'W/"perime"'})
    assert r.status_code == 412

    r = await api.post(url, headers=w.h_direction() | {"If-Match": etag})
    assert r.status_code == 200, r.text
    assert r.json()["published_by"] == str(w.direction)


async def test_rejet_et_archivage(api, world: World):
    w = world
    rid, _ = await create_draft(api, w)
    await submit(api, w, rid)
    base = f"/staff/catalogue/fee-schedules/{rid}"

    r = await api.post(f"{base}/reject", json={}, headers=w.h_lead_b())
    assert r.status_code == 422  # motif obligatoire
    r = await api.post(
        f"{base}/reject", json={"reason": "Montant à vérifier"}, headers=w.h_lead_b()
    )
    assert r.status_code == 200
    assert r.json()["publication_status"] == "draft"
    assert r.json()["submitted_by"] is None

    r = await api.post(f"{base}/archive", headers=w.h_direction())
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "INVALID_STATUS_TRANSITION"
    assert r.json()["error"]["details"]["allowed"] == ["pending_review"]

    etag = await submit(api, w, rid)
    await api.post(f"{base}/publish", headers=w.h_lead_b() | {"If-Match": etag})
    r = await api.post(
        f"{base}/archive", json={"reason": "Grille retirée"}, headers=w.h_direction()
    )
    assert r.status_code == 200
    assert r.json()["publication_status"] == "archived"
    r = await api.get(
        f"/catalogue/programmes/{w.programme}/fees",
        params={"academic_year": "2027-2028", "date": D},
    )
    assert r.json()["fee_schedules"] == []


async def test_chevauchement(api, world: World):
    w = world
    await w.fee("2027-2028", "published", valid_from="2026-03-01")
    await w.commit()
    rid, _ = await create_draft(api, w)  # même clé, même année, période qui chevauche
    etag = await submit(api, w, rid)
    url = f"/staff/catalogue/fee-schedules/{rid}/publish"
    r = await api.post(url, headers=w.h_lead_b() | {"If-Match": etag})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "VALIDITY_OVERLAP"

    r = await api.post(
        url, json={"replace_current": True}, headers=w.h_lead_b() | {"If-Match": etag}
    )
    assert r.status_code == 200, r.text
    r = await api.get(
        f"/catalogue/programmes/{w.programme}/fees",
        params={"academic_year": "2027-2028", "date": D},
    )
    [fee] = r.json()["fee_schedules"]
    assert fee["id"] == rid
    assert fee["source"]["version"] == 2


async def test_version_publiee_figee(api, world: World):
    w = world
    row = await w.fee("2026-2027", "published")
    await w.commit()
    url = f"/staff/catalogue/fee-schedules/{row.id}"
    etag = (await api.get(url, headers=w.h_lead_a())).headers["ETag"]
    r = await api.patch(
        url,
        json={"tuition_fee": {"amount": "1.000", "currency": "TND"}},
        headers=w.h_lead_a() | {"If-Match": etag},
    )
    assert r.status_code == 409
    assert r.json()["error"]["details"]["reason"] == "only_draft_editable"
    assert r.json()["error"]["details"]["hint"] == "new_version"

    r = await api.delete(url, headers=w.h_lead_a())
    assert r.status_code == 409
    # Réponse commune des DELETE du catalogue (décision du 21/11) : publiée → archiver.
    assert r.json()["error"]["details"]["reason"] == "only_draft_deletable"
    assert r.json()["error"]["details"]["hint"] == "archive"

    plan = {"fee_schedule_id": str(row.id), "code": "COMPTANT", "label_fr": "Comptant",
            "installment_count": 1}  # fmt: skip
    r = await api.post("/staff/catalogue/payment-plans", json=plan, headers=w.h_lead_a())
    assert r.status_code == 409  # enfant d'une version publiée : figé

    r = await api.post(
        f"{url}/new-version", json={"academic_year": "2027-2028"}, headers=w.h_lead_a()
    )
    assert r.status_code == 201, r.text
    copy = r.json()
    assert copy["publication_status"] == "draft"
    assert copy["academic_year"] == "2027-2028"
    assert copy["id"] != str(row.id)
    assert len(copy["payment_plans"]) == 1


async def test_if_match_obligatoire_sur_patch(api, world: World):
    w = world
    rid, etag = await create_draft(api, w)
    url = f"/staff/catalogue/fee-schedules/{rid}"
    r = await api.patch(url, json={"notes_fr": "x"}, headers=w.h_lead_a())
    assert r.status_code == 428
    r = await api.patch(url, json={"notes_fr": "x"}, headers=w.h_lead_a() | {"If-Match": etag})
    assert r.status_code == 200
    r = await api.patch(url, json={"notes_fr": "y"}, headers=w.h_lead_a() | {"If-Match": etag})
    assert r.status_code == 412  # ETag périmé après la première modification


# --- Lecture publique --------------------------------------------------------------------------


async def test_annee_obligatoire(api, world: World):
    w = world
    await w.fee("2026-2027", "published")
    await w.fee("2027-2028", "published")
    await w.fee("2028-2029", "pending_review")
    await w.commit()
    r = await api.get(f"/catalogue/programmes/{w.programme}/fees", params={"date": D})
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "ACADEMIC_YEAR_REQUIRED"
    assert err["details"]["available_academic_years"] == ["2026-2027", "2027-2028"]
    assert "fee_schedules" not in r.text


async def test_brouillon_et_relecture_invisibles(api, world: World):
    w = world
    await w.fee("2027-2028", "draft")
    await w.fee("2027-2028", "pending_review", tuition="9999")
    await w.fee("2027-2028", "archived", tuition="1")
    await w.commit()
    r = await api.get(
        f"/catalogue/programmes/{w.programme}/fees",
        params={"academic_year": "2027-2028", "date": D},
    )
    assert r.status_code == 200
    assert r.json()["fee_schedules"] == []
    assert r.json()["available_academic_years"] == []


async def test_deux_annees_en_parallele(api, world: World):
    w = world
    a = await w.fee("2026-2027", "published", tuition="6500")
    b = await w.fee("2027-2028", "published", tuition="6900")
    await w.commit()
    url = f"/catalogue/programmes/{w.programme}/fees"
    r1 = (await api.get(url, params={"academic_year": "2026-2027", "date": D})).json()
    r2 = (await api.get(url, params={"academic_year": "2027-2028", "date": D})).json()
    assert [f["id"] for f in r1["fee_schedules"]] == [str(a.id)]
    assert [f["id"] for f in r2["fee_schedules"]] == [str(b.id)]
    assert r2["fee_schedules"][0]["annual_total"]["amount"] == "7200.000"
    assert r1["available_academic_years"] == ["2026-2027", "2027-2028"]


async def test_validite_a_la_date(api, world: World):
    w = world
    await w.fee("2026-2027", "published", valid_from="2026-03-01", valid_to="2026-09-01")
    await w.commit()
    url = f"/catalogue/programmes/{w.programme}/fees"
    params = {"academic_year": "2026-2027"}
    assert (
        len((await api.get(url, params=params | {"date": "2026-05-01"})).json()["fee_schedules"])
        == 1
    )
    # valid_to est exclu : plus valable le 1er septembre
    assert (await api.get(url, params=params | {"date": "2026-09-01"})).json()[
        "fee_schedules"
    ] == []


async def test_precedence_la_plus_specifique(api, world: World):
    w = world
    general = await w.fee("2026-2027", "published", tuition="6500")
    gl = await w.fee("2026-2027", "published", speciality=w.speciality, tuition="7000")
    year1 = await w.fee("2026-2027", "published", study_year=1, tuition="6000")
    await w.commit()
    url = f"/catalogue/programmes/{w.programme}/fees"
    base = {"academic_year": "2026-2027", "date": D}

    # Sans spécialité : grilles de la formation (toutes années + 1re année)
    r = (await api.get(url, params=base)).json()
    assert {f["id"] for f in r["fee_schedules"]} == {str(general.id), str(year1.id)}

    # Spécialité GL, toutes années : la grille GL l'emporte sur la grille générale
    r = (await api.get(url, params=base | {"speciality_id": str(w.speciality)})).json()
    ids = {f["id"]: f["scope"] for f in r["fee_schedules"]}
    assert ids == {str(gl.id): "speciality", str(year1.id): "programme"}

    # 2e année sans spécialité : seule la grille « toutes années » s'applique
    r = (await api.get(url, params=base | {"study_year": 2})).json()
    assert [f["id"] for f in r["fee_schedules"]] == [str(general.id)]

    # 1re année : la grille de l'année précise l'emporte
    r = (await api.get(url, params=base | {"study_year": 1})).json()
    assert [f["id"] for f in r["fee_schedules"]] == [str(year1.id)]


async def test_formation_non_publiee(api, world: World):
    w = world
    r = await api.get(
        f"/catalogue/programmes/{w.isb_programme}/fees",
        params={"academic_year": "2026-2027", "date": "2019-01-01"},
    )
    assert r.status_code == 404


# --- Autorisations -------------------------------------------------------------------------------


async def test_autorisations(api, world: World):
    w = world
    rid, _ = await create_draft(api, w)
    url = f"/staff/catalogue/fee-schedules/{rid}"

    assert (await api.get(url)).status_code == 401  # visiteur
    assert (await api.get(url, headers=w.h_candidate())).status_code == 403
    assert (await api.get(url, headers=w.h_isb())).status_code == 404  # hors périmètre
    assert (await api.get(url, headers=w.h_direction())).status_code == 200
    assert (await api.get(url, headers=w.h_admin())).status_code == 200

    # Création : direction et admin interdits ; ISB hors périmètre sur une formation IIT
    for h in (w.h_direction(), w.h_admin(), w.h_candidate()):
        r = await api.post("/staff/catalogue/fee-schedules", json=fee_body(w), headers=h)
        assert r.status_code == 403
    r = await api.post("/staff/catalogue/fee-schedules", json=fee_body(w), headers=w.h_isb())
    assert r.status_code == 403
    assert r.json()["error"]["details"]["reason"] == "out_of_scope"

    # Listes : le responsable ISB ne voit pas les grilles IIT
    lst = await api.get("/staff/catalogue/fee-schedules", headers=w.h_isb())
    assert lst.status_code == 200 and lst.json()["meta"]["total_items"] == 0
    lst = await api.get(
        "/staff/catalogue/fee-schedules",
        params={"programme_id": str(w.programme)},
        headers=w.h_lead_a(),
    )
    assert lst.json()["meta"]["total_items"] == 1

    # Compte staff inexistant en base
    r = await api.post(
        "/staff/catalogue/fee-schedules",
        json=fee_body(w),
        headers={"X-Dev-User-Id": "00000000-0000-0000-0000-0000000000aa",
                 "X-Dev-Roles": "iit_academic_lead", "X-Dev-Institution-Id": str(w.iit)},
    )  # fmt: skip
    assert r.status_code == 403

    # Lecture publique : visiteur, candidat, staff
    await w.fee("2026-2027", "published")
    await w.commit()
    pub_url = f"/catalogue/programmes/{w.programme}/fees"
    for h in ({}, w.h_candidate(), w.h_isb()):
        r = await api.get(pub_url, params={"academic_year": "2026-2027", "date": D}, headers=h)
        assert r.status_code == 200


async def test_validation_des_montants(api, world: World):
    w = world
    r = await api.post(
        "/staff/catalogue/fee-schedules",
        json=fee_body(w, tuition_fee={"amount": 6800.5, "currency": "TND"}),
        headers=w.h_lead_a(),
    )
    assert r.status_code == 422  # flottant refusé
    r = await api.post(
        "/staff/catalogue/fee-schedules",
        json=fee_body(w, academic_year="2027-2029"),
        headers=w.h_lead_a(),
    )
    assert r.status_code == 422
    r = await api.post(
        "/staff/catalogue/fee-schedules",
        json=fee_body(w, other_fees={"amount": "50.000", "currency": "TND"}),
        headers=w.h_lead_a(),
    )
    assert r.status_code == 422  # libellé des autres frais obligatoire
