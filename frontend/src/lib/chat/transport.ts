/**
 * Choix du transport du chat : faux flux local (par défaut) ou API réelle.
 * `NEXT_PUBLIC_CHAT_MOCK=false` bascule sur l'API quand E4 aura livré l'endpoint.
 */
import { api } from "@/lib/api/client";
import type { SendTextMessageRequest } from "@/lib/api/chat-types";
import { consumeChatStream, streamChatMessage, type ChatTurnState, type StreamChatOptions } from "@/lib/api/sse";
import { createMockChatStream } from "./mock-stream";

export const chatUsesMock = process.env.NEXT_PUBLIC_CHAT_MOCK !== "false";

function newClientMessageId(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `00000000-0000-4000-8000-${Date.now().toString().padStart(12, "0").slice(-12)}`;
}

let conversationId: string | null = null;

/** Crée la conversation au premier message (mode API réel). */
async function ensureConversation(): Promise<string> {
  if (conversationId) return conversationId;
  const conv = await api.post<{ id: string }>("/conversations", { channel: "web" });
  conversationId = conv.id;
  return conv.id;
}

/** Envoie un message texte et suit le flux jusqu'au bout. */
export async function sendChatMessage(text: string, options: StreamChatOptions = {}): Promise<ChatTurnState> {
  if (chatUsesMock) return consumeChatStream(createMockChatStream(text), options);
  const body: SendTextMessageRequest = {
    client_message_id: newClientMessageId(),
    content: { type: "text", text },
    language_hint: null,
  };
  return streamChatMessage(api, await ensureConversation(), body, options);
}
