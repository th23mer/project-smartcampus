"""Routes des conversations et des messages (SA-26 ; SA-5 §3 et §5.4).

Accès : visiteur (cookie `sc_visitor`) ou candidat (jeton Bearer), chacun sur **ses**
conversations uniquement (une conversation d'un autre → 404). Le staff n'a pas accès au
texte brut (synthèses seulement, D-F) → 403.

`POST /conversations/{id}/messages` enregistre le message (idempotent par
`client_message_id`), compte le quota visiteur dans la même transaction, puis demande la
réponse à l'agent branché par E4 (`app/services/chat.py`). Sans LLM branché : 503
`LLM_UNAVAILABLE` avec le secours déterministe dans `error.details.fallback` ; le message de
l'utilisateur reste enregistré. Le flux SSE (`Accept: text/event-stream`) arrivera avec E4.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.cookies import VISITOR_COOKIE
from app.core.db import get_session
from app.core.errors import AppError, ErrorCode
from app.core.pagination import CursorPage, CursorParamsDep, Page, PageParamsDep
from app.core.security import OptionalUserDep, Role
from app.schemas.common import ErrorResponse
from app.schemas.conversations import (
    ChatMessageCreate,
    ChatReply,
    ConversationCreate,
    ConversationOut,
    MessageOut,
)
from app.services import auth as auth_svc
from app.services import conversations as svc
from app.services import visitor_sessions as visitors
from app.services.chat import get_chat_responder

router = APIRouter(prefix="/conversations", tags=["Conversations et chat"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
IdempotencyKey = Annotated[
    str | None,
    Header(alias="Idempotency-Key", description="UUID client (SA-5 §1.6), facultatif."),
]

COMMON = {
    401: {"model": ErrorResponse, "description": "Codes : UNAUTHENTICATED"},
    403: {"model": ErrorResponse, "description": "Codes : FORBIDDEN"},
    410: {"model": ErrorResponse, "description": "Codes : SESSION_EXPIRED"},
}
NOT_FOUND = {404: {"model": ErrorResponse, "description": "Codes : NOT_FOUND"}}


async def get_chat_caller(
    user: OptionalUserDep, request: Request, session: SessionDep, settings: SettingsDep
) -> svc.ChatCaller:
    """Candidat (jeton) prioritaire ; sinon visiteur (cookie actif, 410 si expiré)."""
    if user is not None:
        if Role.CANDIDATE not in user.roles:
            raise AppError(ErrorCode.FORBIDDEN)
        if not await auth_svc.user_exists(session, user.id):
            raise AppError(ErrorCode.UNAUTHENTICATED, details={"reason": "unknown_user"})
        return svc.ChatCaller(user=user)
    vs = await visitors.find_by_token(session, request.cookies.get(VISITOR_COOKIE))
    vs = await visitors.require_active(session, settings, vs)
    await session.commit()
    return svc.ChatCaller(visitor=vs)


CallerDep = Annotated[svc.ChatCaller, Depends(get_chat_caller)]


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=ConversationOut,
    summary="Ouvrir une conversation",
    responses=COMMON,
)
async def create_conversation(
    caller: CallerDep,
    session: SessionDep,
    _key: IdempotencyKey = None,
    payload: ConversationCreate | None = None,
) -> ConversationOut:
    return await svc.create(session, caller, payload or ConversationCreate())


@router.get(
    "",
    response_model=Page[ConversationOut],
    summary="Lister mes conversations",
    responses=COMMON,
)
async def list_conversations(
    caller: CallerDep,
    session: SessionDep,
    params: PageParamsDep,
    status_: Annotated[Literal["open", "closed", "archived"] | None, Query(alias="status")] = None,
    sort: Annotated[
        Literal["-last_message_at", "last_message_at", "-created_at", "created_at"], Query()
    ] = "-last_message_at",
) -> Page[ConversationOut]:
    return await svc.list_(session, caller, params, status_, sort)


@router.get(
    "/{conversation_id}",
    response_model=ConversationOut,
    summary="Lire une conversation",
    responses={**COMMON, **NOT_FOUND},
)
async def read_conversation(
    conversation_id: uuid.UUID, caller: CallerDep, session: SessionDep
) -> ConversationOut:
    return svc.conversation_out(await svc.get_owned(session, caller, conversation_id))


@router.get(
    "/{conversation_id}/messages",
    response_model=CursorPage[MessageOut],
    summary="Historique des messages (pagination par curseur)",
    responses={**COMMON, **NOT_FOUND},
)
async def list_messages(
    conversation_id: uuid.UUID, caller: CallerDep, session: SessionDep, params: CursorParamsDep
) -> CursorPage[MessageOut]:
    return await svc.list_messages(session, caller, conversation_id, params)


@router.post(
    "/{conversation_id}/messages",
    response_model=ChatReply,
    summary="Envoyer un message et recevoir la réponse de l'agent",
    responses={
        **COMMON,
        **NOT_FOUND,
        409: {
            "model": ErrorResponse,
            "description": "Codes : CONVERSATION_CLOSED, IDEMPOTENCY_KEY_CONFLICT",
        },
        429: {"model": ErrorResponse, "description": "Codes : VISITOR_QUOTA_EXCEEDED"},
        503: {"model": ErrorResponse, "description": "Codes : LLM_UNAVAILABLE (+ secours)"},
        504: {"model": ErrorResponse, "description": "Codes : LLM_TIMEOUT"},
    },
)
async def post_message(
    conversation_id: uuid.UUID,
    payload: ChatMessageCreate,
    caller: CallerDep,
    session: SessionDep,
    settings: SettingsDep,
) -> ChatReply:
    stored = await svc.store_user_message(session, settings, caller, conversation_id, payload)
    conv = await svc.get_owned(session, caller, conversation_id, lock=True)

    # Réessai d'un message qui a déjà reçu sa réponse : on la renvoie sans rappeler le LLM.
    if stored.replayed:
        answer = await svc.next_assistant_message(session, conv.id, stored.message.seq)
        if answer is not None:
            await session.commit()
            return ChatReply(
                user_message=svc.message_out(stored.message),
                assistant_message=svc.message_out(answer),
                quota=stored.quota,
            )

    context = await svc.memory_context(session, conv.id, settings.memory_context_messages)
    await session.commit()
    reply = await get_chat_responder().reply(session, caller, conv, stored.message, context)

    conv = await svc.get_owned(session, caller, conversation_id, lock=True)
    assistant = await svc.append_message(
        session,
        conv,
        role="assistant",
        content=reply.text,
        now=svc.now_utc(),
        reply_language=reply.reply_language,
        finish_reason=reply.finish_reason,
        grounding=reply.grounding,
        sources=reply.sources,
        model_name=reply.model_name,
        prompt_version=reply.prompt_version,
        tokens_in=reply.tokens_in,
        tokens_out=reply.tokens_out,
        latency_ms=reply.latency_ms,
    )
    await session.commit()
    return ChatReply(
        user_message=svc.message_out(stored.message),
        assistant_message=svc.message_out(assistant),
        quota=stored.quota,
    )
