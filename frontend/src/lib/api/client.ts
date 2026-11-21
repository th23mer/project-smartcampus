/**
 * Client API typé (fetch) pour `/api/v1`.
 * - base URL : `NEXT_PUBLIC_API_BASE_URL` ;
 * - en-têtes d'auth simulée X-Dev-* si `NEXT_PUBLIC_APP_ENV=dev` ;
 * - toute erreur est levée sous forme d'`ApiError` (format SA-5 §1.4).
 */
import { config } from "@/lib/config";
import { devAuthHeaders } from "./dev-identity";
import { apiErrorFromException, apiErrorFromResponse, CLIENT_ERROR_CODES, ApiError } from "./errors";
import type { Health } from "./types";

export const API_PREFIX = "/api/v1";

export type QueryValue = string | number | boolean | null | undefined | ReadonlyArray<string | number>;

export interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  query?: Record<string, QueryValue>;
  body?: unknown;
  headers?: Record<string, string>;
  signal?: AbortSignal;
  /** Clé d'idempotence (SA-5 §1.6) pour les créations à effet métier. */
  idempotencyKey?: string;
}

export interface ApiClientOptions {
  baseUrl?: string;
  /** Active les en-têtes X-Dev-*. */
  devAuth?: boolean;
  fetchImpl?: typeof fetch;
  /** Fournit les en-têtes d'auth (par défaut : identité de dev courante). */
  authHeaders?: () => Record<string, string>;
}

/** Construit l'URL complète, avec répétition des paramètres multiples (`?status=a&status=b`). */
export function buildUrl(baseUrl: string, path: string, query?: Record<string, QueryValue>): string {
  const cleanPath = path.startsWith("/") ? path : `/${path}`;
  const url = `${baseUrl}${API_PREFIX}${cleanPath}`;
  if (!query) return url;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null) continue;
    if (Array.isArray(value)) value.forEach((v) => params.append(key, String(v)));
    else params.append(key, String(value));
  }
  const qs = params.toString();
  return qs ? `${url}?${qs}` : url;
}

export function createApiClient(options: ApiClientOptions = {}) {
  const baseUrl = (options.baseUrl ?? config.apiBaseUrl).replace(/\/+$/, "");
  const devAuth = options.devAuth ?? config.appEnv === "dev";
  const fetchImpl = options.fetchImpl ?? ((...args: Parameters<typeof fetch>) => fetch(...args));
  const authHeaders = options.authHeaders ?? (() => devAuthHeaders());

  /** En-têtes communs (auth simulée + extras). */
  function headers(extra?: Record<string, string>): Record<string, string> {
    return { ...(devAuth ? authHeaders() : {}), ...extra };
  }

  /** Envoie une requête brute ; lève ApiError en cas d'échec réseau ou HTTP. */
  async function raw(path: string, opts: RequestOptions = {}): Promise<Response> {
    const h: Record<string, string> = headers({ Accept: "application/json", ...opts.headers });
    let body: BodyInit | undefined;
    if (opts.body instanceof FormData) {
      body = opts.body;
    } else if (opts.body !== undefined) {
      body = JSON.stringify(opts.body);
      h["Content-Type"] = "application/json";
    }
    if (opts.idempotencyKey) h["Idempotency-Key"] = opts.idempotencyKey;

    let response: Response;
    try {
      response = await fetchImpl(buildUrl(baseUrl, path, opts.query), {
        method: opts.method ?? "GET",
        headers: h,
        body,
        signal: opts.signal,
        // Le cookie visiteur `sc_visitor` (httpOnly) doit suivre les appels cross-origin.
        credentials: "include",
      });
    } catch (err) {
      throw apiErrorFromException(err);
    }
    if (!response.ok) throw await apiErrorFromResponse(response);
    return response;
  }

  /** Requête JSON typée. Une réponse 204 renvoie `undefined`. */
  async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
    const response = await raw(path, opts);
    if (response.status === 204) return undefined as T;
    try {
      return (await response.json()) as T;
    } catch {
      throw new ApiError({
        code: CLIENT_ERROR_CODES.UNEXPECTED_RESPONSE,
        message: "Réponse inattendue du serveur.",
        status: response.status,
        requestId: response.headers.get("X-Request-ID"),
      });
    }
  }

  return {
    baseUrl,
    headers,
    raw,
    request,
    get: <T>(path: string, opts?: Omit<RequestOptions, "method" | "body">) =>
      request<T>(path, { ...opts, method: "GET" }),
    post: <T>(path: string, body?: unknown, opts?: Omit<RequestOptions, "method" | "body">) =>
      request<T>(path, { ...opts, method: "POST", body }),
    patch: <T>(path: string, body?: unknown, opts?: Omit<RequestOptions, "method" | "body">) =>
      request<T>(path, { ...opts, method: "PATCH", body }),
    put: <T>(path: string, body?: unknown, opts?: Omit<RequestOptions, "method" | "body">) =>
      request<T>(path, { ...opts, method: "PUT", body }),
    delete: <T>(path: string, opts?: Omit<RequestOptions, "method" | "body">) =>
      request<T>(path, { ...opts, method: "DELETE" }),

    /** `GET /api/v1/health` (public). */
    getHealth: (signal?: AbortSignal) => request<Health>("/health", { signal }),
  };
}

export type ApiClient = ReturnType<typeof createApiClient>;

/** Instance par défaut, configurée par les variables d'environnement. */
export const api = createApiClient();
