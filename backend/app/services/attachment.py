"""Rattachement d'une session visiteur au compte candidat (SA-29).

Parcours (SA-3, SA-5 §5.2) :

1. à l'inscription ou à la connexion d'un **candidat**, si le navigateur porte un cookie
   visiteur actif dont la session contient au moins une conversation, l'API renvoie une
   **offre** (`attach_offer`) et note la ligne `conversation_attachment` `offered` ;
2. le candidat répond par `POST /auth/attach-visitor-session` avec `consent` (booléen
   strict). Il faut **le jeton du candidat et le cookie de la même session** : connaître
   l'identifiant de session ne suffit jamais (`SESSION_NOT_OWNED` sinon) ;
3. `consent: false` → `declined`, rien ne bouge ; `consent: true` → consentement
   `conversation_link` journalisé, conversations **déplacées** vers le compte
   (`user_id`, `origin_visitor_session_id` conservé), session `attached`.

Une session n'a qu'un seul propriétaire (index unique partiel sur `attached`) : la rattacher
de nouveau au même compte est sans effet, à un autre compte → 409 ALREADY_ATTACHED.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError, ErrorCode
from app.models import Consent, Conversation, ConversationAttachment, VisitorSession
from app.schemas.auth import AttachOffer, AttachResponse
from app.services import visitor_sessions as visitors


def now_utc() -> datetime:
    return datetime.now(UTC)


async def build_offer(
    session: AsyncSession, settings: Settings, user_id: uuid.UUID, cookie_token: str | None
) -> AttachOffer | None:
    """Offre de rattachement pour un candidat qui vient de s'identifier, ou None."""
    vs = await visitors.find_by_token(session, cookie_token)
    now = now_utc()
    if vs is None or vs.status != "active" or visitors.is_time_expired(vs, now):
        return None
    conversation_count, message_count = (
        await session.execute(
            select(
                func.count(Conversation.id),
                func.coalesce(func.sum(Conversation.message_count), 0),
            ).where(Conversation.visitor_session_id == vs.id)
        )
    ).one()
    if conversation_count == 0:
        return None
    offer = await _open_offer(session, vs.id, user_id, now)
    if offer is None:
        offer = ConversationAttachment(
            visitor_session_id=vs.id,
            user_id=user_id,
            status="offered",
            offered_at=now,
            offer_expires_at=now + timedelta(minutes=settings.attach_offer_ttl_min),
        )
        session.add(offer)
        await session.flush()
    return AttachOffer(
        visitor_session_id=vs.id,
        conversation_count=conversation_count,
        message_count=int(message_count),
        offer_expires_at=offer.offer_expires_at,
    )


async def _open_offer(
    session: AsyncSession, visitor_session_id: uuid.UUID, user_id: uuid.UUID, now: datetime
) -> ConversationAttachment | None:
    return await session.scalar(
        select(ConversationAttachment)
        .where(
            ConversationAttachment.visitor_session_id == visitor_session_id,
            ConversationAttachment.user_id == user_id,
            ConversationAttachment.status == "offered",
            ConversationAttachment.offer_expires_at > now,
        )
        .order_by(ConversationAttachment.offered_at.desc())
        .limit(1)
    )


async def _attachment_row(
    session: AsyncSession, settings: Settings, vs_id: uuid.UUID, user_id: uuid.UUID, now: datetime
) -> ConversationAttachment:
    """Offre ouverte de ce couple (session, compte), sinon nouvelle ligne."""
    row = await _open_offer(session, vs_id, user_id, now)
    if row is None:
        row = ConversationAttachment(
            visitor_session_id=vs_id,
            user_id=user_id,
            status="offered",
            offered_at=now,
            offer_expires_at=now + timedelta(minutes=settings.attach_offer_ttl_min),
        )
        session.add(row)
    return row


async def attach(
    session: AsyncSession,
    settings: Settings,
    user_id: uuid.UUID,
    cookie_token: str | None,
    visitor_session_id: uuid.UUID,
    consent: bool,
) -> AttachResponse:
    now = now_utc()
    vs = await visitors.find_by_token(session, cookie_token, for_update=True)

    # 1. Preuve de possession : le cookie de CE navigateur désigne bien cette session.
    if vs is None or vs.id != visitor_session_id:
        target = await session.get(VisitorSession, visitor_session_id)
        if target is not None and target.status == "active":
            row = await _attachment_row(session, settings, target.id, user_id, now)
            row.status = "ownership_failed"
            row.resolved_at = now
            await session.commit()
        raise AppError(ErrorCode.SESSION_NOT_OWNED)

    # 2. Déjà rattachée : sans effet pour le même compte, refus pour un autre.
    if vs.status == "attached":
        if vs.attached_user_id != user_id:
            raise AppError(ErrorCode.ALREADY_ATTACHED)
        ids = list(
            await session.scalars(
                select(Conversation.id)
                .where(
                    Conversation.origin_visitor_session_id == vs.id,
                    Conversation.user_id == user_id,
                )
                .order_by(Conversation.created_at)
            )
        )
        return AttachResponse(
            attachment_status="attached", visitor_session_status="attached", conversation_ids=ids
        )

    # 3. Session encore utilisable ?
    if vs.status == "active" and visitors.is_time_expired(vs, now):
        vs.status = "expired"
    if vs.status != "active":
        for offer in await session.scalars(
            select(ConversationAttachment).where(
                ConversationAttachment.visitor_session_id == vs.id,
                ConversationAttachment.status == "offered",
            )
        ):
            offer.status = "expired"
            offer.resolved_at = now
        await session.commit()
        raise AppError(ErrorCode.SESSION_EXPIRED, details={"status": vs.status})

    row = await _attachment_row(session, settings, vs.id, user_id, now)
    consent_row = Consent(
        user_id=user_id,
        visitor_session_id=vs.id,
        consent_type="conversation_link",
        granted=consent,
        policy_version=settings.consent_policy_version,
        channel="web_form",
    )
    session.add(consent_row)
    await session.flush()

    # 4. Refus : journalisé, rien n'est déplacé ; la session visiteur reste utilisable.
    if not consent:
        row.status = "declined"
        row.consent_id = consent_row.id
        row.resolved_at = now
        await session.commit()
        return AttachResponse(attachment_status="declined", visitor_session_status="active")

    # 5. Accord : les conversations changent de propriétaire, la session est rattachée.
    moved = list(
        await session.scalars(
            update(Conversation)
            .where(Conversation.visitor_session_id == vs.id)
            .values(user_id=user_id, visitor_session_id=None, origin_visitor_session_id=vs.id)
            .returning(Conversation.id)
            .execution_options(synchronize_session=False)
        )
    )
    row.status = "attached"
    row.consent_id = consent_row.id
    row.ownership_checked_at = now
    row.conversations_moved = len(moved)
    row.resolved_at = now
    vs.status = "attached"
    vs.attached_user_id = user_id
    vs.attached_at = now
    await session.commit()
    return AttachResponse(
        attachment_status="attached", visitor_session_status="attached", conversation_ids=moved
    )
