import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api/client";
import { getAccessToken, setAccessToken } from "../token";
import {
  answerAttachOffer,
  getAuthState,
  homeFor,
  login,
  logout,
  resetAuthForTests,
  restoreSession,
} from "../session";
import { safeNext } from "@/components/auth/auth-forms";

type Call = { url: string; init: RequestInit };

const USER = {
  id: "u1",
  account_type: "candidate",
  email: "c@example.com",
  full_name: "Candidat Fictif",
  account_status: "pending_verification",
  roles: ["candidate"],
  candidate_id: null,
  created_at: "2026-11-23T10:00:00Z",
};
const OFFER = { visitor_session_id: "vs1", conversation_count: 1, message_count: 2, offer_expires_at: "x" };

function route(handlers: Record<string, (init: RequestInit) => Response>, calls: Call[]) {
  vi.stubGlobal("fetch", async (url: string, init: RequestInit) => {
    calls.push({ url: String(url), init });
    const path = new URL(String(url)).pathname.replace("/api/v1", "");
    const h = handlers[`${init.method} ${path}`];
    if (!h) throw new Error(`route non prévue : ${init.method} ${path}`);
    return h(init);
  });
}

const err = (status: number, code: string) =>
  Response.json({ error: { code, message: code, details: null, request_id: "r" } }, { status });

beforeEach(() => resetAuthForTests());
afterEach(() => vi.unstubAllGlobals());

describe("session d'authentification", () => {
  it("connexion : jeton en mémoire, utilisateur et offre de rattachement", async () => {
    const calls: Call[] = [];
    route({ "POST /auth/login": () => Response.json({ access_token: "A1", token_type: "Bearer", expires_in: 900, user: USER, attach_offer: OFFER }) }, calls);
    await login("c@example.com", "MotDePasse-2026");
    expect(getAccessToken()).toBe("A1");
    expect(getAuthState()).toMatchObject({ status: "authenticated", attachOffer: OFFER });
    expect(calls[0].init.credentials).toBe("include");
  });

  it("restoreSession : cookie de renouvellement absent → anonyme", async () => {
    route({ "POST /auth/refresh": () => err(401, "UNAUTHENTICATED") }, []);
    await restoreSession();
    expect(getAuthState().status).toBe("anonymous");
  });

  it("restoreSession : refresh puis /auth/me", async () => {
    route(
      {
        "POST /auth/refresh": () => Response.json({ access_token: "R1", token_type: "Bearer", expires_in: 900 }),
        "GET /auth/me": (init) => {
          expect((init.headers as Record<string, string>).Authorization).toBe("Bearer R1");
          return Response.json(USER);
        },
      },
      [],
    );
    await restoreSession();
    expect(getAuthState()).toMatchObject({ status: "authenticated", user: { email: "c@example.com" } });
  });

  it("un 401 renouvelle le jeton une fois puis rejoue la requête", async () => {
    setAccessToken("expire");
    let n = 0;
    route(
      {
        "GET /conversations": (init) => {
          n++;
          const auth = (init.headers as Record<string, string>).Authorization;
          return auth === "Bearer neuf" ? Response.json({ items: [] }) : err(401, "UNAUTHENTICATED");
        },
        "POST /auth/refresh": () => Response.json({ access_token: "neuf", token_type: "Bearer", expires_in: 900 }),
      },
      [],
    );
    await expect(api.get("/conversations")).resolves.toEqual({ items: [] });
    expect(n).toBe(2);
  });

  it("rattachement : consentement explicite envoyé avec une clé d'idempotence", async () => {
    const calls: Call[] = [];
    route(
      {
        "POST /auth/login": () => Response.json({ access_token: "A1", token_type: "Bearer", expires_in: 900, user: USER, attach_offer: OFFER }),
        "POST /auth/attach-visitor-session": () =>
          Response.json({ attachment_status: "attached", visitor_session_status: "attached", conversation_ids: ["c1"] }),
      },
      calls,
    );
    await login("c@example.com", "MotDePasse-2026");
    const res = await answerAttachOffer(true);
    expect(res.attachment_status).toBe("attached");
    expect(JSON.parse(String(calls[1].init.body))).toEqual({ visitor_session_id: "vs1", consent: true });
    expect((calls[1].init.headers as Record<string, string>)["Idempotency-Key"]).toMatch(/^[0-9a-f-]{36}$/);
    expect(getAuthState().attachOffer).toBeNull();
  });

  it("déconnexion locale même si le serveur échoue", async () => {
    setAccessToken("A1");
    route({ "POST /auth/logout": () => err(500, "INTERNAL_ERROR") }, []);
    await logout();
    expect(getAccessToken()).toBeNull();
    expect(getAuthState().status).toBe("anonymous");
  });

  it("redirections : espace selon le rôle, `next` interne seulement", () => {
    expect(homeFor(USER as never)).toBe("/candidat");
    expect(homeFor({ ...USER, roles: ["direction"] } as never)).toBe("/staff");
    expect(safeNext("/staff/catalogue")).toBe("/staff/catalogue");
    expect(safeNext("//evil.example")).toBeNull();
    expect(safeNext("https://evil.example")).toBeNull();
  });
});
