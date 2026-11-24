"""SA-26 : conversations et mémoire conversationnelle (messages, contexte borné, idempotence)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from app.services import chat
from app.services.chat import AssistantReply
from app.services.conversations import memory_context
from tests.api.e3_helpers import bearer, register, send, visitor_with_messages

pytestmark = pytest.mark.db


class EchoResponder:
    """Agent factice (E4 branchera le vrai) : répète le dernier message et la taille du contexte."""

    def __init__(self) -> None:
        self.contexts: list[list[dict[str, str]]] = []

    async def reply(self, session, caller, conversation, user_message, context):
        self.contexts.append(context)
        return AssistantReply(text=f"Écho : {user_message.content}", reply_language="fr")


@pytest.fixture
def echo():
    responder = EchoResponder()
    chat.set_chat_responder(responder)
    yield responder
    chat.set_chat_responder(None)


async def test_historique_et_contexte(api, echo):
    _, conv = await visitor_with_messages(api, ())
    r = await send(api, conv, "J'aime la programmation")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user_message"]["text"] == "J'aime la programmation"
    assert body["assistant_message"]["text"] == "Écho : J'aime la programmation"
    assert body["quota"]["messages_used"] == 1
    await send(api, conv, "Quelle formation ?")
    msgs = (await api.get(f"/conversations/{conv}/messages")).json()["items"]
    assert [(m["role"], m["text"]) for m in msgs] == [
        ("user", "J'aime la programmation"),
        ("assistant", "Écho : J'aime la programmation"),
        ("user", "Quelle formation ?"),
        ("assistant", "Écho : Quelle formation ?"),
    ]
    # Le contexte transmis à l'agent contient l'historique, dans l'ordre, avec le message courant.
    assert echo.contexts[-1][-1] == {"role": "user", "content": "Quelle formation ?"}
    assert len(echo.contexts[-1]) == 3
    conversation = (await api.get(f"/conversations/{conv}")).json()
    assert conversation["message_count"] == 4 and conversation["owner_type"] == "visitor"


async def test_contexte_borne_aux_20_derniers(api, db_session, echo):
    _, conv = await visitor_with_messages(api, ())
    for i in range(12):  # 24 messages (12 utilisateur + 12 assistant)
        assert (await send(api, conv, f"message {i}")).status_code == 200
    context = await memory_context(db_session, uuid.UUID(conv), 20)
    assert len(context) == 20
    assert context[0] == {"role": "user", "content": "message 2"}
    assert context[-1] == {"role": "assistant", "content": "Écho : message 11"}


async def test_pagination_par_curseur(api, echo):
    _, conv = await visitor_with_messages(api, ())
    for i in range(3):
        await send(api, conv, f"m{i}")
    page1 = (await api.get(f"/conversations/{conv}/messages", params={"limit": 4})).json()
    assert [m["text"] for m in page1["items"]] == ["m1", "Écho : m1", "m2", "Écho : m2"]
    cursor = page1["meta"]["next_cursor"]
    assert cursor is not None
    page2 = (
        await api.get(f"/conversations/{conv}/messages", params={"limit": 4, "before": cursor})
    ).json()
    assert [m["text"] for m in page2["items"]] == ["m0", "Écho : m0"]
    assert page2["meta"]["next_cursor"] is None
    bad = await api.get(f"/conversations/{conv}/messages", params={"before": "abc"})
    assert bad.status_code == 422


async def test_reessai_meme_client_message_id(api, echo):
    _, conv = await visitor_with_messages(api, ())
    cid = str(uuid.uuid4())
    first = await send(api, conv, "bonjour", client_message_id=cid)
    again = await send(api, conv, "bonjour", client_message_id=cid)
    assert again.status_code == 200
    assert again.json()["user_message"]["id"] == first.json()["user_message"]["id"]
    assert again.json()["assistant_message"]["id"] == first.json()["assistant_message"]["id"]
    assert len(echo.contexts) == 1  # le LLM n'est pas rappelé
    assert (await api.get(f"/conversations/{conv}")).json()["message_count"] == 2
    assert (await api.get("/visitor-sessions/current")).json()["quota"]["messages_used"] == 1
    conflict = await send(api, conv, "autre texte", client_message_id=cid)
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_KEY_CONFLICT"


async def test_validation_du_texte(api):
    _, conv = await visitor_with_messages(api, ())
    assert (await send(api, conv, "   ")).status_code == 422
    assert (await send(api, conv, "x" * 2001)).status_code == 422
    assert (await api.get("/visitor-sessions/current")).json()["quota"]["messages_used"] == 0


async def test_sans_llm_secours_deterministe_et_message_conserve(api):
    _, conv = await visitor_with_messages(api, ())
    r = await send(api, conv, "9adech el frais ?")
    assert r.status_code == 503
    assert r.headers["Retry-After"] == "30"
    err = r.json()["error"]
    assert err["code"] == "LLM_UNAVAILABLE"
    fallback = err["details"]["fallback"]
    assert fallback["text"] and fallback["links"] == []
    assert [a["type"] for a in fallback["suggested_actions"]] == ["create_account", "contact_human"]
    msgs = (await api.get(f"/conversations/{conv}/messages")).json()["items"]
    assert [m["text"] for m in msgs] == ["9adech el frais ?"]


async def test_conversation_fermee(api, db_conn):
    _, conv = await visitor_with_messages(api, ())
    await db_conn.execute(
        text("UPDATE conversation SET status = 'closed' WHERE id = :i"), {"i": conv}
    )
    r = await send(api, conv, "encore là ?")
    assert r.status_code == 409 and r.json()["error"]["code"] == "CONVERSATION_CLOSED"


async def test_candidat_a_ses_conversations_sans_quota(api, echo):
    auth = await register(api)
    h = bearer(auth)
    conv = (await api.post("/conversations", json={}, headers=h)).json()
    assert conv["owner_type"] == "candidate"
    r = await send(api, conv["id"], "bonjour", headers=h)
    assert r.status_code == 200 and r.json()["quota"] is None
    listing = (await api.get("/conversations", headers=h)).json()
    assert [c["id"] for c in listing["items"]] == [conv["id"]]


async def test_staff_refuse_sur_le_chat(api):
    h = {"X-Dev-User-Id": str(uuid.uuid4()), "X-Dev-Roles": "iit_academic_lead"}
    assert (await api.get("/conversations", headers=h)).status_code == 403
