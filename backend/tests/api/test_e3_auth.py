"""SA-28 : inscription, connexion, jetons, rôles (scénarios de Mariem sur notre socle)."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from tests.api.conftest import make_client
from tests.api.e3_helpers import (
    PASSWORD,
    bearer,
    create_account,
    login,
    register,
    register_body,
    unique_email,
)

pytestmark = pytest.mark.db


async def test_inscription_publique_cree_un_candidat(api, db_conn):
    email = unique_email()
    auth = await register(api, email.upper())  # e-mail normalisé en minuscules
    user = auth["user"]
    assert user["email"] == email and user["roles"] == ["candidate"]
    assert user["account_type"] == "candidate"
    assert auth["token_type"] == "Bearer" and auth["expires_in"] == 900
    assert auth["attach_offer"] is None
    row = (
        await db_conn.execute(
            text("SELECT password_hash FROM user_account WHERE id = :i"), {"i": user["id"]}
        )
    ).scalar_one()
    assert row.startswith("$argon2id$") and PASSWORD not in row
    consents = (
        (
            await db_conn.execute(
                text("SELECT consent_type FROM consent WHERE user_id = :i AND granted ORDER BY 1"),
                {"i": user["id"]},
            )
        )
        .scalars()
        .all()
    )
    assert consents == ["data_processing", "terms_accepted"]


async def test_inscription_refusee(api):
    email = unique_email()
    await register(api, email)
    dup = await api.post("/auth/register", json=register_body(email))
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "EMAIL_ALREADY_USED"
    no_consent = await api.post(
        "/auth/register",
        json=register_body(
            unique_email(), consents={"terms_accepted": True, "data_processing": False}
        ),
    )
    assert no_consent.status_code == 422
    assert no_consent.json()["error"]["code"] == "CONSENT_REQUIRED"
    short = await api.post("/auth/register", json=register_body(unique_email(), password="court"))
    assert short.status_code == 422
    bad_email = await api.post("/auth/register", json=register_body("pas-un-email"))
    assert bad_email.status_code == 422
    # Personne ne peut s'inscrire comme staff : le champ « roles » est refusé.
    staff = await api.post(
        "/auth/register", json=register_body(unique_email(), roles=["direction"])
    )
    assert staff.status_code == 422


async def test_connexion_et_me(api):
    email = unique_email()
    await register(api, email)
    auth = await login(api, email)
    me = await api.get("/auth/me", headers=bearer(auth))
    assert me.status_code == 200 and me.json()["email"] == email
    assert (await api.get("/auth/me")).status_code == 401
    bad = await api.get("/auth/me", headers={"Authorization": "Bearer abc.def.ghi"})
    assert bad.status_code == 401


async def test_identifiants_incorrects_meme_reponse(api):
    email = unique_email()
    await register(api, email)
    wrong = await api.post("/auth/login", json={"email": email, "password": "mauvais-mdp-123"})
    unknown = await api.post(
        "/auth/login", json={"email": unique_email(), "password": "mauvais-mdp-123"}
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["error"]["code"] == unknown.json()["error"]["code"] == "INVALID_CREDENTIALS"


async def test_cinq_echecs_bloquent_la_connexion(api):
    email = unique_email()
    await register(api, email)
    for _ in range(5):
        r = await api.post("/auth/login", json={"email": email, "password": "mauvais-mdp-123"})
        assert r.status_code == 401
    blocked = await api.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "RATE_LIMITED"
    assert int(blocked.headers["Retry-After"]) > 0


async def test_compte_desactive(api, db_conn):
    email = unique_email("desactive")
    await create_account(
        db_conn, email, ("candidate",), account_type="candidate", status="disabled"
    )
    r = await api.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 403 and r.json()["error"]["code"] == "ACCOUNT_DISABLED"


async def test_roles_stricts_candidat_et_staff(api, db_conn):
    """Un candidat n'accède pas aux routes staff ; un responsable n'accède pas au chat candidat."""
    cand = await register(api)
    r = await api.get("/staff/catalogue/programmes", headers=bearer(cand))
    assert r.status_code == 403 and r.json()["error"]["code"] == "FORBIDDEN"

    email = unique_email("resp.iit")
    await create_account(db_conn, email, ("iit_academic_lead",))
    staff = await login(api, email)
    assert staff["user"]["account_type"] == "staff" and staff["attach_offer"] is None
    assert (await api.get("/staff/catalogue/programmes", headers=bearer(staff))).status_code == 200
    assert (await api.get("/conversations", headers=bearer(staff))).status_code == 403
    me = (await api.get("/auth/me", headers=bearer(staff))).json()
    assert me["roles"] == ["iit_academic_lead"]


async def test_refresh_rotation_et_reutilisation(api, db_conn):
    await register(api)
    old_cookie = api.cookies["sc_refresh"]
    r = await api.post("/auth/refresh")
    assert r.status_code == 200, r.text
    assert r.json()["expires_in"] == 900
    new_cookie = api.cookies["sc_refresh"]
    assert new_cookie != old_cookie
    me = await api.get("/auth/me", headers=bearer(r.json()))
    assert me.status_code == 200
    # Ancien cookie rejoué (vol) : refusé, et toute la famille est révoquée.
    async with make_client(db_conn) as thief:
        thief.cookies.set("sc_refresh", old_cookie, path="/api/v1/auth")
        assert (await thief.post("/auth/refresh")).status_code == 401
    assert (await api.post("/auth/refresh")).status_code == 401


async def test_logout_revoque_le_cookie(api):
    auth = await register(api)
    r = await api.post("/auth/logout", headers=bearer(auth))
    assert r.status_code == 204
    assert (await api.post("/auth/refresh")).status_code == 401


async def test_refresh_sans_cookie(api):
    r = await api.post("/auth/refresh")
    assert r.status_code == 401 and r.json()["error"]["code"] == "UNAUTHENTICATED"
