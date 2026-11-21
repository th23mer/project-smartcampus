"""Matrice des rôles des actions staff du catalogue, comparée à SA-5 §4 + D-H + D9 (SA-22).

Pour chaque action (créer, modifier, soumettre, publier, rejeter, archiver, réviser, supprimer
un brouillon) et chaque
appelant, le statut HTTP attendu est écrit dans `MATRIX` ; le test le compare à la réponse
réelle. Deux familles d'entités : une grille de frais (noyau SA-21) et une formation (SA-20,
révision d'une entité publiée, suppression d'un brouillon : décision du 21/11).

Appelants : A = responsable IIT auteur (soumetteur), B = autre responsable IIT, ISB =
responsable de l'autre établissement (hors périmètre), DIR = direction, ADM = admin
plateforme, ENTR = responsable entretiens, CAND = candidat, A+ENTR = rôles cumulés.

Règles attendues :
- SA-5 §4 : créer / modifier / soumettre / nouvelle version = IIT (S), ISB (S) ; supprimer un
  brouillon = mêmes droits que modifier (décision du 21/11) ;
  publier / rejeter / archiver = IIT (S), ISB (S), Dir. ; admin : lecture seule ;
- D-H : publieur ≠ soumetteur (A → 403 FOUR_EYES_REQUIRED) ; l'admin ne publie jamais ;
- SA-21 F2 : l'auteur ne renvoie pas lui-même en brouillon (403 FOUR_EYES_REQUIRED) ;
- SA-20 D9 : ligne existante hors périmètre → 404 ; création hors périmètre → 403
  (`details.reason = out_of_scope`) ;
- SA-5 §1.3 : rôles cumulés = union des droits.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from tests.api.conftest import World, headers

pytestmark = pytest.mark.db

CALLERS = ("A", "B", "ISB", "DIR", "ADM", "ENTR", "CAND", "A+ENTR")
ACTIONS = ("create", "modify", "submit", "publish", "reject", "archive", "revise", "delete")

F4 = "FOUR_EYES_REQUIRED"
#: action → appelant → (statut, code d'erreur attendu ou None)
MATRIX: dict[str, dict[str, tuple[int, str | None]]] = {
    "create": {
        "A": (201, None),
        "B": (201, None),
        "ISB": (403, "FORBIDDEN"),  # D9 : création hors périmètre
        "DIR": (403, "FORBIDDEN"),
        "ADM": (403, "FORBIDDEN"),
        "ENTR": (403, "FORBIDDEN"),
        "CAND": (403, "FORBIDDEN"),
        "A+ENTR": (201, None),
    },
    "modify": {
        "A": (200, None),
        "B": (200, None),
        "ISB": (404, "NOT_FOUND"),  # D9 : ligne existante hors périmètre
        "DIR": (403, "FORBIDDEN"),
        "ADM": (403, "FORBIDDEN"),
        "ENTR": (403, "FORBIDDEN"),
        "CAND": (403, "FORBIDDEN"),
        "A+ENTR": (200, None),
    },
    "submit": {
        "A": (200, None),
        "B": (200, None),
        "ISB": (404, "NOT_FOUND"),
        "DIR": (403, "FORBIDDEN"),
        "ADM": (403, "FORBIDDEN"),
        "ENTR": (403, "FORBIDDEN"),
        "CAND": (403, "FORBIDDEN"),
        "A+ENTR": (200, None),
    },
    "publish": {
        "A": (403, F4),  # D-B / D-H : le soumetteur ne publie pas
        "B": (200, None),
        "ISB": (404, "NOT_FOUND"),
        "DIR": (200, None),
        "ADM": (403, "FORBIDDEN"),  # D-H : l'admin ne publie jamais
        "ENTR": (403, "FORBIDDEN"),
        "CAND": (403, "FORBIDDEN"),
        "A+ENTR": (403, F4),
    },
    "reject": {
        "A": (403, F4),  # SA-21 F2 : relecteur ≠ auteur
        "B": (200, None),
        "ISB": (404, "NOT_FOUND"),
        "DIR": (200, None),
        "ADM": (403, "FORBIDDEN"),
        "ENTR": (403, "FORBIDDEN"),
        "CAND": (403, "FORBIDDEN"),
        "A+ENTR": (403, F4),
    },
    "archive": {
        "A": (200, None),
        "B": (200, None),
        "ISB": (404, "NOT_FOUND"),
        "DIR": (200, None),
        "ADM": (403, "FORBIDDEN"),
        "ENTR": (403, "FORBIDDEN"),
        "CAND": (403, "FORBIDDEN"),
        "A+ENTR": (200, None),
    },
    "revise": {
        "A": (201, None),
        "B": (201, None),
        "ISB": (404, "NOT_FOUND"),
        "DIR": (403, "FORBIDDEN"),
        "ADM": (403, "FORBIDDEN"),
        "ENTR": (403, "FORBIDDEN"),
        "CAND": (403, "FORBIDDEN"),
        "A+ENTR": (201, None),
    },
    "delete": {
        "A": (204, None),
        "B": (204, None),
        "ISB": (404, "NOT_FOUND"),
        "DIR": (403, "FORBIDDEN"),
        "ADM": (403, "FORBIDDEN"),
        "ENTR": (403, "FORBIDDEN"),
        "CAND": (403, "FORBIDDEN"),
        "A+ENTR": (204, None),
    },
}


def caller_headers(w: World, caller: str) -> dict[str, str]:
    return {
        "A": w.h_lead_a,
        "B": w.h_lead_b,
        "ISB": w.h_isb,
        "DIR": w.h_direction,
        "ADM": w.h_admin,
        "CAND": w.h_candidate,
        "ENTR": lambda: headers("interview_lead", user=uuid.uuid4()),
        "A+ENTR": lambda: headers(
            "iit_academic_lead,interview_lead", user=w.lead_a, institution=w.iit
        ),
    }[caller]()


FEES = "/staff/catalogue/fee-schedules"


async def etag_of(api, w: World, url: str) -> str:
    r = await api.get(url, headers=w.h_lead_a())
    assert r.status_code == 200, r.text
    return r.headers["ETag"]


async def perform(api, w: World, action: str, h: dict[str, str]) -> Any:
    """Prépare l'état requis par l'action (avec A ou en base) puis l'exécute avec `h`."""
    if action == "create":
        body = {
            "programme_id": str(w.programme),
            "academic_year": "2027-2028",
            "registration_fee": {"amount": "300.000", "currency": "TND"},
            "tuition_fee": {"amount": "6800.000", "currency": "TND"},
            "valid_from": "2027-03-01",
        }
        return await api.post(FEES, json=body, headers=h)

    if action == "delete":
        body = {
            "institution_id": str(w.iit),
            "code": f"DEL-{w.tag}",
            "name_fr": "Formation brouillon à supprimer (fictive)",
            "programme_type": "licence",
            "duration_years": 3,
            "valid_from": "2026-09-01",
        }
        created = await api.post("/staff/catalogue/programmes", json=body, headers=w.h_lead_a())
        assert created.status_code == 201, created.text
        return await api.delete(f"/staff/catalogue/programmes/{created.json()['id']}", headers=h)

    if action == "revise":
        url = f"/staff/catalogue/programmes/{w.programme}/revisions"
        body = {"changes": {"description_fr": "Texte révisé (fictif)."}, "reason_fr": "Mise à jour"}
        return await api.post(url, json=body, headers=h)

    status = {"modify": "draft", "submit": "draft", "publish": "pending_review"}.get(
        action, "pending_review" if action == "reject" else "published"
    )
    row = await w.fee("2027-2028", status, valid_from="2027-03-01")
    await w.commit()
    url = f"{FEES}/{row.id}"
    etag = await etag_of(api, w, url)
    if action == "modify":
        return await api.patch(url, json={"notes_fr": "Modifié"}, headers=h | {"If-Match": etag})
    if action == "submit":
        return await api.post(f"{url}/submit", headers=h | {"If-Match": etag})
    if action == "publish":
        return await api.post(f"{url}/publish", headers=h | {"If-Match": etag})
    if action == "reject":
        return await api.post(f"{url}/reject", json={"reason": "À revoir"}, headers=h)
    return await api.post(f"{url}/archive", json={}, headers=h | {"If-Match": etag})


CASES = [(a, c) for a in ACTIONS for c in CALLERS]


@pytest.mark.parametrize(("action", "caller"), CASES, ids=[f"{a}-{c}" for a, c in CASES])
async def test_matrice_des_roles(api, world: World, action: str, caller: str):
    expected_status, expected_code = MATRIX[action][caller]
    r = await perform(api, world, action, caller_headers(world, caller))
    assert r.status_code == expected_status, r.text
    if expected_code:
        err = r.json()["error"]
        assert err["code"] == expected_code
        if action == "create" and caller == "ISB":
            assert err["details"] == {"reason": "out_of_scope"}
    if action == "publish" and expected_status == 200:
        published_by = {"B": world.lead_b, "DIR": world.direction}[caller]
        assert r.json()["published_by"] == str(published_by)
        assert r.json()["submitted_by"] == str(world.lead_a)


def test_matrice_complete():
    """Chaque case de la matrice est définie (pas de trou silencieux)."""
    assert set(MATRIX) == set(ACTIONS)
    for action in ACTIONS:
        assert set(MATRIX[action]) == set(CALLERS), action
    # D-H : aucun cas où l'admin publie ou rejette.
    assert MATRIX["publish"]["ADM"][0] == 403 and MATRIX["reject"]["ADM"][0] == 403


async def test_lecture_staff(api, world: World):
    """Lecture staff : IIT (S), ISB (S), Dir. (L), Adm. ; hors périmètre → 404."""
    w = world
    row = await w.fee("2027-2028", "draft", valid_from="2027-03-01")
    await w.commit()
    url = f"{FEES}/{row.id}"
    expected = {"A": 200, "B": 200, "DIR": 200, "ADM": 200, "ISB": 404, "ENTR": 403, "CAND": 403}
    for caller, status in expected.items():
        r = await api.get(url, headers=caller_headers(w, caller))
        assert r.status_code == status, (caller, r.text)
    # Listes : le responsable ISB ne voit pas la ligne IIT.
    r = await api.get(FEES, params={"programme_id": str(w.programme)}, headers=w.h_isb())
    assert r.status_code == 200
    items = r.json()["items"] if isinstance(r.json(), dict) else r.json()
    assert str(row.id) not in {i["id"] for i in items}
