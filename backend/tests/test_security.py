"""Authentification simulée (en-têtes X-Dev-*) et contrôle des rôles."""

import uuid

import pytest

from app.core.security import require_roles
from tests.conftest import dev_headers


def test_anonymous_is_401(client):
    r = client.get("/api/v1/_test/me")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "UNAUTHENTICATED"
    assert r.json()["error"]["message"] == "Authentification requise."


def test_candidate_ok(client):
    uid = uuid.uuid4()
    r = client.get("/api/v1/_test/me", headers=dev_headers("candidate", user_id=uid))
    assert r.status_code == 200
    assert r.json() == {"id": str(uid), "roles": ["candidate"], "account_type": "candidate"}


def test_invalid_headers_401(client):
    r = client.get(
        "/api/v1/_test/me", headers={"X-Dev-User-Id": "pas-un-uuid", "X-Dev-Roles": "candidate"}
    )
    assert r.status_code == 401
    r = client.get("/api/v1/_test/me", headers=dev_headers("super_admin"))
    assert r.status_code == 401
    assert r.json()["error"]["details"]["unknown"] == ["super_admin"]
    r = client.get("/api/v1/_test/me", headers={"X-Dev-User-Id": str(uuid.uuid4())})
    assert r.status_code == 401


def test_wrong_role_is_403(client):
    r = client.get("/api/v1/_test/staff-only", headers=dev_headers("candidate"))
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "FORBIDDEN"


def test_staff_role_ok_with_cumulated_roles(client):
    inst = uuid.uuid4()
    r = client.get(
        "/api/v1/_test/staff-only",
        headers=dev_headers("interview_lead", "iit_academic_lead", institution_id=inst),
    )
    assert r.status_code == 200
    assert r.json() == {"ok": True, "institution_id": str(inst)}


def test_staff_only_anonymous_is_401(client):
    assert client.get("/api/v1/_test/staff-only").status_code == 401


def test_dev_auth_disabled_in_prod(prod_client):
    r = prod_client.get("/api/v1/_test/me", headers=dev_headers("direction"))
    assert r.status_code == 401


def test_require_roles_rejects_unknown_role():
    with pytest.raises(ValueError):
        require_roles("roi_du_campus")
    with pytest.raises(ValueError):
        require_roles()
