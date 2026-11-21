/**
 * Gestion centralisée des erreurs au format unique de SA-5 §1.4.
 * Le front teste toujours `code`, jamais le texte de `message`.
 */
import type { ApiErrorBody, ValidationIssue } from "./types";

/** Codes produits par le client lui-même (pas par le serveur). */
export const CLIENT_ERROR_CODES = {
  /** Backend injoignable (arrêté, réseau coupé, CORS). */
  NETWORK_ERROR: "NETWORK_ERROR",
  /** Réponse non conforme à l'enveloppe (proxy, page HTML…). */
  UNEXPECTED_RESPONSE: "UNEXPECTED_RESPONSE",
  /** Requête annulée par le client. */
  ABORTED: "ABORTED",
} as const;

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly details: ApiErrorBody["details"];
  readonly requestId: string | null;

  constructor(params: {
    code: string;
    message: string;
    status: number;
    details?: ApiErrorBody["details"];
    requestId?: string | null;
  }) {
    super(params.message);
    this.name = "ApiError";
    this.code = params.code;
    this.status = params.status;
    this.details = params.details ?? null;
    this.requestId = params.requestId ?? null;
  }

  /** Alias au nom du contrat SA-5. */
  get request_id(): string | null {
    return this.requestId;
  }

  /** Liste des champs invalides si `details` est une liste de validation. */
  get validationIssues(): ValidationIssue[] {
    return Array.isArray(this.details) ? this.details : [];
  }

  get isNetworkError(): boolean {
    return this.code === CLIENT_ERROR_CODES.NETWORK_ERROR;
  }
}

function isErrorBody(value: unknown): value is ApiErrorBody {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return typeof v.code === "string" && typeof v.message === "string";
}

/** Construit une ApiError depuis un corps JSON déjà lu (HTTP ou événement SSE `error`). */
export function apiErrorFromBody(
  body: unknown,
  status: number,
  fallbackRequestId: string | null = null,
): ApiError {
  const inner = typeof body === "object" && body !== null ? (body as { error?: unknown }).error : undefined;
  if (isErrorBody(inner)) {
    return new ApiError({
      code: inner.code,
      message: inner.message,
      status,
      details: inner.details ?? null,
      requestId: inner.request_id ?? fallbackRequestId,
    });
  }
  return new ApiError({
    code: CLIENT_ERROR_CODES.UNEXPECTED_RESPONSE,
    message: "Réponse inattendue du serveur.",
    status,
    details: null,
    requestId: fallbackRequestId,
  });
}

/** Lit une réponse HTTP en échec et la convertit en ApiError. */
export async function apiErrorFromResponse(response: Response): Promise<ApiError> {
  const requestId = response.headers.get("X-Request-ID");
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  return apiErrorFromBody(body, response.status, requestId);
}

/** Convertit une exception de `fetch` (réseau, annulation) en ApiError. */
export function apiErrorFromException(err: unknown): ApiError {
  if (err instanceof ApiError) return err;
  if (err instanceof DOMException && err.name === "AbortError") {
    return new ApiError({ code: CLIENT_ERROR_CODES.ABORTED, message: "Requête annulée.", status: 0 });
  }
  return new ApiError({
    code: CLIENT_ERROR_CODES.NETWORK_ERROR,
    message: "Le serveur est injoignable. Vérifiez votre connexion ou réessayez plus tard.",
    status: 0,
  });
}

/** Message lisible pour l'utilisateur, en français. */
export function userMessage(err: unknown): string {
  if (err instanceof ApiError) {
    return err.requestId ? `${err.message} (référence : ${err.requestId})` : err.message;
  }
  return "Une erreur inattendue s'est produite.";
}
