"""SA-29 : rattacher la conversation visiteur au compte candidat (scénarios de Mariem)."""

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
    unique_email,
    visitor_with_messages,
)

pytestmark = pytest.mark.db

TEXTS = ("Je souhaite étudier l'IA", "Quels parcours conseillez-vous ?")


async def attach(browser, auth, session_id, consent=True):
    return await browser.post(
        "/auth/attach-visitor-session",
        json={"visitor_session_id": session_id, "consent": consent},
        headers=bearer(auth),
    )


async def test_offre_accord_et_conversation_deplacee(api, db_conn):
    sid, conv = await visitor_with_messages(api, TEXTS)
    auth = await register(api)
    offer = auth["attach_offer"]
    assert offer["visitor_session_id"] == sid
    assert offer["conversation_count"] == 1 and offer["message_count"] == 2

    r = await attach(api, auth, sid)
    assert r.status_code == 200, r.text
    assert r.json() == {
        "attachment_status": "attached",
        "visitor_session_status": "attached",
        "conversation_ids": [conv],
    }
    # La conversation appartient maintenant au candidat, depuis n'importe quel navigateur.
    async with make_client(db_conn) as other_browser:
        h = bearer(auth)
        listing = (await other_browser.get("/conversations", headers=h)).json()
        assert [c["id"] for c in listing["items"]] == [conv]
        assert listing["items"][0]["owner_type"] == "candidate"
        msgs = (await other_browser.get(f"/conversations/{conv}/messages", headers=h)).json()
        assert [m["text"] for m in msgs["items"]] == list(TEXTS)
    row = (
        await db_conn.execute(
            text(
                "SELECT c.user_id, c.visitor_session_id, c.origin_visitor_session_id,"
                " a.status, a.conversations_moved, k.consent_type, k.granted"
                " FROM conversation c JOIN conversation_attachment a"
                "   ON a.visitor_session_id = c.origin_visitor_session_id"
                " JOIN consent k ON k.id = a.consent_id WHERE c.id = :i"
            ),
            {"i": conv},
        )
    ).one()
    assert str(row.user_id) == auth["user"]["id"] and row.visitor_session_id is None
    assert str(row.origin_visitor_session_id) == sid
    assert (row.status, row.conversations_moved) == ("attached", 1)
    assert (row.consent_type, row.granted) == ("conversation_link", True)
    # L'ancienne session visiteur n'ouvre plus le chat (410) ; elle reste lisible (attached).
    assert (await api.get("/conversations")).status_code == 410
    assert (await api.get("/visitor-sessions/current")).json()["status"] == "attached"


async def test_refus_rien_n_est_deplace(api, db_conn):
    sid, conv = await visitor_with_messages(api, TEXTS)
    auth = await register(api)
    r = await attach(api, auth, sid, consent=False)
    assert r.status_code == 200
    assert r.json()["attachment_status"] == "declined"
    assert r.json()["conversation_ids"] == []
    assert (await api.get("/conversations", headers=bearer(auth))).json()["items"] == []
    # Le refus ne supprime pas la conversation du visiteur.
    msgs = (await api.get(f"/conversations/{conv}/messages")).json()["items"]
    assert len(msgs) == 2
    granted = (
        await db_conn.execute(
            text(
                "SELECT granted FROM consent WHERE visitor_session_id = :s"
                " AND consent_type = 'conversation_link'"
            ),
            {"s": sid},
        )
    ).scalar_one()
    assert granted is False


async def test_consentement_booleen_strict(api):
    sid, _ = await visitor_with_messages(api, TEXTS)
    auth = await register(api)
    h = bearer(auth)
    url = "/auth/attach-visitor-session"
    assert (await api.post(url, json={"visitor_session_id": sid}, headers=h)).status_code == 422
    for consent in ("true", 1):
        body = {"visitor_session_id": sid, "consent": consent}
        assert (await api.post(url, json=body, headers=h)).status_code == 422
    extra = {"visitor_session_id": sid, "consent": True, "user_id": auth["user"]["id"]}
    assert (await api.post(url, json=extra, headers=h)).status_code == 422
    assert (await api.get("/conversations", headers=h)).json()["items"] == []


async def test_jeton_et_cookie_de_la_meme_session_exiges(api, db_conn):
    sid, _ = await visitor_with_messages(api, TEXTS)
    auth = await register(api)
    no_token = await api.post(
        "/auth/attach-visitor-session", json={"visitor_session_id": sid, "consent": True}
    )
    assert no_token.status_code == 401
    async with make_client(db_conn) as foreign_browser:
        # Même compte, autre navigateur : connaître l'identifiant ne suffit pas.
        r = await attach(foreign_browser, auth, sid)
        assert r.status_code == 403 and r.json()["error"]["code"] == "SESSION_NOT_OWNED"
        # Un autre cookie valide ne permet pas de prendre la session du premier navigateur.
        await foreign_browser.post("/visitor-sessions")
        r = await attach(foreign_browser, auth, sid)
        assert r.status_code == 403
    assert (await api.get("/conversations", headers=bearer(auth))).json()["items"] == []
    status = (
        await db_conn.execute(
            text(
                "SELECT status FROM conversation_attachment WHERE visitor_session_id = :s"
                " ORDER BY created_at DESC LIMIT 1"
            ),
            {"s": sid},
        )
    ).scalar_one()
    assert status == "ownership_failed"


async def test_un_seul_proprietaire(api, db_conn):
    sid, conv = await visitor_with_messages(api, TEXTS)
    a = await register(api)
    assert (await attach(api, a, sid)).status_code == 200
    # Le même compte peut renvoyer la demande : sans effet.
    again = await attach(api, a, sid)
    assert again.status_code == 200 and again.json()["conversation_ids"] == [conv]
    # Un autre candidat, même avec le cookie d'origine, ne peut pas la prendre.
    email_b = unique_email()
    async with make_client(db_conn) as browser_b:
        b = await register(browser_b, email_b)
        browser_b.cookies.set("sc_visitor", "x")  # cookie inconnu
        assert (await attach(browser_b, b, sid)).status_code == 403
        assert (await browser_b.get(f"/conversations/{conv}", headers=bearer(b))).status_code == 404


async def test_session_deja_rattachee_a_un_autre_compte(api, db_conn):
    sid, _ = await visitor_with_messages(api, TEXTS)
    token = api.cookies["sc_visitor"]
    a = await register(api)
    assert (await attach(api, a, sid)).status_code == 200
    async with make_client(db_conn) as browser_b:
        browser_b.cookies.set("sc_visitor", token)  # cookie copié
        b = await register(browser_b)
        r = await attach(browser_b, b, sid)
        assert r.status_code == 409 and r.json()["error"]["code"] == "ALREADY_ATTACHED"


async def test_session_expiree(api, db_conn):
    sid, _ = await visitor_with_messages(api, TEXTS)
    auth = await register(api)
    await db_conn.execute(
        text(
            "UPDATE visitor_session SET idle_expires_at = now() - interval '1 second' WHERE id = :i"
        ),
        {"i": sid},
    )
    r = await attach(api, auth, sid)
    assert r.status_code == 410 and r.json()["error"]["code"] == "SESSION_EXPIRED"
    assert (await api.get("/conversations", headers=bearer(auth))).json()["items"] == []


async def test_pas_d_offre_sans_conversation(api):
    await api.post("/visitor-sessions")
    auth = await register(api)
    assert auth["attach_offer"] is None


async def test_offre_a_la_connexion_candidat_seulement(api, db_conn):
    email = unique_email()
    async with make_client(db_conn) as setup:
        await register(setup, email)
    sid, _ = await visitor_with_messages(api, TEXTS)
    auth = await login(api, email)
    assert auth["attach_offer"]["visitor_session_id"] == sid
    staff_email = unique_email("direction")
    await create_account(db_conn, staff_email, ("direction",))
    r = await api.post("/auth/login", json={"email": staff_email, "password": PASSWORD})
    assert r.json()["attach_offer"] is None
    staff = r.json()
    forbidden = await attach(api, staff, sid)
    assert forbidden.status_code == 403 and forbidden.json()["error"]["code"] == "FORBIDDEN"
