/**
 * Configuration publique du frontend (variables `NEXT_PUBLIC_*`, lues au build).
 * Aucun secret ici : tout ce qui est `NEXT_PUBLIC_*` est visible dans le navigateur.
 */

export type AppEnv = "dev" | "test" | "staging" | "prod";

function readAppEnv(value: string | undefined): AppEnv {
  if (value === "dev" || value === "test" || value === "staging" || value === "prod") {
    return value;
  }
  // Par prudence, une valeur absente ou inconnue désactive les outils de dev.
  return "prod";
}

export const config = {
  apiBaseUrl: (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000").replace(/\/+$/, ""),
  appEnv: readAppEnv(process.env.NEXT_PUBLIC_APP_ENV),
} as const;

/** Vrai seulement en dev : sélecteur de rôle et en-têtes X-Dev-* actifs. */
export const isDev = config.appEnv === "dev";
