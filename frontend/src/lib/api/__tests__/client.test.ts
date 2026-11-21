import { describe, expect, it } from "vitest";
import { buildUrl, createApiClient } from "../client";
import { DEV_IDENTITIES, devAuthHeaders } from "../dev-identity";
import { ApiError } from "../errors";

type Call = { url: string; init: RequestInit };

function fakeFetch(response: () => Response | Promise<Response>, calls: Call[] = []): typeof fetch {
  return async (url, init) => {
    calls.push({ url: String(url), init: init ?? {} });
    return response();
  };
}

describe("buildUrl", () => {
  it("préfixe /api/v1 et répète les paramètres multiples", () => {
    expect(buildUrl("http://h", "/preregistrations", { status: ["submitted", "under_review"], page: 2, x: undefined })).toBe(
      "http://h/api/v1/preregistrations?status=submitted&status=under_review&page=2",
    );
  });
});

describe("createApiClient", () => {
  it("getHealth renvoie le corps typé", async () => {
    const calls: Call[] = [];
    const client = createApiClient({
      baseUrl: "http://h/",
      devAuth: false,
      fetchImpl: fakeFetch(() => Response.json({ status: "ok", version: "0.1.0", time: "2026-11-16T10:15:00Z" }), calls),
    });
    await expect(client.getHealth()).resolves.toEqual({ status: "ok", version: "0.1.0", time: "2026-11-16T10:15:00Z" });
    expect(calls[0].url).toBe("http://h/api/v1/health");
  });

  it("ajoute les en-têtes X-Dev-* seulement si l'auth de dev est active", async () => {
    const staff = DEV_IDENTITIES.find((d) => d.key === "iit_academic_lead")!;
    const calls: Call[] = [];
    const on = createApiClient({
      baseUrl: "http://h",
      devAuth: true,
      authHeaders: () => devAuthHeaders(staff),
      fetchImpl: fakeFetch(() => Response.json({}), calls),
    });
    const off = createApiClient({
      baseUrl: "http://h",
      devAuth: false,
      authHeaders: () => devAuthHeaders(staff),
      fetchImpl: fakeFetch(() => Response.json({}), calls),
    });
    await on.get("/x");
    await off.get("/x");
    const h0 = calls[0].init.headers as Record<string, string>;
    const h1 = calls[1].init.headers as Record<string, string>;
    expect(h0["X-Dev-User-Id"]).toBe(staff.userId);
    expect(h0["X-Dev-Roles"]).toBe("iit_academic_lead");
    expect(h1["X-Dev-User-Id"]).toBeUndefined();
  });

  it("n'envoie aucun en-tête de dev pour un visiteur", () => {
    expect(devAuthHeaders(DEV_IDENTITIES[0])).toEqual({});
  });

  it("envoie le JSON et la clé d'idempotence", async () => {
    const calls: Call[] = [];
    const client = createApiClient({
      baseUrl: "http://h",
      devAuth: false,
      fetchImpl: fakeFetch(() => new Response(null, { status: 204 }), calls),
    });
    await expect(client.post("/a", { b: 1 }, { idempotencyKey: "k-1" })).resolves.toBeUndefined();
    const h = calls[0].init.headers as Record<string, string>;
    expect(calls[0].init.body).toBe('{"b":1}');
    expect(h["Content-Type"]).toBe("application/json");
    expect(h["Idempotency-Key"]).toBe("k-1");
  });

  it("convertit l'enveloppe d'erreur SA-5 en ApiError", async () => {
    const client = createApiClient({
      baseUrl: "http://h",
      devAuth: false,
      fetchImpl: fakeFetch(
        () =>
          new Response(
            JSON.stringify({
              error: {
                code: "VALIDATION_ERROR",
                message: "Les données envoyées sont invalides.",
                details: [{ field: "consents.data_processing", issue: "required" }],
                request_id: "req_123",
              },
            }),
            { status: 422, headers: { "Content-Type": "application/json", "X-Request-ID": "req_123" } },
          ),
      ),
    });
    const err = await client.get("/a").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    const e = err as ApiError;
    expect(e.code).toBe("VALIDATION_ERROR");
    expect(e.status).toBe(422);
    expect(e.request_id).toBe("req_123");
    expect(e.validationIssues).toEqual([{ field: "consents.data_processing", issue: "required" }]);
  });

  it("signale une réponse non conforme (page HTML d'un proxy)", async () => {
    const client = createApiClient({
      baseUrl: "http://h",
      devAuth: false,
      fetchImpl: fakeFetch(() => new Response("<html>Bad gateway</html>", { status: 502, headers: { "X-Request-ID": "r" } })),
    });
    await expect(client.get("/a")).rejects.toMatchObject({ code: "UNEXPECTED_RESPONSE", status: 502, requestId: "r" });
  });

  it("transforme un backend arrêté en NETWORK_ERROR", async () => {
    const client = createApiClient({
      baseUrl: "http://h",
      devAuth: false,
      fetchImpl: async () => {
        throw new TypeError("fetch failed");
      },
    });
    const err = (await client.getHealth().catch((e: unknown) => e)) as ApiError;
    expect(err.code).toBe("NETWORK_ERROR");
    expect(err.isNetworkError).toBe(true);
    expect(err.status).toBe(0);
  });
});
