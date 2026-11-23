"""SA-28 : briques de l'authentification sans base (JWT, Argon2id, limiteur, cookies)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.core.errors import AppError
from app.core.passwords import hash_password, verify_password
from app.core.rate_limit import FailureLimiter
from app.core.tokens import create_access_token, decode_access_token, hash_opaque_token
from tests.conftest import make_settings


def _token(settings, **kw):
    return create_access_token(
        settings,
        user_id=kw.get("user_id", uuid.uuid4()),
        account_type="candidate",
        roles=kw.get("roles", ["candidate"]),
        candidate_id=None,
        institution_id=None,
        now=kw.get("now"),
    )


def test_jwt_aller_retour():
    settings = make_settings()
    uid = uuid.uuid4()
    claims = decode_access_token(settings, _token(settings, user_id=uid))
    assert claims.user_id == uid and claims.roles == ("candidate",)


def test_jwt_expire_ou_mauvais_secret():
    settings = make_settings()
    old = _token(settings, now=datetime.now(UTC) - timedelta(minutes=16))
    with pytest.raises(AppError) as exc:
        decode_access_token(settings, old)
    assert exc.value.details == {"reason": "token_expired"}
    other = make_settings(jwt_secret="un-autre-secret-de-test-assez-long-0123456789")
    with pytest.raises(AppError):
        decode_access_token(other, _token(settings))


def test_secret_trop_court_refuse_et_vide_ignore():
    with pytest.raises(ValueError):
        make_settings(jwt_secret="court")
    assert make_settings(jwt_secret="").jwt_secret is None


def test_bearer_sur_route_protegee(client):
    settings = make_settings()
    r = client.get("/api/v1/_test/me", headers={"Authorization": f"Bearer {_token(settings)}"})
    assert r.status_code == 200 and r.json()["roles"] == ["candidate"]
    r = client.get("/api/v1/_test/me", headers={"Authorization": "Basic abc"})
    assert r.status_code == 401


def test_argon2id():
    encoded = hash_password("MotDePasse-2026")
    assert encoded.startswith("$argon2id$")
    assert verify_password("MotDePasse-2026", encoded)
    assert not verify_password("autre", encoded)
    assert not verify_password("x", "!seed-sa18-pas-de-connexion")
    assert not verify_password("x", None)


def test_limiteur_fenetre_glissante():
    limiter = FailureLimiter(max_failures=2, window_s=10)
    limiter.record_failure("k", now=0)
    assert limiter.retry_after("k", now=1) is None
    limiter.record_failure("k", now=1)
    assert limiter.retry_after("k", now=2) is not None
    assert limiter.retry_after("k", now=11) is None  # le premier échec est sorti de la fenêtre
    limiter.reset("k")
    assert limiter.retry_after("k", now=2) is None


def test_cookies_secure_hors_dev():
    assert make_settings().cookies_secure is False
    assert make_settings(app_env="prod").cookies_secure is True
    assert make_settings(app_env="prod", cookie_secure=False).cookies_secure is False


def test_jeton_opaque_hache():
    assert len(hash_opaque_token("abc")) == 32
