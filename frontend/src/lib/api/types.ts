/**
 * Types de l'API SmartCampus AI, écrits à la main d'après le contrat SA-5.
 * À remplacer plus tard par des types générés depuis `/api/v1/openapi.json`.
 */

/** Réponse de `GET /api/v1/health` (schéma `Health`). */
export interface Health {
  status: "ok" | "degraded";
  version?: string;
  time?: string;
}

/** Détail d'une erreur de validation : `[{"field": "...", "issue": "..."}]`. */
export interface ValidationIssue {
  field: string;
  issue: string;
}

/** Corps interne de l'enveloppe d'erreur unique (SA-5 §1.4). */
export interface ApiErrorBody {
  code: string;
  message: string;
  details: Record<string, unknown> | ValidationIssue[] | null;
  request_id: string | null;
}

/** Enveloppe d'erreur unique : `{"error": {...}}`. */
export interface ApiErrorEnvelope {
  error: ApiErrorBody;
}

/** Métadonnées de pagination par page (SA-5 §1.5). */
export interface PageMeta {
  page: number;
  page_size: number;
  total_items: number;
  total_pages: number;
}

/** Liste paginée par page. */
export interface Paginated<T> {
  items: T[];
  meta: PageMeta;
}

/** Métadonnées de pagination par curseur (messages de chat). */
export interface CursorMeta {
  limit: number;
  next_cursor: string | null;
}

/** Liste paginée par curseur. */
export interface CursorPaginated<T> {
  items: T[];
  meta: CursorMeta;
}

/** Codes de langue (SA-5 §1.1, décision C2). */
export type LanguageCode =
  | "fr"
  | "aeb_arab"
  | "aeb_latn"
  | "ar"
  | "en"
  | "mixed"
  | "unknown";

/** Sous-rôles staff (SA-3, enum `staff_role`). */
export type StaffRole =
  | "iit_academic_lead"
  | "isb_academic_lead"
  | "interview_lead"
  | "direction"
  | "platform_admin";

/** Rôles transmis par l'auth simulée de dev. */
export type DevRole = "candidate" | StaffRole;
