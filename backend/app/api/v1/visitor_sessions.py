"""Routes des sessions visiteur sans compte (SA-25 ; SA-5 §5.3).

Le visiteur est identifié par le cookie `sc_visitor` (jamais par un identifiant envoyé dans
l'URL ou le corps). Règles et durées : `app/services/visitor_sessions.py` (D-D).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.cookies import VISITOR_COOKIE, clear_visitor_cookie, set_visitor_cookie
from app.core.db import get_session
from app.core.errors import AppError, ErrorCode
from app.schemas.common import ErrorResponse
from app.schemas.conversations import VisitorSessionCreate, VisitorSessionOut
from app.services import visitor_sessions as svc

router = APIRouter(prefix="/visitor-sessions", tags=["Sessions visiteur"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def _err(*codes: str) -> dict:
    return {"model": ErrorResponse, "description": "Codes : " + ", ".join(codes)}


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=VisitorSessionOut,
    summary="Créer une session visiteur temporaire",
    responses={200: {"model": VisitorSessionOut, "description": "Session active réutilisée."}},
)
async def create_visitor_session(
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
    payload: Annotated[VisitorSessionCreate | None, Body()] = None,
) -> VisitorSessionOut:
    """Pose le cookie `sc_visitor` (httpOnly). Si le navigateur porte déjà une session active,
    elle est **réutilisée** (200) au lieu d'en créer une nouvelle (201). Expire après 24 h
    d'inactivité, 7 jours au plus ; quota de 30 messages par 24 h."""
    result = await svc.create_or_reuse(
        session,
        settings,
        request.cookies.get(VISITOR_COOKIE),
        payload.locale if payload else None,
    )
    if result.created:
        assert result.token is not None
        set_visitor_cookie(response, settings, result.token)
    else:
        response.status_code = status.HTTP_200_OK
    return svc.to_out(result.visitor_session, settings)


@router.get(
    "/current",
    response_model=VisitorSessionOut,
    summary="Lire la session visiteur, son quota et son profil provisoire",
    responses={401: _err("UNAUTHENTICATED"), 410: _err("SESSION_EXPIRED")},
)
async def read_current(
    request: Request, session: SessionDep, settings: SettingsDep
) -> VisitorSessionOut:
    """Une session rattachée à un compte reste lisible (statut `attached`) ; une session
    expirée répond 410, une session oubliée ou inconnue 401."""
    vs = await svc.find_by_token(session, request.cookies.get(VISITOR_COOKIE), for_update=True)
    if vs is None or vs.status == "purged":
        raise AppError(ErrorCode.UNAUTHENTICATED, details={"reason": "no_visitor_session"})
    if vs.status == "attached":
        return svc.to_out(vs, settings)
    vs = await svc.require_active(session, settings, vs)
    await session.commit()
    return svc.to_out(vs, settings)


@router.delete(
    "/current",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Oublier ma session (purge immédiate des messages)",
    responses={401: _err("UNAUTHENTICATED"), 410: _err("SESSION_EXPIRED")},
)
async def forget_current(request: Request, session: SessionDep, settings: SettingsDep) -> Response:
    """Bouton « oublier ma session » : conversations et messages supprimés tout de suite,
    statut `purged`, cookie effacé."""
    vs = await svc.find_by_token(session, request.cookies.get(VISITOR_COOKIE), for_update=True)
    vs = await svc.require_active(session, settings, vs)
    await svc.forget(session, vs)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_visitor_cookie(response, settings)
    return response
