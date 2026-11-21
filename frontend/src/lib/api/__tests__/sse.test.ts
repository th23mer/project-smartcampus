import { describe, expect, it } from "vitest";
import type { ChatStreamEvent } from "../chat-types";
import { createApiClient } from "../client";
import {
  applyChatEvent,
  consumeChatStream,
  formatSseEvent,
  initialTurnState,
  parseSseStream,
  readChatStream,
  streamChatMessage,
} from "../sse";
import { buildMockEvents, createMockChatStream } from "@/lib/chat/mock-stream";

/** Flux simulé : chaque chaîne devient un morceau d'octets distinct. */
function streamOf(chunks: (string | Uint8Array)[]): ReadableStream<Uint8Array> {
  const enc = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const c of chunks) controller.enqueue(typeof c === "string" ? enc.encode(c) : c);
      controller.close();
    },
  });
}

async function collect<T>(gen: AsyncGenerator<T>): Promise<T[]> {
  const out: T[] = [];
  for await (const x of gen) out.push(x);
  return out;
}

describe("parseSseStream", () => {
  it("lit id, event et data et ignore les commentaires ping", async () => {
    const events = await collect(
      parseSseStream(streamOf([": ping\n\n", 'id: 1\nevent: delta\ndata: {"text":"Bon"}\n\n'])),
    );
    expect(events).toEqual([{ id: "1", event: "delta", data: '{"text":"Bon"}' }]);
  });

  it("reconstitue un événement coupé au milieu d'une ligne et d'un caractère UTF-8", async () => {
    const full = new TextEncoder().encode('event: delta\ndata: {"text":"année"}\n\n');
    // Coupe à l'intérieur du « é » (2 octets en UTF-8).
    const cut = full.indexOf(0xc3) + 1;
    const events = await collect(parseSseStream(streamOf([full.slice(0, 5), full.slice(5, cut), full.slice(cut)])));
    expect(events).toHaveLength(1);
    expect(JSON.parse(events[0].data)).toEqual({ text: "année" });
  });

  it("accepte les fins de ligne CRLF, y compris coupées entre deux morceaux", async () => {
    const events = await collect(
      parseSseStream(streamOf(["event: delta\r", "\ndata: {}\r\n\r", "\n"])),
    );
    expect(events).toEqual([{ id: null, event: "delta", data: "{}" }]);
  });

  it("joint plusieurs lignes data par un saut de ligne et garde le dernier id", async () => {
    const events = await collect(
      parseSseStream(streamOf(["id: 7\nevent: x\ndata: a\ndata: b\n\nevent: y\ndata: c\n\n"])),
    );
    expect(events).toEqual([
      { id: "7", event: "x", data: "a\nb" },
      { id: "7", event: "y", data: "c" },
    ]);
  });

  it("utilise « message » par défaut et émet un dernier événement sans ligne vide finale", async () => {
    const events = await collect(parseSseStream(streamOf(["data: fin"])));
    expect(events).toEqual([{ id: null, event: "message", data: "fin" }]);
  });

  it("ignore un bloc sans data", async () => {
    const events = await collect(parseSseStream(streamOf(["event: delta\n\n"])));
    expect(events).toEqual([]);
  });
});

describe("readChatStream", () => {
  it("décode les événements connus et ignore les inconnus", async () => {
    const events = await collect(
      readChatStream(
        streamOf([
          formatSseEvent({ id: 1, event: "inconnu.futur", data: { a: 1 } }),
          formatSseEvent({ id: 2, event: "delta", data: { text: "x" } }),
        ]),
      ),
    );
    expect(events).toEqual([{ event: "delta", id: "2", data: { text: "x" } }]);
  });

  it("lève UNEXPECTED_RESPONSE si data n'est pas du JSON", async () => {
    await expect(collect(readChatStream(streamOf(["event: delta\ndata: pas-du-json\n\n"])))).rejects.toMatchObject({
      code: "UNEXPECTED_RESPONSE",
    });
  });
});

describe("applyChatEvent / consumeChatStream", () => {
  it("rejoue un tour complet sourcé (frais) depuis le faux flux", async () => {
    const seen: string[] = [];
    const state = await consumeChatStream(createMockChatStream("slm, 9adech el frais ?", 0), {
      onEvent: (ev) => seen.push(ev.event),
    });
    expect(seen[0]).toBe("message.accepted");
    expect(seen).toContain("tool_call.started");
    expect(seen).toContain("citation");
    expect(seen).toContain("delta");
    expect(seen.at(-1)).toBe("message.completed");
    expect(state.status).toBe("completed");
    expect(state.userMessage?.language).toBe("aeb_latn");
    expect(state.citations.map((c) => c.id)).toEqual(["S1", "S2"]);
    expect(state.toolCalls.every((t) => t.status === "succeeded")).toBe(true);
    expect(state.assistantMessage?.grounding?.status).toBe("grounded");
    expect(state.quota?.messages_limit).toBe(30);
  });

  it("le message final remplace le texte accumulé par les delta", () => {
    const events: ChatStreamEvent[] = [
      { event: "delta", data: { text: "brouillon " } },
      { event: "delta", data: { text: "partiel" } },
    ];
    let s = events.reduce(applyChatEvent, initialTurnState);
    expect(s.text).toBe("brouillon partiel");
    s = applyChatEvent(s, {
      event: "message.completed",
      data: { assistant_message: { id: "a", role: "assistant", text: "Texte final" }, quota: null },
    });
    expect(s.text).toBe("Texte final");
    expect(s.status).toBe("completed");
  });

  it("met à jour un appel d'outil started → completed sans le dupliquer", () => {
    const base = { id: "tc_1", name: "get_fees", kind: "deterministic" as const, display_label: "Frais" };
    let s = applyChatEvent(initialTurnState, { event: "tool_call.started", data: { ...base, status: "running" } });
    s = applyChatEvent(s, { event: "tool_call.completed", data: { ...base, status: "succeeded", duration_ms: 84 } });
    expect(s.toolCalls).toEqual([{ ...base, status: "succeeded", duration_ms: 84 }]);
  });

  it("gère le secours déterministe : fallback puis error (LLM_UNAVAILABLE)", async () => {
    const state = await consumeChatStream(createMockChatStream("panne", 0));
    expect(state.status).toBe("fallback");
    expect(state.fallback?.links.length).toBeGreaterThan(0);
    expect(state.error?.code).toBe("LLM_UNAVAILABLE");
    expect(state.error?.requestId).toBe("req_mock_0001");
  });

  it("signale un flux interrompu sans événement de fin", async () => {
    const events = buildMockEvents("bonjour").slice(0, 3);
    const state = await consumeChatStream(
      streamOf(events.map((e, i) => formatSseEvent({ id: i + 1, event: e.event, data: e.data }))),
    );
    expect(state.status).toBe("error");
    expect(state.error?.code).toBe("UNEXPECTED_RESPONSE");
  });

  it("transforme un événement error isolé en ApiError", async () => {
    const state = await consumeChatStream(
      streamOf([
        formatSseEvent({
          event: "error",
          data: { error: { code: "CONVERSATION_CLOSED", message: "Cette conversation est fermée.", details: null, request_id: "req_x" } },
        }),
      ]),
    );
    expect(state.status).toBe("error");
    expect(state.error).toMatchObject({ code: "CONVERSATION_CLOSED", requestId: "req_x" });
  });
});

describe("streamChatMessage", () => {
  it("envoie un POST Accept: text/event-stream et lit la réponse", async () => {
    let captured: { url: string; init: RequestInit } | null = null;
    const client = createApiClient({
      baseUrl: "http://api.test",
      devAuth: false,
      fetchImpl: async (url, init) => {
        captured = { url: String(url), init: init ?? {} };
        return new Response(createMockChatStream("frais", 0), {
          status: 200,
          headers: { "Content-Type": "text/event-stream" },
        });
      },
    });
    const state = await streamChatMessage(client, "conv-1", {
      client_message_id: "6e0f2c1a-9b7d-4c4e-8f51-0d3b7a2e91c4",
      content: { type: "text", text: "frais" },
      language_hint: null,
    });
    expect(captured!.url).toBe("http://api.test/api/v1/conversations/conv-1/messages");
    expect(captured!.init.method).toBe("POST");
    expect((captured!.init.headers as Record<string, string>).Accept).toBe("text/event-stream");
    expect(state.status).toBe("completed");
  });

  it("lève l'erreur HTTP reçue avant le début du flux", async () => {
    const client = createApiClient({
      baseUrl: "http://api.test",
      devAuth: false,
      fetchImpl: async () =>
        new Response(
          JSON.stringify({
            error: { code: "VISITOR_QUOTA_EXCEEDED", message: "Limite atteinte.", details: { limit: 30 }, request_id: "req_q" },
          }),
          { status: 429, headers: { "Content-Type": "application/json" } },
        ),
    });
    await expect(
      streamChatMessage(client, "c", { client_message_id: "x", content: { type: "text", text: "a" }, language_hint: null }),
    ).rejects.toMatchObject({ code: "VISITOR_QUOTA_EXCEEDED", status: 429, details: { limit: 30 } });
  });
});
