"""Contrat SA-5 vérifié sur **toutes** les routes, à partir de `app.openapi()` (SA-22).

Pour chaque opération déclarée :
- route staff (`/staff/...`) : visiteur → 401 UNAUTHENTICATED, candidat → 403 FORBIDDEN,
  responsable entretiens (absent de la matrice catalogue) → 403 ;
- route publique (`/catalogue/...`, `/health`) : répond sans authentification (jamais 401/403) ;
- toute erreur a l'enveloppe `{"error": {code, message, details, request_id}}` et
  `request_id` = en-tête `X-Request-ID` ;
- documentation : chaque POST staff déclare `Idempotency-Key`, chaque PATCH staff `If-Match`
  (SA-5 §1.6), chaque route staff documente 401 et 403.

La liste est générée : une route ajoutée demain est vérifiée sans écrire de test.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

import httpx
import pytest

from app.core.errors import ErrorCode
from tests.conftest import shared_app

pytestmark = pytest.mark.db

PREFIX = "/api/v1"
_OPENAPI: dict[str, Any] = shared_app().openapi()


def _operations() -> list[tuple[str, str, dict[str, Any]]]:
    ops = []
    for path, methods in _OPENAPI["paths"].items():
        if "/_test/" in path:
            continue
        for method, op in methods.items():
            ops.append((method.upper(), path.removeprefix(PREFIX), op))
    return ops


OPERATIONS = _operations()
STAFF = [(m, p, op) for m, p, op in OPERATIONS if p.startswith("/staff/")]
PUBLIC = [(m, p, op) for m, p, op in OPERATIONS if not p.startswith("/staff/")]


def _id(op: tuple[str, str, Any]) -> str:
    return f"{op[0]} {op[1]}"


def concrete(path: str) -> str:
    """Remplace chaque `{param}` par un UUID inexistant."""
    return re.sub(r"\{[^}]+\}", lambda _: str(uuid.uuid4()), path)


def assert_error_envelope(r: httpx.Response) -> dict[str, Any]:
    assert r.headers.get("content-type", "").startswith("application/json"), r.text
    body = r.json()
    assert set(body) == {"error"}, body
    err = body["error"]
    assert set(err) == {"code", "message", "details", "request_id"}, err
    assert err["code"] in ErrorCode.__members__, err["code"]
    assert isinstance(err["message"], str) and err["message"]
    assert err["details"] is None or isinstance(err["details"], dict | list)
    assert err["request_id"] == r.headers["X-Request-ID"]
    return err


async def call(api: httpx.AsyncClient, method: str, path: str, **kw: Any) -> httpx.Response:
    return await api.request(method, concrete(path), **kw)


def h(*roles: str) -> dict[str, str]:
    return {"X-Dev-User-Id": str(uuid.uuid4()), "X-Dev-Roles": ",".join(roles)}


def test_inventaire_des_routes():
    """Garde-fou : le catalogue SA-20/SA-21 est bien exposé (sinon la suite ne prouve rien)."""
    assert len(STAFF) >= 90
    assert len(PUBLIC) >= 9
    assert {p for _, p, _ in PUBLIC} >= {
        "/health",
        "/catalogue/institutions",
        "/catalogue/programmes",
        "/catalogue/programmes/{programme_id}",
        "/catalogue/programmes/{programme_id}/curricula",
        "/catalogue/programmes/{programme_id}/fees",
        "/catalogue/programmes/{programme_id}/admission-conditions",
        "/catalogue/bridges",
        "/catalogue/eligibility-check",
    }


@pytest.mark.parametrize(("method", "path", "op"), STAFF, ids=[_id(o) for o in STAFF])
async def test_route_staff_refuse_visiteur_et_candidat(api, method: str, path: str, op: dict):
    r = await call(api, method, path)
    assert r.status_code == 401, r.text
    assert assert_error_envelope(r)["code"] == "UNAUTHENTICATED"

    for roles in (("candidate",), ("interview_lead",)):
        r = await call(api, method, path, headers=h(*roles))
        assert r.status_code == 403, (roles, r.text)
        assert assert_error_envelope(r)["code"] == "FORBIDDEN"

    # En-têtes d'auth malformés : 401, jamais 500.
    r = await call(api, method, path, headers={"X-Dev-User-Id": "x", "X-Dev-Roles": "direction"})
    assert r.status_code == 401
    assert_error_envelope(r)


@pytest.mark.parametrize(("method", "path", "op"), PUBLIC, ids=[_id(o) for o in PUBLIC])
async def test_route_publique_sans_authentification(api, method: str, path: str, op: dict):
    kw: dict[str, Any] = {"json": {}} if method == "POST" else {}
    r = await call(api, method, path, **kw)
    assert r.status_code not in (401, 403), r.text
    # /health/ready : 503 attendu, l'application de test n'a pas de DATABASE_URL (SA-7).
    assert r.status_code < 500 or (path == "/health/ready" and r.status_code == 503), r.text
    assert "X-Request-ID" in r.headers
    if r.status_code >= 400:
        assert_error_envelope(r)
    # Un candidat connecté voit la même chose (aucune route publique ne dépend du rôle).
    r2 = await call(api, method, path, headers=h("candidate"), **kw)
    assert r2.status_code not in (401, 403)


def _header_names(op: dict) -> set[str]:
    return {p["name"] for p in op.get("parameters", []) if p["in"] == "header"}


@pytest.mark.parametrize(
    ("method", "path", "op"),
    [(m, p, op) for m, p, op in STAFF if m in ("POST", "PATCH")],
    ids=[_id(o) for o in STAFF if o[0] in ("POST", "PATCH")],
)
def test_documentation_entetes_staff(method: str, path: str, op: dict):
    names = _header_names(op)
    if method == "POST":
        assert "Idempotency-Key" in names, "SA-5 D8 : POST staff « idem. »"
    else:
        assert "If-Match" in names, "SA-5 §1.6 : If-Match obligatoire sur PATCH staff"


@pytest.mark.parametrize(("method", "path", "op"), STAFF, ids=[_id(o) for o in STAFF])
def test_documentation_erreurs_staff(method: str, path: str, op: dict):
    responses = op["responses"]
    assert {"401", "403", "422"} <= set(responses)
    schema = responses["401"]["content"]["application/json"]["schema"]
    assert schema["$ref"].endswith("/ErrorResponse")


async def test_erreurs_generiques_au_format(api):
    """404 inconnue, 405, JSON invalide, paramètres invalides : même enveloppe."""
    r = await api.get("/nexiste/pas")
    assert r.status_code == 404
    assert assert_error_envelope(r)["code"] == "NOT_FOUND"
    r = await api.put("/catalogue/programmes")
    assert r.status_code == 405
    assert assert_error_envelope(r)["code"] == "METHOD_NOT_ALLOWED"
    r = await api.post(
        "/catalogue/eligibility-check",
        content=b"{pas du json",
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 422
    assert assert_error_envelope(r)["code"] == "VALIDATION_ERROR"
    r = await api.get("/catalogue/programmes/pas-un-uuid")
    assert r.status_code == 422
    err = assert_error_envelope(r)
    assert err["details"][0]["field"] == "programme_id"
    assert err["details"][0]["location"] == "path"
    assert "pas-un-uuid" not in r.text
    r = await api.get("/catalogue/programmes", params={"page_size": 1000})
    assert r.status_code == 422
    assert assert_error_envelope(r)["details"][0]["field"] == "page_size"
    # X-Request-ID du client repris s'il est sûr.
    r = await api.get("/catalogue/programmes/x", headers={"X-Request-ID": "req_verif-22"})
    assert r.headers["X-Request-ID"] == "req_verif-22"
    assert r.json()["error"]["request_id"] == "req_verif-22"
