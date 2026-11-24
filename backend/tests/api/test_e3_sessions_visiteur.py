"""SA-25 : sessions visiteur sans compte (cookie, TTL, quota, isolation, oubli, purge)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from app.services.visitor_sessions import expire_and_purge
from tests.api.conftest import make_client
from tests.api.e3_helpers import send, visitor_with_messages
from tests.conftest import make_settings

pytestmark = pytest.mark.db


async def test_creation_cookie_httponly_et_reutilisation(api):
    r = await api.post("/visitor-sessions", json={"locale": "fr"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "active"
    assert body["quota"]["messages_used"] == 0
    assert body["quota"]["messages_limit"] == 30
    cookie = r.headers["set-cookie"].lower()
    assert "sc_visitor=" in cookie and "httponly" in cookie and "samesite=lax" in cookie
    # Même navigateur : la session est réutilisée, pas de nouvelle session (200).
    again = await api.post("/visitor-sessions")
    assert again.status_code == 200
    assert again.json()["id"] == body["id"]


async def test_expiration_inactivite_24h_et_max_7j(api, db_conn):
    body = (await api.post("/visitor-sessions")).json()
    created = datetime.fromisoformat(body["created_at"])
    expires = datetime.fromisoformat(body["expires_at"])
    assert timedelta(hours=23, minutes=59) < expires - created <= timedelta(hours=24)
    hard = (
        await db_conn.execute(
            text("SELECT hard_expires_at - created_at FROM visitor_session WHERE id = :i"),
            {"i": body["id"]},
        )
    ).scalar_one()
    assert hard == timedelta(days=7)


async def test_jeton_stocke_hache_jamais_en_clair(api, db_conn):
    r = await api.post("/visitor-sessions")
    token = api.cookies["sc_visitor"]
    stored = (
        await db_conn.execute(
            text("SELECT token_hash FROM visitor_session WHERE id = :i"), {"i": r.json()["id"]}
        )
    ).scalar_one()
    assert len(stored) == 32 and token.encode() not in bytes(stored)


async def test_sans_cookie_401_et_cookie_inconnu_401(api):
    r = await api.get("/visitor-sessions/current")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "UNAUTHENTICATED"
    api.cookies.set("sc_visitor", "jeton-invente")
    assert (await api.get("/visitor-sessions/current")).status_code == 401


async def test_session_expiree_410_puis_nouvelle_session(api, db_conn):
    old = (await api.post("/visitor-sessions")).json()["id"]
    await db_conn.execute(
        text(
            "UPDATE visitor_session SET idle_expires_at = now() - interval '1 second' WHERE id = :i"
        ),
        {"i": old},
    )
    r = await api.get("/visitor-sessions/current")
    assert r.status_code == 410
    assert r.json()["error"]["code"] == "SESSION_EXPIRED"
    status = (
        await db_conn.execute(text("SELECT status FROM visitor_session WHERE id = :i"), {"i": old})
    ).scalar_one()
    assert status == "expired"
    new = await api.post("/visitor-sessions")
    assert new.status_code == 201 and new.json()["id"] != old


async def test_quota_30_messages_par_fenetre(api, db_conn):
    sid, conv = await visitor_with_messages(api, ())
    await db_conn.execute(
        text("UPDATE visitor_session SET message_count = 29 WHERE id = :i"), {"i": sid}
    )
    assert (await send(api, conv, "message 30")).status_code == 503  # accepté, secours LLM
    r = await send(api, conv, "message 31")
    assert r.status_code == 429
    err = r.json()["error"]
    assert err["code"] == "VISITOR_QUOTA_EXCEEDED"
    assert err["details"]["limit"] == 30 and err["details"]["suggestion"] == "create_account"
    assert int(r.headers["Retry-After"]) > 0
    # Le message refusé n'est pas enregistré.
    msgs = (await api.get(f"/conversations/{conv}/messages")).json()["items"]
    assert [m["text"] for m in msgs] == ["message 30"]
    # Fenêtre de 24 h écoulée : le compteur repart à zéro.
    await db_conn.execute(
        text(
            "UPDATE visitor_session SET quota_window_start = now() - interval '25 hours'"
            " WHERE id = :i"
        ),
        {"i": sid},
    )
    assert (await send(api, conv, "nouvelle fenêtre")).status_code == 503
    quota = (await api.get("/visitor-sessions/current")).json()["quota"]
    assert quota["messages_used"] == 1


async def test_isolation_entre_visiteurs(api, db_conn):
    _, conv = await visitor_with_messages(api, ("secret visiteur 1",))
    async with make_client(db_conn) as other:
        await other.post("/visitor-sessions")
        assert (await other.get(f"/conversations/{conv}")).status_code == 404
        assert (await other.get(f"/conversations/{conv}/messages")).status_code == 404
        assert (await send(other, conv, "intrusion")).status_code == 404
        assert (await other.get("/conversations")).json()["meta"]["total_items"] == 0


async def test_oublier_ma_session(api, db_conn):
    sid, conv = await visitor_with_messages(api)
    r = await api.delete("/visitor-sessions/current")
    assert r.status_code == 204
    row = (
        await db_conn.execute(
            text("SELECT status, purged_at FROM visitor_session WHERE id = :i"), {"i": sid}
        )
    ).one()
    assert row.status == "purged" and row.purged_at is not None
    count = (
        await db_conn.execute(text("SELECT count(*) FROM conversation WHERE id = :i"), {"i": conv})
    ).scalar_one()
    assert count == 0
    assert (await api.get("/visitor-sessions/current")).status_code == 401


async def test_purge_30_jours_apres_expiration(api, db_conn, db_session):
    sid, conv = await visitor_with_messages(api)
    past = datetime.now(UTC) - timedelta(days=31)
    await db_conn.execute(
        text(
            "UPDATE visitor_session SET idle_expires_at = :p, hard_expires_at = :p,"
            " created_at = :c WHERE id = :i"
        ),
        {"p": past, "c": past - timedelta(hours=1), "i": sid},
    )
    report = await expire_and_purge(db_session, make_settings())
    assert report.expired >= 1 and report.purged >= 1
    status = (
        await db_conn.execute(text("SELECT status FROM visitor_session WHERE id = :i"), {"i": sid})
    ).scalar_one()
    assert status == "purged"
    gone = (
        await db_conn.execute(text("SELECT count(*) FROM conversation WHERE id = :i"), {"i": conv})
    ).scalar_one()
    assert gone == 0
