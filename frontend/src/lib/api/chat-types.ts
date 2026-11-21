/**
 * Types du contrat de chat (SA-5 §3). Les champs facultatifs reflètent
 * le fait que certains événements SSE n'envoient qu'une partie du message.
 */
import type { ApiErrorEnvelope, LanguageCode } from "./types";

export interface Transcription {
  text: string;
  language: LanguageCode;
  confidence: number;
  duration_s?: number;
}

export interface CitationSource {
  entity_type: string;
  entity_id?: string;
  version: number;
  published_at?: string;
  valid_from: string | null;
  valid_to: string | null;
}

/** Carte source officielle (F1). */
export interface Citation {
  id: string;
  kind: "catalogue" | "document" | "faq" | string;
  title: string;
  institution?: "iit" | "isb" | string | null;
  source: CitationSource | null;
  document_version_id?: string | null;
  page?: number | null;
  excerpt?: string | null;
  url?: string | null;
}

export type ToolCallKind = "deterministic" | "retrieval" | "ai";
export type ToolCallStatus = "running" | "succeeded" | "failed";

export interface ToolCall {
  id: string;
  name: string;
  kind: ToolCallKind;
  display_label: string;
  status: ToolCallStatus;
  duration_ms?: number;
  summary?: string | null;
}

export interface SuggestedAction {
  type: string;
  label: string;
  requires_confirmation: boolean;
  payload: Record<string, unknown>;
}

export type FinishReason =
  | "completed"
  | "clarification_requested"
  | "fallback_human"
  | "fallback_deterministic"
  | "length"
  | "refused";

export interface Grounding {
  status: "grounded" | "partial" | "no_official_source" | "not_applicable";
  knowledge_gap_id: string | null;
}

export interface ChatMessage {
  id: string;
  conversation_id?: string;
  role: "user" | "assistant" | "system_notice";
  content_type?: "text" | "audio";
  text: string;
  language?: LanguageCode;
  reply_language?: LanguageCode;
  transcription?: Transcription | null;
  audio_expires_at?: string | null;
  citations?: Citation[];
  tool_calls?: ToolCall[];
  grounding?: Grounding;
  suggested_actions?: SuggestedAction[];
  finish_reason?: FinishReason;
  created_at?: string;
}

export interface Quota {
  messages_used: number;
  messages_limit: number;
  resets_at: string;
}

export interface FallbackLink {
  title: string;
  url: string;
  kind: string;
  source: Partial<CitationSource> | null;
}

/** Secours déterministe (SA-5 §3.5, décision D-E). */
export interface Fallback {
  message_id?: string;
  text: string;
  links: FallbackLink[];
  suggested_actions: SuggestedAction[];
}

/** Corps de `POST /conversations/{id}/messages` (texte). */
export interface SendTextMessageRequest {
  client_message_id: string;
  content: { type: "text"; text: string };
  language_hint: LanguageCode | null;
}

/** Union discriminée des événements SSE du chat (SA-5 §3.3). */
export type ChatStreamEvent =
  | { event: "message.accepted"; id?: string; data: { user_message: ChatMessage } }
  | { event: "transcription.completed"; id?: string; data: Transcription }
  | { event: "tool_call.started"; id?: string; data: ToolCall }
  | { event: "tool_call.completed"; id?: string; data: ToolCall }
  | { event: "citation"; id?: string; data: Citation }
  | { event: "delta"; id?: string; data: { text: string } }
  | {
      event: "message.completed";
      id?: string;
      data: { assistant_message: ChatMessage; quota: Quota | null };
    }
  | { event: "fallback"; id?: string; data: Fallback }
  | { event: "error"; id?: string; data: ApiErrorEnvelope };

export type ChatStreamEventName = ChatStreamEvent["event"];

export const CHAT_STREAM_EVENT_NAMES: readonly ChatStreamEventName[] = [
  "message.accepted",
  "transcription.completed",
  "tool_call.started",
  "tool_call.completed",
  "citation",
  "delta",
  "message.completed",
  "fallback",
  "error",
] as const;
