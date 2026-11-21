"use client";

/**
 * Composant de conversation : bulles, puces d'outils, cartes sources (F1),
 * secours déterministe, zone de saisie et bouton micro (désactivé pour l'instant).
 * Branché sur le faux flux local tant que l'endpoint d'E4 n'existe pas.
 */
import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { Loader2, Mic, RotateCcw, SendHorizontal, Check, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import { SourceCard } from "./source-card";
import type { ToolCall } from "@/lib/api/chat-types";
import { initialTurnState, type ChatTurnState } from "@/lib/api/sse";
import { apiErrorFromException, userMessage } from "@/lib/api/errors";
import { chatUsesMock, sendChatMessage } from "@/lib/chat/transport";
import { cn } from "@/lib/utils";
import { isDev } from "@/lib/config";

interface Turn {
  key: number;
  userText: string;
  state: ChatTurnState;
}

const SUGGESTIONS = [
  "slm, 9adech el frais mta3 licence génie logiciel ?",
  "Quelle différence entre la Prépa et la Licence ?",
  "Test du mode panne (secours)",
];

const MAX_LEN = 2000;

function ToolChip({ call }: { call: ToolCall }) {
  const running = call.status === "running";
  return (
    <span className="inline-flex items-center gap-1 rounded-full border bg-background px-2 py-0.5 text-[11px] text-muted-foreground">
      {running ? (
        <Loader2 className="size-3 animate-spin" aria-hidden />
      ) : call.status === "succeeded" ? (
        <Check className="size-3 text-emerald-600" aria-hidden />
      ) : (
        <X className="size-3 text-red-600" aria-hidden />
      )}
      {call.display_label}
      {call.kind === "deterministic" && <span className="text-[10px] opacity-70">· code</span>}
    </span>
  );
}

function AssistantTurn({ turn, onRetry }: { turn: Turn; onRetry: () => void }) {
  const { state } = turn;
  const streaming = state.status === "streaming";
  return (
    <div className="flex flex-col items-start gap-2">
      {state.toolCalls.length > 0 && (
        <div className="flex flex-wrap gap-1.5" aria-label="Outils consultés">
          {state.toolCalls.map((c) => (
            <ToolChip key={c.id} call={c} />
          ))}
        </div>
      )}

      {(state.text || streaming) && state.status !== "fallback" && (
        <div className="max-w-[85%] rounded-2xl rounded-ss-sm bg-muted px-4 py-2.5 text-sm leading-relaxed">
          {state.text || <span className="text-muted-foreground">L&apos;assistant réfléchit…</span>}
          {streaming && state.text && <span className="ms-0.5 inline-block h-4 w-1.5 animate-pulse bg-foreground/50 align-middle" />}
        </div>
      )}

      {/* Emplacement des cartes sources officielles (F1). */}
      {state.citations.length > 0 && (
        <section className="grid w-full max-w-[85%] gap-2 sm:grid-cols-2" aria-label="Sources officielles">
          {state.citations.map((c) => (
            <SourceCard key={c.id} citation={c} />
          ))}
        </section>
      )}

      {state.assistantMessage?.grounding?.status === "no_official_source" && (
        <Badge variant="outline" className="border-amber-400 text-amber-700 dark:text-amber-300">
          Aucune source officielle : question transmise à l&apos;équipe
        </Badge>
      )}

      {state.status === "fallback" && state.fallback && (
        <div className="max-w-[85%] rounded-2xl border border-amber-300 bg-amber-50 px-4 py-2.5 text-sm dark:bg-amber-950/40">
          <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-amber-700 dark:text-amber-300">
            Assistant indisponible · réponse de secours
          </p>
          <p>{state.fallback.text}</p>
          <ul className="mt-2 list-disc ps-5 text-xs">
            {state.fallback.links.map((l) => (
              <li key={l.title}>{l.title}</li>
            ))}
          </ul>
        </div>
      )}

      {state.error && (
        <div className="flex items-center gap-2 text-xs text-red-700 dark:text-red-400" role="alert">
          <span>{userMessage(state.error)}</span>
          <Button size="sm" variant="ghost" className="h-7 px-2" onClick={onRetry}>
            <RotateCcw className="size-3.5" /> Réessayer
          </Button>
        </div>
      )}

      {state.assistantMessage?.suggested_actions && state.assistantMessage.suggested_actions.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {state.assistantMessage.suggested_actions.map((a) => (
            <Button key={a.type} size="sm" variant="outline" className="h-7 text-xs" disabled title="Bientôt disponible">
              {a.label}
            </Button>
          ))}
        </div>
      )}
    </div>
  );
}

export function ChatPanel({ className }: { className?: string }) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const keyRef = useRef(0);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns]);

  useEffect(() => () => abortRef.current?.abort(), []);

  // Dev uniquement : `?demo=<message>` envoie un message au chargement (captures, démos).
  // Le minuteur annulé au démontage évite un double envoi en mode strict de React.
  useEffect(() => {
    if (!isDev) return;
    const demo = new URLSearchParams(window.location.search).get("demo");
    if (!demo) return;
    const timer = setTimeout(() => void send(demo), 0);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function send(text: string) {
    const clean = text.trim().slice(0, MAX_LEN);
    if (!clean || busy) return;
    const key = ++keyRef.current;
    const update = (state: ChatTurnState) =>
      setTurns((prev) => prev.map((t) => (t.key === key ? { ...t, state } : t)));

    setTurns((prev) => [...prev, { key, userText: clean, state: initialTurnState }]);
    setInput("");
    setBusy(true);
    abortRef.current = new AbortController();
    try {
      const final = await sendChatMessage(clean, {
        signal: abortRef.current.signal,
        onEvent: (_ev, state) => update(state),
      });
      update(final);
    } catch (err) {
      update({ ...initialTurnState, status: "error", error: apiErrorFromException(err) });
    } finally {
      setBusy(false);
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    void send(input);
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void send(input);
    }
  }

  return (
    <div className={cn("flex h-full min-h-[28rem] flex-col rounded-xl border bg-card shadow-sm", className)}>
      <div className="flex items-center justify-between border-b px-4 py-2.5">
        <div>
          <p className="text-sm font-semibold">Assistant d&apos;orientation</p>
          <p className="text-xs text-muted-foreground">Français · tunisien · arabizi</p>
        </div>
        {chatUsesMock && (
          <Badge variant="outline" className="text-[10px]">
            Flux simulé
          </Badge>
        )}
      </div>

      <div className="flex-1 space-y-5 overflow-y-auto px-4 py-4" aria-live="polite">
        {turns.length === 0 && (
          <div className="flex h-full flex-col items-center justify-center gap-3 text-center text-sm text-muted-foreground">
            <p>Pose ta question sur l&apos;IIT ou l&apos;ISB : formations, conditions, frais, passerelles.</p>
            <div className="flex flex-wrap justify-center gap-2">
              {SUGGESTIONS.map((s) => (
                <Button
                  key={s}
                  variant="outline"
                  size="sm"
                  className="h-auto whitespace-normal py-1.5 text-xs"
                  onClick={() => void send(s.startsWith("Test") ? "panne" : s)}
                >
                  {s}
                </Button>
              ))}
            </div>
          </div>
        )}
        {turns.map((t) => (
          <div key={t.key} className="space-y-2">
            <div className="flex justify-end">
              <div className="max-w-[85%] rounded-2xl rounded-se-sm bg-primary px-4 py-2.5 text-sm text-primary-foreground">
                {t.state.userMessage?.text ?? t.userText}
              </div>
            </div>
            <AssistantTurn turn={t} onRetry={() => void send(t.userText)} />
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      <form onSubmit={onSubmit} className="flex items-end gap-2 border-t p-3">
        <Textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Écris ton message… (Entrée pour envoyer)"
          aria-label="Votre message"
          maxLength={MAX_LEN}
          rows={1}
          className="max-h-32 min-h-10 resize-none"
        />
        <Button
          type="button"
          variant="outline"
          size="icon"
          disabled
          aria-label="Message vocal (bientôt disponible)"
          title="Message vocal : bientôt disponible"
        >
          <Mic />
        </Button>
        <Button type="submit" size="icon" disabled={busy || !input.trim()} aria-label="Envoyer">
          {busy ? <Loader2 className="animate-spin" /> : <SendHorizontal className="rtl:-scale-x-100" />}
        </Button>
      </form>
    </div>
  );
}
