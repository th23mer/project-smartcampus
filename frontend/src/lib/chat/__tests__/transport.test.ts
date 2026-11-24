import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { resetAuthForTests } from "@/lib/auth/session";
import { resetChat, sendChatMessage } from "../transport";

type Call = { method: string; path: string; headers: Record<string, string> };

const err = (status: number, code: string, details: unknown = null) =>
  Response.json({ error: { code, message: code, details, request_id: "r" } }, { status });

function route(handlers: Record<string, () => Response>, calls: Call[]) {
  vi.stubGlobal("fetch", async (url: string, init: RequestInit) => {
    const path = new URL(String(url)).pathname.replace("/api/v1", "").replace(/[0-9a-f-]{36}|conv-\d/, ":id");
    calls.push({ method: String(init.method), path, headers: init.headers as Record<string, string> });
    const h = handlers[`${init.method} ${path}`];
    if (!h) throw new Error(`route non prévue : ${init.method} ${path}`);
    return h();
  });
}

beforeEach(() => {
  resetAuthForTests();
  resetChat();
});
afterEach(() => vi.unstubAllGlobals());

const MSG = (role: string, text: string) => ({ id: `${role}-1`, role, text, citations: [] });

describe("transport du chat (API réelle)", () => {
  it("visiteur : session, conversation, puis message ; réutilise la conversation", async () => {
    const calls: Call[] = [];
    route(
      {
        "POST /visitor-sessions": () => Response.json({ id: "vs" }, { status: 201 }),
        "POST /conversations": () => Response.json({ id: "conv-1" }, { status: 201 }),
        "POST /conversations/:id/messages": () =>
          Response.json({
            user_message: MSG("user", "Bonjour"),
            assistant_message: MSG("assistant", "Salut !"),
            quota: { messages_used: 1, messages_limit: 30, resets_at: "x" },
          }),
      },
      calls,
    );
    const state = await sendChatMessage("Bonjour");
    expect(state.status).toBe("completed");
    expect(state.text).toBe("Salut !");
    expect(state.quota?.messages_used).toBe(1);
    await sendChatMessage("Encore");
    expect(calls.map((c) => `${c.method} ${c.path}`)).toEqual([
      "POST /visitor-sessions",
      "POST /conversations",
      "POST /conversations/:id/messages",
      "POST /conversations/:id/messages",
    ]);
    expect(calls[0].headers["X-Dev-User-Id"]).toBeUndefined();
  });

  it("LLM indisponible : secours déterministe affiché", async () => {
    const fallback = { text: "Secours", links: [], suggested_actions: [{ type: "create_account", label: "Créer", requires_confirmation: true, payload: {} }] };
    route(
      {
        "POST /visitor-sessions": () => Response.json({ id: "vs" }, { status: 201 }),
        "POST /conversations": () => Response.json({ id: "conv-1" }, { status: 201 }),
        "POST /conversations/:id/messages": () => err(503, "LLM_UNAVAILABLE", { retry_after_s: 30, fallback }),
        "GET /visitor-sessions/current": () =>
          Response.json({ id: "vs", quota: { messages_used: 1, messages_limit: 30, resets_at: "x" } }),
      },
      [],
    );
    const state = await sendChatMessage("Bonjour");
    expect(state.status).toBe("fallback");
    expect(state.fallback?.text).toBe("Secours");
    expect(state.quota?.messages_used).toBe(1);
  });

  it("session expirée : nouvelle session et un seul nouvel essai", async () => {
    const calls: Call[] = [];
    let first = true;
    route(
      {
        "POST /visitor-sessions": () => Response.json({ id: "vs" }, { status: 201 }),
        "POST /conversations": () => Response.json({ id: "conv-1" }, { status: 201 }),
        "POST /conversations/:id/messages": () => {
          if (first) {
            first = false;
            return err(410, "SESSION_EXPIRED");
          }
          return Response.json({ user_message: MSG("user", "x"), assistant_message: MSG("assistant", "ok"), quota: null });
        },
      },
      calls,
    );
    const state = await sendChatMessage("x");
    expect(state.status).toBe("completed");
    expect(calls.filter((c) => c.path === "/visitor-sessions")).toHaveLength(2);
  });

  it("quota atteint : erreur remontée (pas de nouvel essai)", async () => {
    route(
      {
        "POST /visitor-sessions": () => Response.json({ id: "vs" }, { status: 201 }),
        "POST /conversations": () => Response.json({ id: "conv-1" }, { status: 201 }),
        "POST /conversations/:id/messages": () => err(429, "VISITOR_QUOTA_EXCEEDED", { limit: 30 }),
      },
      [],
    );
    await expect(sendChatMessage("x")).rejects.toMatchObject({ code: "VISITOR_QUOTA_EXCEEDED" });
  });
});
