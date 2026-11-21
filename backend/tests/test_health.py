"""Sondes /health et /health/ready, documentation OpenAPI."""

import os

import pytest

from tests.conftest import build_app, make_settings


def test_health_ok(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["version"] == "0.1.0"
    assert body["time"].endswith(("Z", "+00:00"))


def test_ready_without_database_is_503(client):
    r = client.get("/api/v1/health/ready")
    assert r.status_code == 503
    err = r.json()["error"]
    assert err["code"] == "SERVICE_UNAVAILABLE"
    assert err["details"] == {"checks": {"database": "not_configured"}}


def test_ready_unreachable_database_is_503():
    from fastapi.testclient import TestClient

    from app.core import db

    db.get_engine.cache_clear()
    db.get_sessionmaker.cache_clear()
    os.environ["DATABASE_URL"] = "postgresql+asyncpg://u:p@127.0.0.1:1/absente"
    try:
        from app.core.config import get_settings

        get_settings.cache_clear()
        settings = make_settings(database_url=os.environ["DATABASE_URL"], db_ready_timeout_s=1.0)
        with TestClient(build_app(settings)) as c:
            r = c.get("/api/v1/health/ready")
        assert r.status_code == 503
        assert r.json()["error"]["details"] == {"checks": {"database": "unreachable"}}
        assert r.headers["Retry-After"] == "5"
    finally:
        os.environ.pop("DATABASE_URL", None)
        get_settings.cache_clear()
        db.get_engine.cache_clear()
        db.get_sessionmaker.cache_clear()


@pytest.mark.db
def test_ready_with_real_database():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL non définie")
    from fastapi.testclient import TestClient

    from app.core import db
    from app.core.config import get_settings

    os.environ["DATABASE_URL"] = url
    get_settings.cache_clear()
    db.get_engine.cache_clear()
    db.get_sessionmaker.cache_clear()
    try:
        with TestClient(build_app(make_settings(database_url=url))) as c:
            r = c.get("/api/v1/health/ready")
        assert r.status_code == 200, r.text
        assert r.json() == {"status": "ok", "checks": {"database": "ok"}}
    finally:
        os.environ.pop("DATABASE_URL", None)
        get_settings.cache_clear()
        db.get_engine.cache_clear()
        db.get_sessionmaker.cache_clear()


def test_openapi_in_french(client):
    r = client.get("/api/v1/openapi.json")
    assert r.status_code == 200
    spec = r.json()
    assert spec["info"]["title"] == "SmartCampus AI — API"
    assert "Format d'erreur unique" in spec["info"]["description"]
    assert "/api/v1/health" in spec["paths"]
    assert "ErrorResponse" in spec["components"]["schemas"]
    assert client.get("/docs").status_code == 200
