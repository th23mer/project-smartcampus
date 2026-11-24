/**
 * Client API typé (fetch) pour `/api/v1`.
 * - base URL : `NEXT_PUBLIC_API_BASE_URL` ;
 * - authentification (E3) : `Authorization: Bearer <jeton>` si l'utilisateur est connecté ;
 *   un 401 déclenche **un** renouvellement (`/auth/refresh`) puis un nouvel essai ;
 * - sinon, en-têtes d'auth simulée X-Dev-* si `NEXT_PUBLIC_APP_ENV=dev` ;
 * - les cookies (`sc_visitor`, `sc_refresh`, httpOnly) suivent les appels (`credentials`) ;
 * - toute erreur est levée sous forme d'`ApiError` (format SA-5 §1.4).
 */
import { config } from "@/lib/config";
import { getAccessToken, getRefreshHandler } from "@/lib/auth/token";
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
  /** N'envoie pas les en-têtes X-Dev-* (chat : le visiteur reste un visiteur). */
  skipDevAuth?: boolean;
  /** Pas de renouvellement automatique sur 401 (routes `/auth/*`). */
  noRefresh?: boolean;
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

  /** En-têtes communs : jeton Bearer si connecté, sinon auth simulée (dev), + extras. */
  function headers(extra?: Record<string, string>, skipDevAuth = false): Record<string, string> {
    const token = getAccessToken();
    const auth = token
      ? { Authorization: `Bearer ${token}` }
      : devAuth && !skipDevAuth
        ? authHeaders()
        : {};
    return { ...auth, ...extra };
  }

  /** Envoie une requête brute ; lève ApiError en cas d'échec réseau ou HTTP. */
  async function raw(path: string, opts: RequestOptions = {}): Promise<Response> {
    const sentToken = getAccessToken();
    const response = await send(path, opts);
    if (response.status === 401 && sentToken && !opts.noRefresh) {
      // Jeton expiré (15 min) : un seul renouvellement, puis un seul nouvel essai.
      const refresh = getRefreshHandler();
      if (refresh && (await refresh())) {
        const retried = await send(path, opts);
        if (!retried.ok) throw await apiErrorFromResponse(retried);
        return retried;
      }
    }
    if (!response.ok) throw await apiErrorFromResponse(response);
    return response;
  }

  async function send(path: string, opts: RequestOptions): Promise<Response> {
    const h: Record<string, string> = headers({ Accept: "application/json", ...opts.headers }, opts.skipDevAuth);
    let body: BodyInit | undefined;
    if (opts.body instanceof FormData) {
      body = opts.body;
    } else if (opts.body !== undefined) {
      body = JSON.stringify(opts.body);
      h["Content-Type"] = "application/json";
    }
    if (opts.idempotencyKey) h["Idempotency-Key"] = opts.idempotencyKey;

    try {
      return await fetchImpl(buildUrl(baseUrl, path, opts.query), {
        method: opts.method ?? "GET",
        headers: h,
        body,
        signal: opts.signal,
        // Les cookies httpOnly (`sc_visitor`, `sc_refresh`) doivent suivre les appels cross-origin.
        credentials: "include",
      });
    } catch (err) {
      throw apiErrorFromException(err);
    }
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
