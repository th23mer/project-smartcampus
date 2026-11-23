"""Sessions visiteur sans compte (SA-25) : création, contrôle, quota, oubli et purge.

Règles (décision D-D, SA-3 §visiteur, SA-5 §1.2) — code déterministe, jamais le LLM :

- cookie opaque `sc_visitor` (httpOnly, SameSite=Lax) ; en base, seul le **hachage
  SHA-256** du jeton est stocké. La preuve de possession est le cookie, jamais un
  identifiant envoyé par le client ;
- expiration après **24 h d'inactivité**, **7 jours au plus** ; la session expirée ne sert
  plus (410 SESSION_EXPIRED) et ses conversations sont purgées **30 jours** après ;
- quota : **30 messages par fenêtre de 24 h** ; compteur et message enregistrés dans la
  **même transaction** (deux requêtes simultanées ne dépassent pas la limite) ;
- « oublier ma session » : transition `active → purged` immédiate, conversations supprimées.

Statuts (SA-3) : `active`, `attached` (rattachée à un compte, SA-29), `expired`, `purged`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import case, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError, ErrorCode
from app.core.tokens import hash_opaque_token, new_opaque_token
from app.models import Conversation, VisitorSession
from app.schemas.conversations import Quota, VisitorSessionOut


def now_utc() -> datetime:
    return datetime.now(UTC)


def expires_at(vs: VisitorSession) -> datetime:
    """Fin de validité effective : inactivité ou durée maximale, la plus proche."""
    return min(vs.idle_expires_at, vs.hard_expires_at)


def is_time_expired(vs: VisitorSession, now: datetime) -> bool:
    return now >= expires_at(vs)


def quota_of(vs: VisitorSession, settings: Settings, now: datetime) -> Quota:
    """Vue du quota : une fenêtre écoulée compte pour zéro (remise à zéro au prochain message)."""
    window = timedelta(hours=settings.visitor_quota_window_h)
    if now >= vs.quota_window_start + window:
        return Quota(
            messages_used=0, messages_limit=settings.visitor_message_quota, resets_at=now + window
        )
    return Quota(
        messages_used=vs.message_count,
        messages_limit=settings.visitor_message_quota,
        resets_at=vs.quota_window_start + window,
    )


def to_out(
    vs: VisitorSession, settings: Settings, now: datetime | None = None
) -> VisitorSessionOut:
    now = now or now_utc()
    return VisitorSessionOut(
        id=vs.id,
        status=vs.status,  # type: ignore[arg-type]
        created_at=vs.created_at,
        expires_at=expires_at(vs),
        quota=quota_of(vs, settings, now),
    )


async def find_by_token(
    session: AsyncSession, token: str | None, *, for_update: bool = False
) -> VisitorSession | None:
    """Session désignée par le cookie (jeton haché), quel que soit son statut."""
    if not token:
        return None
    stmt = select(VisitorSession).where(VisitorSession.token_hash == hash_opaque_token(token))
    if for_update:
        stmt = stmt.with_for_update()
    return await session.scalar(stmt)


@dataclass
class CreatedSession:
    visitor_session: VisitorSession
    #: Jeton à poser dans le cookie ; None si la session existante est réutilisée.
    token: str | None

    @property
    def created(self) -> bool:
        return self.token is not None


async def create_or_reuse(
    session: AsyncSession, settings: Settings, cookie_token: str | None, locale: str | None
) -> CreatedSession:
    """Réutilise la session active du navigateur (pas de nouvelle session à chaque appel),
    sinon en crée une nouvelle avec un jeton neuf."""
    now = now_utc()
    existing = await find_by_token(session, cookie_token, for_update=True)
    if existing is not None and existing.status == "active":
        if not is_time_expired(existing, now):
            touch(existing, settings, now)
            await session.commit()
            return CreatedSession(existing, None)
        existing.status = "expired"

    token = new_opaque_token()
    hard = now + timedelta(days=settings.visitor_max_lifetime_days)
    vs = VisitorSession(
        token_hash=hash_opaque_token(token),
        status="active",
        last_seen_at=now,
        idle_expires_at=min(now + timedelta(hours=settings.visitor_idle_ttl_h), hard),
        hard_expires_at=hard,
        quota_window_start=now,
        detected_language=locale,
        created_at=now,
    )
    session.add(vs)
    await session.commit()
    await session.refresh(vs)
    return CreatedSession(vs, token)


def touch(vs: VisitorSession, settings: Settings, now: datetime) -> None:
    """Activité : repousse l'expiration d'inactivité, jamais au-delà de la durée maximale."""
    vs.last_seen_at = now
    vs.idle_expires_at = min(now + timedelta(hours=settings.visitor_idle_ttl_h), vs.hard_expires_at)


async def require_active(
    session: AsyncSession, settings: Settings, vs: VisitorSession | None
) -> VisitorSession:
    """Contrôle d'une requête visiteur : 401 sans cookie valide, 410 si expirée ou rattachée.

    Une expiration constatée est enregistrée (`active → expired`) avant de répondre 410.
    """
    if vs is None or vs.status == "purged":
        raise AppError(ErrorCode.UNAUTHENTICATED, details={"reason": "no_visitor_session"})
    now = now_utc()
    if vs.status == "active" and is_time_expired(vs, now):
        vs.status = "expired"
        await session.commit()
    if vs.status != "active":
        raise AppError(ErrorCode.SESSION_EXPIRED, details={"status": vs.status})
    touch(vs, settings, now)
    return vs


async def consume_quota(
    session: AsyncSession, settings: Settings, vs: VisitorSession, now: datetime
) -> Quota:
    """Compte un message dans la transaction en cours (UPDATE conditionnel atomique).

    Fenêtre écoulée → compteur remis à 1 et nouvelle fenêtre. Limite atteinte → 429
    VISITOR_QUOTA_EXCEEDED avec `Retry-After` et la suggestion de créer un compte.
    """
    window = timedelta(hours=settings.visitor_quota_window_h)
    limit = settings.visitor_message_quota
    window_start = vs.quota_window_start  # lu avant un éventuel rollback (attributs expirés)
    elapsed = VisitorSession.quota_window_start + window <= now
    row = (
        await session.execute(
            update(VisitorSession)
            .where(
                VisitorSession.id == vs.id,
                VisitorSession.status == "active",
                elapsed | (VisitorSession.message_count < limit),
            )
            .values(
                message_count=case((elapsed, 1), else_=VisitorSession.message_count + 1),
                quota_window_start=case((elapsed, now), else_=VisitorSession.quota_window_start),
            )
            .returning(VisitorSession.message_count, VisitorSession.quota_window_start)
            .execution_options(synchronize_session=False)
        )
    ).first()
    if row is None:
        await session.rollback()
        resets_at = window_start + window
        retry_after = max(1, int((resets_at - now).total_seconds()))
        raise AppError(
            ErrorCode.VISITOR_QUOTA_EXCEEDED,
            details={
                "limit": limit,
                "resets_at": resets_at.isoformat(),
                "suggestion": "create_account",
            },
            headers={"Retry-After": str(retry_after)},
        )
    vs.message_count, vs.quota_window_start = row.message_count, row.quota_window_start
    return Quota(
        messages_used=row.message_count,
        messages_limit=limit,
        resets_at=row.quota_window_start + window,
    )


async def forget(session: AsyncSession, vs: VisitorSession) -> None:
    """« Oublier ma session » : conversations supprimées (messages en cascade), `purged`."""
    await session.execute(delete(Conversation).where(Conversation.visitor_session_id == vs.id))
    vs.status = "purged"
    vs.purged_at = now_utc()
    await session.commit()


@dataclass
class PurgeReport:
    expired: int
    purged: int


async def expire_and_purge(
    session: AsyncSession, settings: Settings, now: datetime | None = None
) -> PurgeReport:
    """Tâche planifiée : marque les sessions échues `expired`, puis purge (conversations
    supprimées, statut `purged`) celles expirées depuis plus de 30 jours."""
    now = now or now_utc()
    effective = func.least(VisitorSession.idle_expires_at, VisitorSession.hard_expires_at)
    expired = await session.execute(
        update(VisitorSession)
        .where(VisitorSession.status == "active", effective <= now)
        .values(status="expired")
        .execution_options(synchronize_session=False)
    )
    cutoff = now - timedelta(days=settings.visitor_purge_after_days)
    to_purge = list(
        await session.scalars(
            select(VisitorSession.id).where(VisitorSession.status == "expired", effective <= cutoff)
        )
    )
    if to_purge:
        await session.execute(
            delete(Conversation).where(Conversation.visitor_session_id.in_(to_purge))
        )
        await session.execute(
            update(VisitorSession)
            .where(VisitorSession.id.in_(to_purge))
            .values(status="purged", purged_at=now)
            .execution_options(synchronize_session=False)
        )
    await session.commit()
    return PurgeReport(expired=expired.rowcount or 0, purged=len(to_purge))
