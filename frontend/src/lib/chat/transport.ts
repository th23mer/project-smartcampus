/**
 * Transport du chat : API réelle (par défaut) ou faux flux local (`NEXT_PUBLIC_CHAT_MOCK=true`).
 *
 * API réelle (E3, SA-25 / SA-26) :
 * 1. visiteur sans compte : au premier message, `POST /visitor-sessions` pose le cookie
 *    httpOnly `sc_visitor` (session réutilisée si elle existe déjà) ;
 * 2. `POST /conversations` ouvre la conversation (visiteur ou candidat connecté) ;
 * 3. `POST /conversations/{id}/messages` : réponse JSON aujourd'hui, flux SSE quand E4
 *    l'aura branché (on accepte les deux et on lit selon le `Content-Type`).
 *
 * Cas gérés : session expirée (410) ou conversation introuvable (404, p. ex. après une
 * connexion sans rattachement) → nouvelle session / conversation et un seul nouvel essai ;
 * LLM indisponible (503) → secours déterministe affiché, le message reste enregistré.
 */
import { api } from "@/lib/api/client";
import type { ChatMessage, Fallback, Quota, SendTextMessageRequest } from "@/lib/api/chat-types";
import { ApiError } from "@/lib/api/errors";
import { consumeChatStream, initialTurnState, type ChatTurnState, type StreamChatOptions } from "@/lib/api/sse";
import { getAccessToken } from "@/lib/auth/token";
import { newUuid } from "@/lib/auth/session";
import { createMockChatStream } from "./mock-stream";

export const chatUsesMock = process.env.NEXT_PUBLIC_CHAT_MOCK === "true";

/** Réponse JSON de `POST /conversations/{id}/messages` (SA-5 §3.2). */
export interface ChatReply {
  user_message: ChatMessage;
  assistant_message: ChatMessage;
  quota: Quota | null;
}

interface ChatContext {
  conversationId: string | null;
  /** « visitor » ou « user » : la conversation change avec l'identité. */
  owner: "visitor" | "user" | null;
  visitorReady: boolean;
}

const ctx: ChatContext = { conversationId: null, owner: null, visitorReady: false };

/** Oublie la conversation courante (déconnexion, nouvelle conversation). */
export function resetChat(): void {
  ctx.conversationId = null;
  ctx.owner = null;
  ctx.visitorReady = false;
}

async function ensureConversation(): Promise<string> {
  const owner = getAccessToken() ? "user" : "visitor";
  if (ctx.owner !== owner) resetChat();
  ctx.owner = owner;
  if (owner === "visitor" && !ctx.visitorReady) {
    await api.post("/visitor-sessions", { locale: "fr" }, { skipDevAuth: true });
    ctx.visitorReady = true;
  }
  if (!ctx.conversationId) {
    const conv = await api.post<{ id: string }>(
      "/conversations",
      { channel: "web" },
      { skipDevAuth: true, idempotencyKey: newUuid() },
    );
    ctx.conversationId = conv.id;
  }
  return ctx.conversationId;
}

/** Codes après lesquels on repart d'une session / conversation neuve (un seul essai). */
const RESTART_CODES = new Set(["SESSION_EXPIRED", "NOT_FOUND", "UNAUTHENTICATED"]);

function stateFromReply(reply: ChatReply): ChatTurnState {
  return {
    ...initialTurnState,
    status: "completed",
    userMessage: reply.user_message,
    assistantMessage: reply.assistant_message,
    text: reply.assistant_message.text,
    citations: reply.assistant_message.citations ?? [],
    toolCalls: reply.assistant_message.tool_calls ?? [],
    quota: reply.quota,
  };
}

function fallbackOf(err: ApiError): Fallback | null {
  const details = err.details;
  if (!details || Array.isArray(details)) return null;
  const fb = (details as Record<string, unknown>).fallback;
  return fb && typeof fb === "object" ? (fb as Fallback) : null;
}

async function postMessage(body: SendTextMessageRequest, options: StreamChatOptions): Promise<ChatTurnState> {
  const conversationId = await ensureConversation();
  const response = await api.raw(`/conversations/${encodeURIComponent(conversationId)}/messages`, {
    method: "POST",
    body,
    headers: { Accept: "text/event-stream, application/json" },
    signal: options.signal,
    skipDevAuth: true,
  });
  if (response.headers.get("Content-Type")?.includes("text/event-stream") && response.body) {
    return consumeChatStream(response.body, options);
  }
  return stateFromReply((await response.json()) as ChatReply);
}

/** Quota du visiteur (le 503 de secours ne le contient pas) ; null pour un compte. */
async function visitorQuota(): Promise<Quota | null> {
  if (ctx.owner !== "visitor") return null;
  try {
    const session = await api.get<{ quota: Quota }>("/visitor-sessions/current", { skipDevAuth: true });
    return session.quota;
  } catch {
    return null;
  }
}

/** Envoie un message texte et renvoie l'état final du tour. */
export async function sendChatMessage(text: string, options: StreamChatOptions = {}): Promise<ChatTurnState> {
  if (chatUsesMock) return consumeChatStream(createMockChatStream(text), options);
  const body: SendTextMessageRequest = {
    client_message_id: newUuid(),
    content: { type: "text", text },
    language_hint: null,
  };
  for (let attempt = 0; ; attempt++) {
    try {
      return await postMessage(body, options);
    } catch (err) {
      if (!(err instanceof ApiError)) throw err;
      if (attempt === 0 && RESTART_CODES.has(err.code)) {
        resetChat();
        continue;
      }
      const fallback = fallbackOf(err);
      if (fallback) {
        return { ...initialTurnState, status: "fallback", fallback, error: err, quota: await visitorQuota() };
      }
      throw err;
    }
  }
}
