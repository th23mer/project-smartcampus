"""Routes d'authentification et de rattachement (SA-28, SA-29 ; SA-5 §5.2).

| Route | Accès |
|---|---|
| `POST /auth/register` | public : crée un **candidat**, pose `sc_refresh`, offre de rattachement |
| `POST /auth/login` | public : candidat ou staff ; 5 échecs / 15 min / IP + e-mail |
| `POST /auth/refresh` | cookie `sc_refresh` : nouveau jeton d'accès, rotation du cookie |
| `POST /auth/logout` | connecté : révoque le cookie de renouvellement |
| `GET /auth/me` | connecté : compte et rôles relus en base |
| `POST /auth/attach-visitor-session` | candidat + cookie visiteur de la même session |
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.cookies import (
    REFRESH_COOKIE,
    VISITOR_COOKIE,
    clear_refresh_cookie,
    set_refresh_cookie,
)
from app.core.db import get_session
from app.core.errors import AppError, ErrorCode
from app.core.rate_limit import FailureLimiter
from app.core.security import CurrentUser, CurrentUserDep, Role, require_roles
from app.schemas.auth import (
    AttachRequest,
    AttachResponse,
    AuthResponse,
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    User,
    normalize_email,
)
from app.schemas.common import ErrorResponse
from app.services import attachment as attach_svc
from app.services import auth as svc
from app.services import visitor_sessions as visitors

router = APIRouter(prefix="/auth", tags=["Authentification"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
CandidateDep = Annotated[CurrentUser, Depends(require_roles(Role.CANDIDATE))]


def _err(*codes: str) -> dict:
    return {"model": ErrorResponse, "description": "Codes : " + ", ".join(codes)}


def _limiter(request: Request, settings: Settings) -> FailureLimiter:
    """Limiteur d'échecs de connexion, un par application (state)."""
    limiter = getattr(request.app.state, "login_limiter", None)
    if limiter is None:
        limiter = FailureLimiter(settings.login_max_failures, settings.login_window_s)
        request.app.state.login_limiter = limiter
    return limiter


async def _auth_response(
    session: AsyncSession,
    settings: Settings,
    request: Request,
    response: Response,
    identity: svc.Identity,
) -> AuthResponse:
    tokens, _ = await svc.issue_tokens(session, settings, identity)
    offer = None
    if "candidate" in identity.roles:
        offer = await attach_svc.build_offer(
            session, settings, identity.account.id, request.cookies.get(VISITOR_COOKIE)
        )
    await session.commit()
    set_refresh_cookie(response, settings, tokens.refresh_token)
    return AuthResponse(
        user=identity.to_user(),
        access_token=tokens.access_token,
        expires_in=tokens.expires_in,
        attach_offer=offer,
    )


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    response_model=AuthResponse,
    summary="Créer un compte candidat (passage visiteur → candidat)",
    responses={409: _err("EMAIL_ALREADY_USED"), 503: _err("SERVICE_UNAVAILABLE")},
)
async def register(
    payload: RegisterRequest,
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
) -> AuthResponse:
    """Inscription **publique** : le compte créé est toujours `candidate`, jamais staff.
    `consents.terms_accepted` et `consents.data_processing` doivent valoir `true`
    (`422 CONSENT_REQUIRED`). Pose le cookie `sc_refresh` ; `attach_offer` est présent si le
    navigateur porte une session visiteur active avec au moins une conversation (SA-29)."""
    vs = await visitors.find_by_token(session, request.cookies.get(VISITOR_COOKIE))
    identity = await svc.register(
        session, settings, payload, vs.id if vs and vs.status == "active" else None
    )
    return await _auth_response(session, settings, request, response, identity)


@router.post(
    "/login",
    response_model=AuthResponse,
    summary="Connexion candidat ou staff",
    responses={
        401: _err("INVALID_CREDENTIALS"),
        403: _err("ACCOUNT_DISABLED"),
        429: _err("RATE_LIMITED"),
        503: _err("SERVICE_UNAVAILABLE"),
    },
)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
) -> AuthResponse:
    """Même réponse pour un e-mail inconnu et un mauvais mot de passe. 5 échecs en 15 min
    pour une IP et un e-mail → `429 RATE_LIMITED` avec `Retry-After`."""
    try:
        email = normalize_email(payload.email)
    except ValueError:
        raise AppError(ErrorCode.INVALID_CREDENTIALS) from None
    limiter = _limiter(request, settings)
    key = f"{request.client.host if request.client else '-'}|{email}"
    wait = limiter.retry_after(key)
    if wait is not None:
        raise AppError(ErrorCode.RATE_LIMITED, headers={"Retry-After": str(wait)})
    try:
        identity = await svc.authenticate(session, email, payload.password)
    except AppError as exc:
        if exc.code == ErrorCode.INVALID_CREDENTIALS:
            limiter.record_failure(key)
        raise
    limiter.reset(key)
    return await _auth_response(session, settings, request, response, identity)


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Renouveler le jeton d'accès (cookie `sc_refresh`, rotation)",
    responses={401: _err("UNAUTHENTICATED"), 403: _err("ACCOUNT_DISABLED")},
)
async def refresh(
    request: Request, response: Response, session: SessionDep, settings: SettingsDep
) -> TokenResponse:
    """Le cookie présenté est remplacé par un nouveau ; les rôles sont relus en base. Un cookie
    déjà échangé et présenté de nouveau révoque toute la chaîne (vol probable)."""
    tokens = await svc.refresh(session, settings, request.cookies.get(REFRESH_COOKIE))
    set_refresh_cookie(response, settings, tokens.refresh_token)
    return TokenResponse(access_token=tokens.access_token, expires_in=tokens.expires_in)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Déconnexion (révoque le refresh token)",
    responses={401: _err("UNAUTHENTICATED")},
)
async def logout(
    user: CurrentUserDep, request: Request, session: SessionDep, settings: SettingsDep
) -> Response:
    await svc.logout(session, user.id, request.cookies.get(REFRESH_COOKIE))
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_refresh_cookie(response, settings)
    return response


@router.get(
    "/me",
    response_model=User,
    summary="Utilisateur courant et rôles",
    responses={401: _err("UNAUTHENTICATED")},
)
async def me(user: CurrentUserDep, session: SessionDep) -> User:
    identity = await svc.load_identity(session, user.id)
    if identity is None:
        raise AppError(ErrorCode.UNAUTHENTICATED, details={"reason": "unknown_user"})
    return identity.to_user()


@router.post(
    "/attach-visitor-session",
    response_model=AttachResponse,
    summary="Rattacher (ou refuser) la conversation visiteur au compte",
    responses={
        401: _err("UNAUTHENTICATED"),
        403: _err("SESSION_NOT_OWNED", "FORBIDDEN"),
        409: _err("ALREADY_ATTACHED", "IDEMPOTENCY_KEY_CONFLICT"),
        410: _err("SESSION_EXPIRED"),
    },
)
async def attach_visitor_session(
    payload: AttachRequest,
    user: CandidateDep,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
) -> AttachResponse:
    """Exige le jeton du **candidat** et le cookie visiteur de **la même** session : connaître
    l'identifiant ne suffit pas (`403 SESSION_NOT_OWNED`). `consent` est un booléen JSON strict ;
    `false` → `declined`, rien n'est déplacé. `true` → conversations déplacées vers le compte,
    consentement `conversation_link` journalisé, session `attached` : le cookie visiteur ne
    sert plus au chat (410) mais permet de renvoyer la même demande sans effet.
    Une session déjà rattachée à un autre compte → `409 ALREADY_ATTACHED`."""
    if not await svc.user_exists(session, user.id):
        raise AppError(ErrorCode.UNAUTHENTICATED, details={"reason": "unknown_user"})
    result = await attach_svc.attach(
        session,
        settings,
        user.id,
        request.cookies.get(VISITOR_COOKIE),
        payload.visitor_session_id,
        payload.consent,
    )
    return result
