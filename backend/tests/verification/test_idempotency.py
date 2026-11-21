"""Middleware d'idempotence commun (SA-22 ; SA-5 §1.6, D8 ; table `idempotency_key`).

Deux niveaux : des routes de test minimales (comportement générique : rejeu, conflit, en cours,
5xx et 403 non mémorisés, expiration, portée par appelant) et les vraies routes du catalogue
staff (clé obligatoire, double création et double publication sans effet).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any

import httpx
import pytest
from fastapi import APIRouter, Body, Response
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from app.core.db import get_session
from app.core.errors import AppError, ErrorCode
from app.core.idempotency import request_fingerprint
from app.models import FeeSchedule, IdempotencyKey
from tests.api.conftest import World, _session, headers
from tests.conftest import build_app, make_settings

pytestmark = pytest.mark.db


Payload = Annotated[dict[str, Any] | None, Body()]


class Counter:
    def __init__(self) -> None:
        self.calls = 0


def _idem_router(counter: Counter) -> APIRouter:
    router = APIRouter(prefix="/_idem")

    @router.post("/ok", status_code=201)
    async def ok(response: Response, payload: Payload = None) -> dict:
        counter.calls += 1
        response.headers["ETag"] = f'W/"v{counter.calls}"'
        response.headers["Location"] = f"/api/v1/_idem/ok/{counter.calls}"
        return {"n": counter.calls, "echo": payload or {}}

    @router.post("/other", status_code=201)
    async def other(payload: Payload = None) -> dict:
        counter.calls += 1
        return {"n": counter.calls}

    @router.post("/boom")
    async def boom() -> None:
        counter.calls += 1
        raise RuntimeError("panne simulée")

    @router.post("/forbidden")
    async def forbidden() -> None:
        counter.calls += 1
        raise AppError(ErrorCode.FORBIDDEN)

    @router.post("/conflict")
    async def conflict() -> None:
        counter.calls += 1
        raise AppError(ErrorCode.CONFLICT, details={"n": counter.calls})

    @router.post("/text")
    async def text_route() -> PlainTextResponse:
        counter.calls += 1
        return PlainTextResponse("ok")

    @router.delete("/item", status_code=204)
    async def delete_item() -> Response:
        counter.calls += 1
        return Response(status_code=204)

    return router


@pytest.fixture
async def idem(db_conn: AsyncConnection) -> AsyncIterator[tuple[httpx.AsyncClient, Counter]]:
    counter = Counter()
    settings = make_settings()
    app = build_app(settings)
    app.include_router(_idem_router(counter), prefix=settings.api_prefix)

    async def _override() -> AsyncIterator[AsyncSession]:
        session = _session(db_conn)
        try:
            yield session
        finally:
            await session.close()

    app.dependency_overrides[get_session] = _override
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test/api/v1") as client:
        yield client, counter


def key() -> dict[str, str]:
    return {"Idempotency-Key": str(uuid.uuid4())}


async def rows(session: AsyncSession, user: uuid.UUID) -> list[IdempotencyKey]:
    session.expire_all()
    return list(await session.scalars(select(IdempotencyKey).where(IdempotencyKey.user_id == user)))


def assert_envelope(r: httpx.Response, code: str) -> dict:
    body = r.json()
    assert set(body) == {"error"}
    err = body["error"]
    assert set(err) == {"code", "message", "details", "request_id"}
    assert err["code"] == code
    assert err["request_id"] == r.headers["X-Request-ID"]
    return err


# --- Comportement générique ------------------------------------------------------------------


async def test_rejeu_meme_cle_meme_corps(idem, world: World, db_session: AsyncSession):
    client, counter = idem
    h = world.h_lead_a() | key()
    r1 = await client.post("/_idem/ok", json={"a": 1, "b": [1, 2]}, headers=h)
    assert r1.status_code == 201
    assert "Idempotent-Replayed" not in r1.headers

    # Même corps, clés JSON dans un autre ordre : même empreinte, réponse rejouée.
    r2 = await client.post("/_idem/ok", json={"b": [1, 2], "a": 1}, headers=h)
    assert r2.status_code == 201
    assert r2.json() == r1.json() == {"n": 1, "echo": {"a": 1, "b": [1, 2]}}
    assert r2.headers["Idempotent-Replayed"] == "true"
    assert r2.headers["ETag"] == r1.headers["ETag"]
    assert r2.headers["Location"] == r1.headers["Location"]
    assert r2.headers["X-Request-ID"] != r1.headers["X-Request-ID"]
    assert counter.calls == 1

    [row] = await rows(db_session, world.lead_a)
    assert row.state == "completed"
    assert row.response_status == 201
    assert row.method == "POST"
    assert row.route == "/api/v1/_idem/ok"
    assert row.response_body["body"] == {"n": 1, "echo": {"a": 1, "b": [1, 2]}}
    ttl = await db_session.scalar(
        select(func.extract("epoch", IdempotencyKey.expires_at - IdempotencyKey.created_at)).where(
            IdempotencyKey.id == row.id
        )
    )
    assert abs(float(ttl) - 24 * 3600) < 5


async def test_meme_cle_corps_different_conflit(idem, world: World, db_session: AsyncSession):
    client, counter = idem
    h = world.h_lead_a() | key()
    assert (await client.post("/_idem/ok", json={"a": 1}, headers=h)).status_code == 201
    r = await client.post("/_idem/ok", json={"a": 2}, headers=h)
    assert r.status_code == 409
    err = assert_envelope(r, "IDEMPOTENCY_KEY_CONFLICT")
    assert err["details"] == {"reason": "request_mismatch", "header": "Idempotency-Key"}
    # La valeur saisie n'est jamais renvoyée.
    assert '"a": 2' not in r.text and '"a":2' not in r.text
    # Même clé sur une autre route ou avec d'autres paramètres : conflit aussi.
    r = await client.post("/_idem/other", json={"a": 1}, headers=h)
    assert r.status_code == 409
    r = await client.post("/_idem/ok", json={"a": 1}, params={"x": "1"}, headers=h)
    assert r.status_code == 409
    assert counter.calls == 1


async def test_requete_en_cours_conflit(idem, world: World, db_session: AsyncSession):
    client, counter = idem
    k = uuid.uuid4()
    db_session.add(
        IdempotencyKey(
            user_id=world.lead_a,
            idempotency_key=k,
            method="POST",
            route="/api/v1/_idem/ok",
            request_hash=request_fingerprint("POST", "/api/v1/_idem/ok", b"", b"{}"),
            state="in_progress",
            expires_at=func.now() + text("interval '24 hours'"),
        )
    )
    await db_session.commit()
    r = await client.post(
        "/_idem/ok", json={}, headers=world.h_lead_a() | {"Idempotency-Key": str(k)}
    )
    assert r.status_code == 409
    err = assert_envelope(r, "IDEMPOTENCY_KEY_CONFLICT")
    assert err["details"]["reason"] == "in_progress"
    assert r.headers["Retry-After"] == "1"
    assert counter.calls == 0


async def test_cle_par_appelant(idem, world: World):
    client, _counter = idem
    k = key()
    r1 = await client.post("/_idem/ok", json={}, headers=world.h_lead_a() | k)
    r2 = await client.post("/_idem/ok", json={}, headers=world.h_lead_b() | k)
    assert (r1.json()["n"], r2.json()["n"]) == (1, 2)
    assert "Idempotent-Replayed" not in r2.headers


async def test_5xx_non_memorisee(idem, world: World, db_session: AsyncSession):
    client, counter = idem
    h = world.h_lead_a() | key()
    for _ in range(2):
        r = await client.post("/_idem/boom", headers=h)
        assert r.status_code == 500
        assert_envelope(r, "INTERNAL_ERROR")
    assert counter.calls == 2  # le client peut réessayer avec la même clé
    assert await rows(db_session, world.lead_a) == []


async def test_403_non_memorisee_409_metier_memorisee(idem, world: World, db_session: AsyncSession):
    client, counter = idem
    h = world.h_lead_a() | key()
    for _ in range(2):
        assert (await client.post("/_idem/forbidden", headers=h)).status_code == 403
    assert counter.calls == 2
    assert await rows(db_session, world.lead_a) == []

    h = world.h_lead_a() | key()
    r1 = await client.post("/_idem/conflict", headers=h)
    r2 = await client.post("/_idem/conflict", headers=h)
    assert r1.status_code == r2.status_code == 409
    assert r2.headers["Idempotent-Replayed"] == "true"
    # Rejouée telle quelle, sauf request_id = celui de l'échange courant (= X-Request-ID).
    e1, e2 = assert_envelope(r1, "CONFLICT"), assert_envelope(r2, "CONFLICT")
    assert e1["details"] == e2["details"] == {"n": 3}
    assert counter.calls == 3


async def test_reponse_non_json_et_204(idem, world: World, db_session: AsyncSession):
    client, counter = idem
    h = world.h_lead_a() | key()
    for _ in range(2):
        r = await client.post("/_idem/text", headers=h)
        assert r.status_code == 200
        assert r.text == "ok"
    assert counter.calls == 2  # flux non JSON : non mémorisé

    h = world.h_lead_a() | key()
    r1 = await client.delete("/_idem/item", headers=h)
    r2 = await client.delete("/_idem/item", headers=h)
    assert r1.status_code == r2.status_code == 204
    assert r2.content == b""
    assert r2.headers["Idempotent-Replayed"] == "true"
    assert counter.calls == 3


async def test_cle_expiree_reutilisable(idem, world: World, db_session: AsyncSession):
    client, _counter = idem
    h = world.h_lead_a() | key()
    assert (await client.post("/_idem/ok", json={"a": 1}, headers=h)).json()["n"] == 1
    await db_session.execute(
        text(
            "UPDATE idempotency_key SET expires_at = now() - interval '1 second', "
            "created_at = now() - interval '25 hours' WHERE user_id = :u"
        ),
        {"u": world.lead_a},
    )
    await db_session.commit()
    # Après 24 h : même clé, autre corps → exécutée normalement (pas de conflit).
    r = await client.post("/_idem/ok", json={"a": 2}, headers=h)
    assert r.status_code == 201
    assert r.json()["n"] == 2
    [row] = await rows(db_session, world.lead_a)
    assert row.response_body["body"]["echo"] == {"a": 2}


async def test_cle_invalide_et_appelants_non_memorises(
    idem, world: World, db_session: AsyncSession
):
    client, counter = idem
    r = await client.post(
        "/_idem/ok", json={}, headers=world.h_lead_a() | {"Idempotency-Key": "pas-un-uuid"}
    )
    assert r.status_code == 422
    err = assert_envelope(r, "VALIDATION_ERROR")
    assert err["details"] == [
        {"field": "Idempotency-Key", "issue": "uuid_parsing", "location": "header"}
    ]
    assert "pas-un-uuid" not in r.text

    # Anonyme, compte absent de user_account : la requête passe, rien n'est mémorisé.
    k = key()
    ghost = headers("iit_academic_lead", user=uuid.uuid4())
    for h in ({} | k, {} | k, ghost | k, ghost | k):
        assert (await client.post("/_idem/ok", json={}, headers=h)).status_code == 201
    assert counter.calls == 4
    # GET : l'en-tête est ignoré.
    r = await client.get("/health", headers=world.h_lead_a() | k)
    assert r.status_code == 200
    n = await db_session.scalar(select(func.count()).select_from(IdempotencyKey))
    assert n == 0


# --- Vraies routes du catalogue staff ---------------------------------------------------------


def fee_body(w: World) -> dict:
    return {
        "programme_id": str(w.programme),
        "academic_year": "2028-2029",
        "registration_fee": {"amount": "300.000", "currency": "TND"},
        "tuition_fee": {"amount": "7000.000", "currency": "TND"},
        "valid_from": "2027-06-01",
    }


async def test_cle_obligatoire_sur_les_post_staff(api_raw, world: World):
    w = world
    url = "/staff/catalogue/fee-schedules"
    r = await api_raw.post(url, json=fee_body(w), headers=w.h_lead_a())
    assert r.status_code == 422
    err = assert_envelope(r, "VALIDATION_ERROR")
    assert err["details"] == [
        {"field": "Idempotency-Key", "issue": "required", "location": "header"}
    ]
    # Ordre SA-5 §1.3 : identification puis rôle avant le contrôle de la clé.
    assert (await api_raw.post(url, json=fee_body(w))).status_code == 401
    assert (await api_raw.post(url, json=fee_body(w), headers=w.h_candidate())).status_code == 403
    assert (await api_raw.post(url, json=fee_body(w), headers=w.h_admin())).status_code == 403
    # Une action (soumission) sans clé est refusée aussi ; la clé reste facultative sur PATCH.
    rid = (await api_raw.post(url, json=fee_body(w), headers=w.h_lead_a() | key())).json()["id"]
    r = await api_raw.get(f"{url}/{rid}", headers=w.h_lead_a())
    etag = r.headers["ETag"]
    r = await api_raw.post(f"{url}/{rid}/submit", headers=w.h_lead_a() | {"If-Match": etag})
    assert r.status_code == 422
    r = await api_raw.patch(
        f"{url}/{rid}", json={"notes_fr": "Note"}, headers=w.h_lead_a() | {"If-Match": etag}
    )
    assert r.status_code == 200, r.text


async def test_double_creation_et_double_publication_sans_effet(
    api_raw, world: World, db_session: AsyncSession
):
    w = world
    url = "/staff/catalogue/fee-schedules"
    k = key()
    r1 = await api_raw.post(url, json=fee_body(w), headers=w.h_lead_a() | k)
    r2 = await api_raw.post(url, json=fee_body(w), headers=w.h_lead_a() | k)
    assert r1.status_code == r2.status_code == 201
    assert r1.json()["id"] == r2.json()["id"]
    assert r2.headers["ETag"] == r1.headers["ETag"]
    assert r2.headers["Idempotent-Replayed"] == "true"
    n = await db_session.scalar(
        select(func.count())
        .select_from(FeeSchedule)
        .where(FeeSchedule.programme_id == w.programme, FeeSchedule.academic_year == "2028-2029")
    )
    assert n == 1  # un réessai réseau ne crée pas de doublon

    rid = r1.json()["id"]
    r = await api_raw.post(
        f"{url}/{rid}/submit", headers=w.h_lead_a() | key() | {"If-Match": r1.headers["ETag"]}
    )
    assert r.status_code == 200, r.text
    k = key()
    publish = w.h_lead_b() | k | {"If-Match": r.headers["ETag"]}
    p1 = await api_raw.post(f"{url}/{rid}/publish", headers=publish)
    p2 = await api_raw.post(f"{url}/{rid}/publish", headers=publish)
    assert p1.status_code == p2.status_code == 200
    assert p2.json() == p1.json()
    # Sans idempotence, le 2e appel aurait donné 409 INVALID_STATUS_TRANSITION (ou 412).
    assert p2.headers["Idempotent-Replayed"] == "true"
    # Nouvelle clé : la route s'exécute et refuse la transition (déjà publiée).
    r = await api_raw.post(
        f"{url}/{rid}/publish", headers=w.h_lead_b() | key() | {"If-Match": p1.headers["ETag"]}
    )
    assert r.status_code == 409
    assert_envelope(r, "INVALID_STATUS_TRANSITION")
