"""Cookies de l'authentification (SA-25, SA-28 ; SA-5 §1.2).

- `sc_visitor` : jeton opaque de la session visiteur ; httpOnly, SameSite=Lax, chemin `/`,
  durée = durée maximale de la session (7 j). Seul son hachage est en base.
- `sc_refresh` : jeton de renouvellement ; httpOnly, SameSite=Strict, chemin
  `/api/v1/auth` (jamais envoyé aux autres routes), 7 jours.

`Secure` est actif hors dev/test (réglage `cookie_secure`) : le navigateur ne les envoie
alors qu'en HTTPS.
"""

from __future__ import annotations

from fastapi import Response

from app.core.config import Settings

VISITOR_COOKIE = "sc_visitor"
REFRESH_COOKIE = "sc_refresh"


def refresh_cookie_path(settings: Settings) -> str:
    return f"{settings.api_prefix}/auth"


def set_visitor_cookie(response: Response, settings: Settings, token: str) -> None:
    response.set_cookie(
        VISITOR_COOKIE,
        token,
        max_age=settings.visitor_max_lifetime_days * 86400,
        httponly=True,
        secure=settings.cookies_secure,
        samesite="lax",
        path="/",
    )


def clear_visitor_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        VISITOR_COOKIE, path="/", httponly=True, secure=settings.cookies_secure, samesite="lax"
    )


def set_refresh_cookie(response: Response, settings: Settings, token: str) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        max_age=settings.refresh_token_ttl_days * 86400,
        httponly=True,
        secure=settings.cookies_secure,
        samesite="strict",
        path=refresh_cookie_path(settings),
    )


def clear_refresh_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        REFRESH_COOKIE,
        path=refresh_cookie_path(settings),
        httponly=True,
        secure=settings.cookies_secure,
        samesite="strict",
    )
