"""Middleware d'idempotence (SA-22) : parties testables sans base de données."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from app.core.db import get_session
from app.core.idempotency import is_mandatory, request_fingerprint
from app.core.security import CurrentUser, Role
from tests.conftest import build_app, dev_headers, make_settings


def user(*roles: Role) -> CurrentUser:
    return CurrentUser(id=uuid.uuid4(), roles=frozenset(roles))


def test_empreinte_json_canonique():
    a = request_fingerprint("POST", "/api/v1/x", b"", b'{"a": 1, "b": {"c": 2, "d": 3}}')
    b = request_fingerprint("post", "/api/v1/x", b"", b'{"b":{"d":3,"c":2},"a":1}')
    assert a == b and len(a) == 32
    assert a != request_fingerprint("POST", "/api/v1/x", b"", b'{"a": 2, "b": {"c": 2, "d": 3}}')
    assert a != request_fingerprint("POST", "/api/v1/y", b"", b'{"a": 1, "b": {"c": 2, "d": 3}}')
    assert a != request_fingerprint("PATCH", "/api/v1/x", b"", b'{"a": 1, "b": {"c": 2, "d": 3}}')


def test_empreinte_parametres_et_corps_non_json():
    assert request_fingerprint("POST", "/p", b"b=2&a=1", b"") == request_fingerprint(
        "POST", "/p", b"a=1&b=2", b""
    )
    assert request_fingerprint("POST", "/p", b"a=1", b"") != request_fingerprint(
        "POST", "/p", b"a=2", b""
    )
    # Corps non JSON : comparé octet par octet ; pas de collision par concaténation.
    assert request_fingerprint("POST", "/p", b"", b"\xff\xfe") != request_fingerprint(
        "POST", "/p", b"", b"\xff"
    )
    assert request_fingerprint("POST", "/ab", b"", b"c") != request_fingerprint(
        "POST", "/a", b"", b"bc"
    )


def test_cle_obligatoire_selon_route_et_role():
    lead = user(Role.IIT_ACADEMIC_LEAD)
    assert is_mandatory("POST", "/staff/catalogue/fee-schedules", lead)
    assert is_mandatory("POST", "/staff/catalogue/fee-schedules/x/publish", user(Role.DIRECTION))
    assert not is_mandatory("PATCH", "/staff/catalogue/fee-schedules/x", lead)
    assert not is_mandatory("POST", "/catalogue/eligibility-check", lead)
    # Rôles refusés par la route : la route répond 403 (ordre SA-5 §1.3), pas 422.
    assert not is_mandatory("POST", "/staff/catalogue/fee-schedules", user(Role.CANDIDATE))
    assert not is_mandatory("POST", "/staff/catalogue/fee-schedules", user(Role.PLATFORM_ADMIN))
    assert is_mandatory(
        "POST", "/staff/catalogue/programmes", user(Role.INTERVIEW_LEAD, Role.ISB_ACADEMIC_LEAD)
    )


def test_transparent_sans_cle_ni_base(client):
    """Sans clé (ou en GET), le middleware ne touche pas à la base."""
    r = client.post("/api/v1/_test/echo", json={"name": "Amal", "age": 20})
    assert r.status_code == 200
    assert "Idempotent-Replayed" not in r.headers
    r = client.get("/api/v1/health", headers={"Idempotency-Key": str(uuid.uuid4())})
    assert r.status_code == 200
    # Anonyme avec clé : pas d'appelant, pas de mémorisation, la route répond.
    r = client.post(
        "/api/v1/_test/echo",
        json={"name": "Amal", "age": 20},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert r.status_code == 200


def test_cle_manquante_ou_invalide_sans_base(client):
    h = dev_headers("iit_academic_lead")
    r = client.post("/api/v1/staff/catalogue/fee-schedules", json={}, headers=h)
    assert r.status_code == 422
    body = r.json()["error"]
    assert body["details"] == [
        {"field": "Idempotency-Key", "issue": "required", "location": "header"}
    ]
    assert body["request_id"] == r.headers["X-Request-ID"]
    r = client.post(
        "/api/v1/_test/echo",
        json={"name": "Amal", "age": 20},
        headers=h | {"Idempotency-Key": "abc"},
    )
    assert r.status_code == 422
    assert r.json()["error"]["details"][0]["issue"] == "uuid_parsing"


def test_base_absente_503():
    """Clé valide d'un appelant identifié mais base injoignable : 503 au format SA-5, la route
    n'est pas exécutée (on ne peut pas garantir l'idempotence)."""
    calls = []
    app = build_app(make_settings())

    @app.post("/api/v1/_test/compte")
    async def compte() -> dict:
        calls.append(1)
        return {"ok": True}

    async def _down():
        raise OSError("connexion refusée")
        yield  # pragma: no cover

    app.dependency_overrides[get_session] = _down
    with TestClient(app) as c:
        r = c.post(
            "/api/v1/_test/compte",
            headers=dev_headers("candidate") | {"Idempotency-Key": str(uuid.uuid4())},
        )
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
    assert r.headers["Retry-After"] == "5"
    assert r.json()["error"]["request_id"] == r.headers["X-Request-ID"]
    assert calls == []
