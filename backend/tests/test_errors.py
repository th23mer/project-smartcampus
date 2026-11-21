"""Format d'erreur unique SA-5 : 404, 405, 422, 500, AppError."""

from app.core.errors import ERROR_CATALOGUE, AppError, ErrorCode


def _assert_error_shape(body: dict, code: str, request_id: str) -> dict:
    assert set(body) == {"error"}
    err = body["error"]
    assert set(err) == {"code", "message", "details", "request_id"}
    assert err["code"] == code
    assert err["request_id"] == request_id
    return err


def test_unknown_route_404(client):
    r = client.get("/api/v1/inexistant")
    assert r.status_code == 404
    err = _assert_error_shape(r.json(), "NOT_FOUND", r.headers["X-Request-ID"])
    assert err["message"] == "Ressource introuvable."
    assert err["details"] is None


def test_method_not_allowed_405(client):
    r = client.delete("/api/v1/health")
    assert r.status_code == 405
    _assert_error_shape(r.json(), "METHOD_NOT_ALLOWED", r.headers["X-Request-ID"])


def test_validation_error_body_422(client):
    r = client.post("/api/v1/_test/echo", json={"age": "pas un nombre"})
    assert r.status_code == 422
    err = _assert_error_shape(r.json(), "VALIDATION_ERROR", r.headers["X-Request-ID"])
    assert err["message"] == "Les données envoyées sont invalides."
    fields = {d["field"]: d for d in err["details"]}
    assert fields["name"]["issue"] == "required"
    assert fields["name"]["location"] == "body"
    assert fields["age"]["issue"] == "int_parsing"
    # La valeur saisie n'est jamais renvoyée.
    assert "pas un nombre" not in r.text


def test_validation_error_query_422(client):
    r = client.get("/api/v1/_test/items", params={"page_size": 101})
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["details"][0]["field"] == "page_size"
    assert err["details"][0]["location"] == "query"


def test_internal_error_500_without_trace(client):
    r = client.get("/api/v1/_test/boom")
    assert r.status_code == 500
    err = _assert_error_shape(r.json(), "INTERNAL_ERROR", r.headers["X-Request-ID"])
    assert err["details"] is None
    assert "secret" not in r.text
    assert "Traceback" not in r.text
    assert "RuntimeError" not in r.text


def test_app_error(client):
    r = client.get("/api/v1/_test/app-error")
    assert r.status_code == 409
    err = _assert_error_shape(r.json(), "INVALID_STATUS_TRANSITION", r.headers["X-Request-ID"])
    assert err["details"]["allowed"] == ["submitted", "withdrawn"]


def test_catalogue_complete():
    # Chaque code a un statut HTTP et un message français.
    assert set(ERROR_CATALOGUE) == set(ErrorCode)
    assert len(ErrorCode) == 42
    e = AppError(
        ErrorCode.ACADEMIC_YEAR_REQUIRED, details={"available_academic_years": ["2026-2027"]}
    )
    assert e.http_status == 422
    assert e.message == "Précisez l'année universitaire."
