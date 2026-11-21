"use client";

/**
 * Indicateur d'état du backend : appelle `GET /api/v1/health` au montage puis
 * toutes les 30 s. Un backend arrêté donne « hors ligne », sans erreur visible.
 */
import { useEffect, useState } from "react";
import { api } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { cn } from "@/lib/utils";

type Status = "checking" | "ok" | "degraded" | "down";

const LABELS: Record<Status, string> = {
  checking: "Vérification…",
  ok: "API en ligne",
  degraded: "API dégradée",
  down: "API hors ligne",
};

const DOTS: Record<Status, string> = {
  checking: "bg-muted-foreground animate-pulse",
  ok: "bg-emerald-500",
  degraded: "bg-amber-500",
  down: "bg-red-500",
};

export function BackendStatus({ className }: { className?: string }) {
  const [status, setStatus] = useState<Status>("checking");
  const [detail, setDetail] = useState<string>("");

  useEffect(() => {
    let active = true;
    let controller: AbortController | null = null;

    async function check() {
      controller?.abort();
      controller = new AbortController();
      const timeout = setTimeout(() => controller?.abort(), 5000);
      try {
        const health = await api.getHealth(controller.signal);
        if (!active) return;
        setStatus(health.status === "ok" ? "ok" : "degraded");
        setDetail(health.version ? `version ${health.version}` : "");
      } catch (err) {
        if (!active) return;
        setStatus("down");
        setDetail(err instanceof ApiError ? err.code : "");
      } finally {
        clearTimeout(timeout);
      }
    }

    check();
    const timer = setInterval(check, 30_000);
    return () => {
      active = false;
      clearInterval(timer);
      controller?.abort();
    };
  }, []);

  return (
    <span
      role="status"
      aria-live="polite"
      title={`${api.baseUrl}/api/v1/health${detail ? ` · ${detail}` : ""}`}
      className={cn(
        "inline-flex items-center gap-2 rounded-full border px-2.5 py-1 text-xs text-muted-foreground",
        className,
      )}
    >
      <span className={cn("size-2 rounded-full", DOTS[status])} aria-hidden />
      {LABELS[status]}
    </span>
  );
}
