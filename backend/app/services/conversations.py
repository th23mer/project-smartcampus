"""Conversations et mémoire conversationnelle (SA-26).

Une conversation appartient **soit** à une session visiteur, **soit** à un compte candidat
(CHECK `owner` de SA-13). Les messages sont stockés dans `message` (numérotés par `seq`) :

- un visiteur ne voit que les conversations de **sa** session (cookie), un candidat que les
  siennes ; une conversation d'un autre répond 404 (SA-5 §1.3, règle P) ;
- envoi d'un message : texte de 1 à 2 000 caractères, `client_message_id` pour rendre
  l'envoi idempotent, quota visiteur compté **dans la même transaction** que l'écriture ;
- **mémoire de travail** de l'agent : `memory_context` renvoie les N derniers messages
  (20 par défaut, `memory_context_messages`) au format `{role, content}`, ordre
  chronologique. La mémoire dure autant que la session visiteur (24 h d'inactivité, 7 j
  max, purge à 30 j, D-D) ou que le compte candidat.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError, ErrorCode
from app.core.pagination import CursorMeta, CursorPage, CursorParams, Page, PageParams
from app.core.security import CurrentUser
from app.models import Conversation, Message, VisitorSession
from app.schemas.conversations import (
    ChatMessageCreate,
    ConversationCreate,
    ConversationOut,
    MessageOut,
    Quota,
)
from app.services import visitor_sessions as visitors


def now_utc() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class ChatCaller:
    """Propriétaire des conversations : un candidat (jeton) ou un visiteur (cookie)."""

    user: CurrentUser | None = None
    visitor: VisitorSession | None = None

    @property
    def is_visitor(self) -> bool:
        return self.user is None


def _owner_filter(caller: ChatCaller) -> Any:
    if caller.user is not None:
        return Conversation.user_id == caller.user.id
    assert caller.visitor is not None
    return Conversation.visitor_session_id == caller.visitor.id


def conversation_out(conv: Conversation) -> ConversationOut:
    return ConversationOut(
        id=conv.id,
        owner_type="candidate" if conv.user_id else "visitor",
        status=conv.status,  # type: ignore[arg-type]
        title=conv.title,
        created_at=conv.created_at,
        last_message_at=conv.last_message_at,
        message_count=conv.message_count,
    )


def message_out(msg: Message) -> MessageOut:
    return MessageOut(
        id=msg.id,
        conversation_id=msg.conversation_id,
        role=msg.role,  # type: ignore[arg-type]
        content_type=msg.input_modality,  # type: ignore[arg-type]
        text=msg.content,
        language=msg.detected_language,  # type: ignore[arg-type]
        reply_language=msg.reply_language,  # type: ignore[arg-type]
        audio_expires_at=msg.audio_purge_at,
        citations=list(msg.sources or []),
        finish_reason=msg.finish_reason,
        created_at=msg.created_at,
    )


async def create(
    session: AsyncSession, caller: ChatCaller, payload: ConversationCreate
) -> ConversationOut:
    conv = Conversation(
        user_id=caller.user.id if caller.user else None,
        visitor_session_id=caller.visitor.id if caller.visitor and not caller.user else None,
        channel="text",
        status="open",
        title=payload.title,
        message_count=0,
    )
    session.add(conv)
    await session.commit()
    await session.refresh(conv)
    return conversation_out(conv)


async def list_(
    session: AsyncSession,
    caller: ChatCaller,
    params: PageParams,
    status: str | None,
    sort: str,
) -> Page[ConversationOut]:
    where = [_owner_filter(caller)]
    if status:
        where.append(Conversation.status == status)
    total = await session.scalar(select(func.count(Conversation.id)).where(*where)) or 0
    order = {
        "-last_message_at": Conversation.last_message_at.desc().nulls_last(),
        "last_message_at": Conversation.last_message_at.asc().nulls_first(),
        "-created_at": Conversation.created_at.desc(),
        "created_at": Conversation.created_at.asc(),
    }[sort]
    rows = await session.scalars(
        select(Conversation)
        .where(*where)
        .order_by(order, Conversation.id)
        .offset(params.offset)
        .limit(params.limit)
    )
    return Page[ConversationOut].build([conversation_out(c) for c in rows], total, params)


async def get_owned(
    session: AsyncSession, caller: ChatCaller, conversation_id: uuid.UUID, *, lock: bool = False
) -> Conversation:
    """Conversation de l'appelant ; 404 si elle n'existe pas ou appartient à un autre."""
    stmt = select(Conversation).where(Conversation.id == conversation_id, _owner_filter(caller))
    if lock:
        stmt = stmt.with_for_update()
    conv = await session.scalar(stmt)
    if conv is None:
        raise AppError(ErrorCode.NOT_FOUND, details={"resource": "conversation"})
    return conv


async def list_messages(
    session: AsyncSession, caller: ChatCaller, conversation_id: uuid.UUID, params: CursorParams
) -> CursorPage[MessageOut]:
    """Page de messages en ordre chronologique ; `before` = curseur vers les plus anciens."""
    await get_owned(session, caller, conversation_id)
    where = [Message.conversation_id == conversation_id]
    if params.before is not None:
        try:
            before = int(params.before)
        except ValueError as exc:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                details=[{"field": "before", "issue": "invalid_cursor", "location": "query"}],
            ) from exc
        where.append(Message.seq < before)
    rows = list(
        await session.scalars(
            select(Message).where(*where).order_by(Message.seq.desc()).limit(params.limit + 1)
        )
    )
    has_more = len(rows) > params.limit
    rows = rows[: params.limit]
    rows.reverse()
    next_cursor = str(rows[0].seq) if has_more and rows else None
    return CursorPage[MessageOut](
        items=[message_out(m) for m in rows],
        meta=CursorMeta(limit=params.limit, next_cursor=next_cursor),
    )


async def memory_context(
    session: AsyncSession, conversation_id: uuid.UUID, max_messages: int
) -> list[dict[str, str]]:
    """Mémoire de travail transmise au LLM (E4, SA-37) : N derniers messages utilisateur et
    assistant, en ordre chronologique. Les messages d'outil restent dans le journal."""
    rows = list(
        await session.execute(
            select(Message.role, Message.content)
            .where(
                Message.conversation_id == conversation_id,
                Message.role.in_(("user", "assistant")),
                Message.content.is_not(None),
            )
            .order_by(Message.seq.desc())
            .limit(max_messages)
        )
    )
    rows.reverse()
    return [{"role": r.role, "content": r.content} for r in rows]


@dataclass
class StoredUserMessage:
    conversation: Conversation
    message: Message
    quota: Quota | None
    #: Vrai si le même `client_message_id` avait déjà été enregistré (réessai du front).
    replayed: bool


async def store_user_message(
    session: AsyncSession,
    settings: Settings,
    caller: ChatCaller,
    conversation_id: uuid.UUID,
    payload: ChatMessageCreate,
) -> StoredUserMessage:
    """Enregistre le message de l'utilisateur et compte le quota, en une seule transaction."""
    text = payload.content.text
    if not text.strip():
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            details=[{"field": "content.text", "issue": "blank", "location": "body"}],
        )
    if len(text) > settings.message_max_chars:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            details=[{"field": "content.text", "issue": "too_long", "location": "body"}],
        )
    conv = await get_owned(session, caller, conversation_id, lock=True)
    now = now_utc()

    existing = await session.scalar(
        select(Message).where(
            Message.conversation_id == conv.id,
            Message.client_message_id == payload.client_message_id,
        )
    )
    if existing is not None:
        if existing.content != text:
            raise AppError(
                ErrorCode.IDEMPOTENCY_KEY_CONFLICT,
                details={"field": "client_message_id", "reason": "request_mismatch"},
            )
        quota = visitors.quota_of(caller.visitor, settings, now) if caller.visitor else None
        return StoredUserMessage(conv, existing, quota, replayed=True)

    if conv.status != "open":
        raise AppError(ErrorCode.CONVERSATION_CLOSED)

    quota = None
    if caller.is_visitor:
        assert caller.visitor is not None
        quota = await visitors.consume_quota(session, settings, caller.visitor, now)

    msg = await append_message(
        session,
        conv,
        role="user",
        content=text,
        now=now,
        client_message_id=payload.client_message_id,
        detected_language=payload.language_hint,
    )
    await session.commit()
    return StoredUserMessage(conv, msg, quota, replayed=False)


async def append_message(
    session: AsyncSession,
    conv: Conversation,
    *,
    role: str,
    content: str,
    now: datetime,
    **fields: Any,
) -> Message:
    """Ajoute un message à la conversation **verrouillée** (numéro `seq` suivant)."""
    last_seq = await session.scalar(
        select(func.coalesce(func.max(Message.seq), 0)).where(Message.conversation_id == conv.id)
    )
    msg = Message(
        conversation_id=conv.id,
        seq=(last_seq or 0) + 1,
        role=role,
        content=content,
        input_modality="text",
        created_at=now,
        **fields,
    )
    session.add(msg)
    conv.message_count = conv.message_count + 1
    conv.last_message_at = now
    if conv.title is None and role == "user":
        conv.title = content[:80]
    await session.flush()
    await session.refresh(msg)
    return msg


async def next_assistant_message(
    session: AsyncSession, conversation_id: uuid.UUID, after_seq: int
) -> Message | None:
    """Réponse de l'assistant qui suit un message utilisateur donné (rejeu d'un réessai)."""
    nxt = await session.scalar(
        select(Message)
        .where(Message.conversation_id == conversation_id, Message.seq > after_seq)
        .order_by(Message.seq)
        .limit(1)
    )
    return nxt if nxt is not None and nxt.role == "assistant" else None
