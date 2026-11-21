"""En-tête X-Request-ID et pagination."""

import re


def test_request_id_generated(client):
    r = client.get("/api/v1/health")
    assert re.fullmatch(r"req_[0-9a-f]{32}", r.headers["X-Request-ID"])


def test_request_id_propagated(client):
    r = client.get("/api/v1/inexistant", headers={"X-Request-ID": "req_client-123"})
    assert r.headers["X-Request-ID"] == "req_client-123"
    assert r.json()["error"]["request_id"] == "req_client-123"


def test_unsafe_request_id_replaced(client):
    r = client.get("/api/v1/health", headers={"X-Request-ID": "<script>alert(1)</script>"})
    assert r.headers["X-Request-ID"].startswith("req_")


def test_request_id_on_500(client):
    r = client.get("/api/v1/_test/boom", headers={"X-Request-ID": "trace-500"})
    assert r.headers["X-Request-ID"] == "trace-500"
    assert r.json()["error"]["request_id"] == "trace-500"


def test_cors_exposes_request_id(client):
    r = client.get("/api/v1/health", headers={"Origin": "http://localhost:3000"})
    assert r.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "X-Request-ID" in r.headers["access-control-expose-headers"]


def test_pagination_envelope(client):
    r = client.get("/api/v1/_test/items", params={"page": 3, "page_size": 20})
    assert r.status_code == 200
    body = r.json()
    assert body["items"] == [41, 42, 43, 44, 45]
    assert body["meta"] == {"page": 3, "page_size": 20, "total_items": 45, "total_pages": 3}
