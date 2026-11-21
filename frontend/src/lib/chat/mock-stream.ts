/**
 * Faux flux de chat local, conforme aux événements SA-5 §3.3.
 * Sert tant que l'endpoint réel d'E4 n'existe pas. Données 100 % fictives.
 *
 * Scénarios (choisis par mots-clés dans le message) :
 * - « frais », « 9adech », « prix » → réponse sourcée avec 2 cartes sources (F1) ;
 * - « panne » → LLM indisponible : événement `fallback` puis `error` (D-E) ;
 * - sinon → réponse sans source officielle (`no_official_source`).
 */
import type { ChatMessage, ChatStreamEvent, Citation, ToolCall } from "@/lib/api/chat-types";
import { formatSseEvent } from "@/lib/api/sse";

const CONVERSATION_ID = "00000000-0000-4000-8000-00000000c0de";

function uuid(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return "00000000-0000-4000-8000-" + Math.floor(Math.random() * 1e12).toString().padStart(12, "0");
}

const FEES_CITATIONS: Citation[] = [
  {
    id: "S1",
    kind: "catalogue",
    title: "Frais de scolarité 2026-2027 – Licence en génie logiciel (fictif)",
    institution: "iit",
    source: {
      entity_type: "fee_schedule",
      entity_id: "e3f4f41f-cfe1-56fe-8280-da3cd6335b6b",
      version: 2,
      published_at: "2026-07-01T08:00:00Z",
      valid_from: "2026-09-01",
      valid_to: "2027-08-31",
    },
    document_version_id: null,
    page: null,
    excerpt: "Frais annuels : 6 500,000 TND ; inscription : 300,000 TND.",
    url: "/api/v1/catalogue/programmes/9b8a8c62-420a-54bb-9a69-0b920d20ccb7/fees",
  },
  {
    id: "S2",
    kind: "document",
    title: "Guide des admissions IIT 2026 (fictif), v2",
    institution: "iit",
    source: {
      entity_type: "document_version",
      entity_id: "67157c63-a214-5098-a348-85513bccf099",
      version: 2,
      published_at: "2026-07-10T08:00:00Z",
      valid_from: "2026-09-01",
      valid_to: "2027-08-31",
    },
    document_version_id: "67157c63-a214-5098-a348-85513bccf099",
    page: 4,
    excerpt: "Le paiement peut être échelonné en trois tranches…",
    url: null,
  },
];

const FEES_TOOLS: ToolCall[] = [
  {
    id: "tc_1",
    name: "get_fees",
    kind: "deterministic",
    display_label: "Consultation des frais officiels",
    status: "succeeded",
    duration_ms: 84,
    summary: "1 grille de frais valide trouvée",
  },
  {
    id: "tc_2",
    name: "search_documents",
    kind: "retrieval",
    display_label: "Recherche dans les documents officiels",
    status: "succeeded",
    duration_ms: 412,
    summary: "3 passages pertinents",
  },
];

function chunks(text: string, size = 3): string[] {
  const words = text.split(/(?<=\s)/);
  const out: string[] = [];
  for (let i = 0; i < words.length; i += size) out.push(words.slice(i, i + size).join(""));
  return out;
}

/** Construit la suite d'événements d'un tour simulé. */
export function buildMockEvents(userText: string): ChatStreamEvent[] {
  const now = new Date().toISOString();
  const user: ChatMessage = {
    id: uuid(),
    conversation_id: CONVERSATION_ID,
    role: "user",
    content_type: "text",
    text: userText,
    language: /[a-z]*[2379][a-z]+/i.test(userText) ? "aeb_latn" : "fr",
    created_at: now,
  };
  const events: ChatStreamEvent[] = [{ event: "message.accepted", data: { user_message: user } }];
  const lower = userText.toLowerCase();

  if (lower.includes("panne")) {
    events.push({
      event: "fallback",
      data: {
        message_id: uuid(),
        text: "Je ne peux pas répondre pour le moment. Voici les informations officielles qui peuvent t'aider, et tu peux prendre rendez-vous avec un conseiller.",
        links: [
          { title: "FAQ des admissions IIT (fictive)", url: "#", kind: "faq", source: null },
        ],
        suggested_actions: [
          { type: "contact_human", label: "Être recontacté", requires_confirmation: true, payload: {} },
        ],
      },
    });
    events.push({
      event: "error",
      data: {
        error: {
          code: "LLM_UNAVAILABLE",
          message: "L'assistant est momentanément indisponible.",
          details: { retry_after_s: 30 },
          request_id: "req_mock_0001",
        },
      },
    });
    return events;
  }

  const isFees = /frais|9adech|prix|co[uû]t/.test(lower);
  const text = isFees
    ? "Pour l'année 2026-2027, les frais de la Licence en génie logiciel sont de 6 500,000 TND par an, plus 300,000 TND d'inscription [S1]. Le paiement peut se faire en trois tranches [S2]. Tu veux que je compare avec le cycle préparatoire ?"
    : "Je n'ai pas trouvé d'information officielle publiée sur ce point. Je peux te mettre en relation avec un conseiller des admissions, et ta question est transmise à l'équipe.";
  const tools = isFees
    ? FEES_TOOLS
    : [
        {
          id: "tc_1",
          name: "search_documents",
          kind: "retrieval",
          display_label: "Recherche dans les documents officiels",
          status: "succeeded",
          duration_ms: 390,
          summary: "Aucun passage pertinent",
        } satisfies ToolCall,
      ];
  const citations = isFees ? FEES_CITATIONS : [];

  for (const t of tools) {
    events.push({ event: "tool_call.started", data: { ...t, status: "running", duration_ms: undefined, summary: null } });
    events.push({ event: "tool_call.completed", data: t });
  }
  for (const c of citations) events.push({ event: "citation", data: c });
  for (const piece of chunks(text)) events.push({ event: "delta", data: { text: piece } });

  events.push({
    event: "message.completed",
    data: {
      assistant_message: {
        id: uuid(),
        conversation_id: CONVERSATION_ID,
        role: "assistant",
        content_type: "text",
        text,
        language: "fr",
        reply_language: "fr",
        citations,
        tool_calls: tools,
        grounding: { status: isFees ? "grounded" : "no_official_source", knowledge_gap_id: null },
        suggested_actions: isFees
          ? [{ type: "compare_programmes", label: "Comparer avec la Prépa", requires_confirmation: false, payload: {} }]
          : [{ type: "contact_human", label: "Parler à un conseiller", requires_confirmation: true, payload: {} }],
        finish_reason: "completed",
        created_at: new Date().toISOString(),
      },
      quota: { messages_used: 1, messages_limit: 30, resets_at: "2026-11-17T10:00:00Z" },
    },
  });
  return events;
}

/**
 * Renvoie un ReadableStream d'octets au format text/event-stream,
 * avec un léger délai entre les événements pour simuler le streaming.
 */
export function createMockChatStream(userText: string, delayMs = 60): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  const events = buildMockEvents(userText);
  let index = 0;
  let cancelled = false;
  return new ReadableStream<Uint8Array>({
    async pull(controller) {
      if (cancelled) return;
      if (index === 0) controller.enqueue(encoder.encode(": ping\n\n"));
      if (index >= events.length) {
        controller.close();
        return;
      }
      if (delayMs > 0) await new Promise((r) => setTimeout(r, delayMs));
      if (cancelled) return;
      const ev = events[index];
      controller.enqueue(encoder.encode(formatSseEvent({ id: index + 1, event: ev.event, data: ev.data })));
      index++;
    },
    cancel() {
      cancelled = true;
    },
  });
}
