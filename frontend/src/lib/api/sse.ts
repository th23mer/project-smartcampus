/**
 * Lecteur de flux SSE via fetch + ReadableStream (SA-5 §3.3).
 *
 * `EventSource` ne sait pas faire de POST : on lit donc le corps de la réponse
 * à la main, selon le format text/event-stream (WHATWG HTML §9.2) :
 * lignes `id:`, `event:`, `data:` (plusieurs lignes `data` jointes par `\n`),
 * commentaires `: ping` ignorés, événement terminé par une ligne vide.
 */
import type { ApiClient } from "./client";
import {
  CHAT_STREAM_EVENT_NAMES,
  type ChatMessage,
  type ChatStreamEvent,
  type ChatStreamEventName,
  type Citation,
  type Fallback,
  type Quota,
  type SendTextMessageRequest,
  type ToolCall,
  type Transcription,
} from "./chat-types";
import { ApiError, apiErrorFromBody, apiErrorFromException, CLIENT_ERROR_CODES } from "./errors";

/** Événement SSE brut, avant décodage JSON. */
export interface RawSseEvent {
  id: string | null;
  event: string;
  data: string;
}

/**
 * Découpe un flux d'octets en événements SSE.
 * Gère les fins de ligne LF, CRLF et CR, les caractères UTF-8 coupés entre
 * deux morceaux et les commentaires. Un dernier événement sans ligne vide
 * finale est tout de même émis s'il porte des données (tolérance).
 */
export async function* parseSseStream(
  stream: ReadableStream<Uint8Array>,
  signal?: AbortSignal,
): AsyncGenerator<RawSseEvent> {
  const reader = stream.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  let lastId: string | null = null;
  let eventName = "";
  let dataLines: string[] = [];
  let hasData = false;

  const flush = (): RawSseEvent | null => {
    if (!hasData) {
      eventName = "";
      return null;
    }
    const ev: RawSseEvent = { id: lastId, event: eventName || "message", data: dataLines.join("\n") };
    eventName = "";
    dataLines = [];
    hasData = false;
    return ev;
  };

  const processLine = (line: string): RawSseEvent | null => {
    if (line === "") return flush();
    if (line.startsWith(":")) return null; // commentaire (ping)
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    switch (field) {
      case "event":
        eventName = value;
        break;
      case "data":
        dataLines.push(value);
        hasData = true;
        break;
      case "id":
        if (!value.includes("\0")) lastId = value;
        break;
      default:
        // `retry` et champs inconnus : ignorés (pas de reconnexion automatique).
        break;
    }
    return null;
  };

  try {
    while (true) {
      if (signal?.aborted) throw new DOMException("Flux annulé", "AbortError");
      const { value, done } = await reader.read();
      buffer += done ? decoder.decode() : decoder.decode(value, { stream: true });

      // Extrait toutes les lignes complètes. Un `\r` en fin de tampon peut être
      // suivi d'un `\n` au prochain morceau : on le garde de côté sauf à la fin.
      let start = 0;
      for (let i = 0; i < buffer.length; i++) {
        const ch = buffer[i];
        if (ch !== "\n" && ch !== "\r") continue;
        if (ch === "\r" && i === buffer.length - 1 && !done) break;
        const line = buffer.slice(start, i);
        if (ch === "\r" && buffer[i + 1] === "\n") i++;
        start = i + 1;
        const ev = processLine(line);
        if (ev) yield ev;
      }
      buffer = buffer.slice(start);

      if (done) {
        if (buffer.length > 0) {
          const ev = processLine(buffer);
          buffer = "";
          if (ev) yield ev;
        }
        const last = flush();
        if (last) yield last;
        return;
      }
    }
  } finally {
    // Ferme la connexion si on s'arrête avant la fin (break, annulation, erreur).
    await reader.cancel().catch(() => undefined);
  }
}

function isKnownEvent(name: string): name is ChatStreamEventName {
  return (CHAT_STREAM_EVENT_NAMES as readonly string[]).includes(name);
}

/**
 * Décode les événements du chat en objets typés.
 * Les événements inconnus sont ignorés (compatibilité ascendante) ;
 * un `data` non JSON lève une ApiError `UNEXPECTED_RESPONSE`.
 */
export async function* readChatStream(
  stream: ReadableStream<Uint8Array>,
  signal?: AbortSignal,
): AsyncGenerator<ChatStreamEvent> {
  for await (const raw of parseSseStream(stream, signal)) {
    if (!isKnownEvent(raw.event)) continue;
    let data: unknown;
    try {
      data = JSON.parse(raw.data);
    } catch {
      throw new ApiError({
        code: CLIENT_ERROR_CODES.UNEXPECTED_RESPONSE,
        message: "Flux de réponse illisible.",
        status: 200,
      });
    }
    yield { event: raw.event, id: raw.id ?? undefined, data } as ChatStreamEvent;
  }
}

/* ------------------------------------------------------------------------ */
/* État d'un tour de chat, reconstruit à partir des événements.             */
/* ------------------------------------------------------------------------ */

export type TurnStatus = "streaming" | "completed" | "fallback" | "error";

export interface ChatTurnState {
  status: TurnStatus;
  userMessage: ChatMessage | null;
  transcription: Transcription | null;
  /** Texte accumulé par les `delta` (remplacé par le message final). */
  text: string;
  toolCalls: ToolCall[];
  citations: Citation[];
  assistantMessage: ChatMessage | null;
  quota: Quota | null;
  fallback: Fallback | null;
  error: ApiError | null;
}

export const initialTurnState: ChatTurnState = {
  status: "streaming",
  userMessage: null,
  transcription: null,
  text: "",
  toolCalls: [],
  citations: [],
  assistantMessage: null,
  quota: null,
  fallback: null,
  error: null,
};

function upsertToolCall(list: ToolCall[], call: ToolCall): ToolCall[] {
  const i = list.findIndex((c) => c.id === call.id);
  if (i === -1) return [...list, call];
  const next = list.slice();
  next[i] = { ...next[i], ...call };
  return next;
}

/** Réducteur pur : applique un événement SSE à l'état du tour. */
export function applyChatEvent(state: ChatTurnState, ev: ChatStreamEvent): ChatTurnState {
  switch (ev.event) {
    case "message.accepted":
      return { ...state, userMessage: ev.data.user_message };
    case "transcription.completed":
      return { ...state, transcription: ev.data };
    case "tool_call.started":
    case "tool_call.completed":
      return { ...state, toolCalls: upsertToolCall(state.toolCalls, ev.data) };
    case "citation":
      return state.citations.some((c) => c.id === ev.data.id)
        ? state
        : { ...state, citations: [...state.citations, ev.data] };
    case "delta":
      return { ...state, text: state.text + ev.data.text };
    case "message.completed": {
      // Le message final fait foi : il remplace le texte accumulé.
      const msg = ev.data.assistant_message;
      return {
        ...state,
        status: "completed",
        assistantMessage: msg,
        text: msg.text,
        citations: msg.citations ?? state.citations,
        toolCalls: msg.tool_calls ?? state.toolCalls,
        quota: ev.data.quota,
      };
    }
    case "fallback":
      return { ...state, status: "fallback", fallback: ev.data };
    case "error":
      return {
        ...state,
        // Après un `fallback`, l'erreur accompagne le secours : on garde l'état « fallback ».
        status: state.status === "fallback" ? "fallback" : "error",
        error: apiErrorFromBody(ev.data, 200),
      };
  }
}

/* ------------------------------------------------------------------------ */
/* Envoi d'un message avec réponse en flux.                                 */
/* ------------------------------------------------------------------------ */

export interface StreamChatOptions {
  signal?: AbortSignal;
  onEvent?: (ev: ChatStreamEvent, state: ChatTurnState) => void;
}

/**
 * `POST /conversations/{id}/messages` avec `Accept: text/event-stream`.
 * Une erreur HTTP avant le flux est levée (ApiError) ; une erreur pendant
 * le flux arrive comme événement `error` et se retrouve dans l'état final.
 */
export async function streamChatMessage(
  client: ApiClient,
  conversationId: string,
  body: SendTextMessageRequest,
  options: StreamChatOptions = {},
): Promise<ChatTurnState> {
  const response = await client.raw(`/conversations/${encodeURIComponent(conversationId)}/messages`, {
    method: "POST",
    body,
    headers: { Accept: "text/event-stream" },
    signal: options.signal,
  });
  if (!response.body) {
    throw new ApiError({
      code: CLIENT_ERROR_CODES.UNEXPECTED_RESPONSE,
      message: "Réponse sans flux.",
      status: response.status,
    });
  }
  return consumeChatStream(response.body, options);
}

/** Lit un flux de chat jusqu'au bout et renvoie l'état final du tour. */
export async function consumeChatStream(
  stream: ReadableStream<Uint8Array>,
  options: StreamChatOptions = {},
): Promise<ChatTurnState> {
  let state = initialTurnState;
  try {
    for await (const ev of readChatStream(stream, options.signal)) {
      state = applyChatEvent(state, ev);
      options.onEvent?.(ev, state);
      if (ev.event === "message.completed" || ev.event === "error") break;
    }
  } catch (err) {
    const error = apiErrorFromException(err);
    return { ...state, status: state.status === "fallback" ? "fallback" : "error", error };
  }
  if (state.status === "streaming") {
    // Flux coupé sans événement de fin : le front relira l'historique (SA-5 §3.3).
    return {
      ...state,
      status: "error",
      error: new ApiError({
        code: CLIENT_ERROR_CODES.UNEXPECTED_RESPONSE,
        message: "La réponse a été interrompue. Réessayez.",
        status: 200,
      }),
    };
  }
  return state;
}

/** Sérialise un événement au format SSE (utile pour le faux flux et les tests). */
export function formatSseEvent(ev: { id?: string | number; event: string; data: unknown }): string {
  const lines: string[] = [];
  if (ev.id !== undefined) lines.push(`id: ${ev.id}`);
  lines.push(`event: ${ev.event}`);
  lines.push(`data: ${JSON.stringify(ev.data)}`);
  return `${lines.join("\n")}\n\n`;
}
