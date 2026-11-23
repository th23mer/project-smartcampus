"""Outils communs des tests E3 (SA-25, SA-26, SA-28, SA-29), inspirés des scénarios de Mariem.

Chaque client httpx joue le rôle d'un **navigateur** (il garde ses cookies). Plusieurs
navigateurs partagent la même connexion de test (transaction annulée à la fin).
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.passwords import hash_password

PASSWORD = "MotDePasseDeTest!2026"


def unique_email(prefix: str = "candidat") -> str:
    return f"{prefix}.{uuid.uuid4().hex[:10]}@example.com"


def register_body(email: str, **over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "email": email,
        "password": PASSWORD,
        "full_name": "Candidat Fictif",
        "consents": {"terms_accepted": True, "data_processing": True},
    }
    body.update(over)
    return body


async def register(browser: httpx.AsyncClient, email: str | None = None) -> dict[str, Any]:
    r = await browser.post("/auth/register", json=register_body(email or unique_email()))
    assert r.status_code == 201, r.text
    return r.json()


def bearer(auth: dict[str, Any]) -> dict[str, str]:
    return {"Authorization": f"Bearer {auth['access_token']}"}


async def visitor_with_messages(
    browser: httpx.AsyncClient, texts: tuple[str, ...] = ("Je souhaite étudier l'IA",)
) -> tuple[str, str]:
    """Session visiteur + une conversation contenant `texts` (réponses : secours 503)."""
    r = await browser.post("/visitor-sessions", json={"locale": "fr"})
    assert r.status_code in (200, 201), r.text
    session_id = r.json()["id"]
    r = await browser.post("/conversations", json={"channel": "web"})
    assert r.status_code == 201, r.text
    conversation_id = r.json()["id"]
    for t in texts:
        r = await send(browser, conversation_id, t)
        assert r.status_code == 503, r.text  # aucun LLM branché : secours déterministe
    return session_id, conversation_id


async def send(
    browser: httpx.AsyncClient,
    conversation_id: str,
    text_: str,
    client_message_id: str | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    return await browser.post(
        f"/conversations/{conversation_id}/messages",
        json={
            "client_message_id": client_message_id or str(uuid.uuid4()),
            "content": {"type": "text", "text": text_},
        },
        headers=headers,
    )


async def ensure_role(conn: AsyncConnection, code: str, is_staff: bool = True) -> uuid.UUID:
    await conn.execute(
        text(
            "INSERT INTO role (code, label, is_staff) VALUES (:c, :c, :s)"
            " ON CONFLICT (code) DO NOTHING"
        ),
        {"c": code, "s": is_staff},
    )
    return (
        await conn.execute(text("SELECT id FROM role WHERE code = :c"), {"c": code})
    ).scalar_one()


async def create_account(
    conn: AsyncConnection,
    email: str,
    roles: tuple[str, ...],
    *,
    account_type: str = "staff",
    status: str = "active",
) -> uuid.UUID:
    """Compte créé directement en base (comme `scripts/create_staff.py`)."""
    user_id = (
        await conn.execute(
            text(
                "INSERT INTO user_account (email, password_hash, full_name, account_type,"
                " account_status) VALUES (:e, :h, 'Compte Fictif', :t, :s) RETURNING id"
            ),
            {"e": email, "h": hash_password(PASSWORD), "t": account_type, "s": status},
        )
    ).scalar_one()
    for code in roles:
        role_id = await ensure_role(conn, code, is_staff=code != "candidate")
        await conn.execute(
            text("INSERT INTO user_role (user_id, role_id) VALUES (:u, :r)"),
            {"u": user_id, "r": role_id},
        )
    return user_id


async def login(browser: httpx.AsyncClient, email: str) -> dict[str, Any]:
    r = await browser.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return r.json()
