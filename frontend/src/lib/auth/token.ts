/**
 * Jeton d'accès en mémoire (SA-5 §1.2 : jamais dans localStorage, illisible après
 * fermeture de l'onglet). Le cookie httpOnly `sc_refresh` permet de le renouveler.
 *
 * Module sans dépendance : le client API le lit, la session (`session.ts`) l'écrit et
 * branche le renouvellement automatique (`setRefreshHandler`).
 */

let accessToken: string | null = null;
let refreshHandler: (() => Promise<boolean>) | null = null;

export function getAccessToken(): string | null {
  return accessToken;
}

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

/** Fonction appelée par le client API quand le jeton est refusé (401) : vrai si renouvelé. */
export function setRefreshHandler(handler: (() => Promise<boolean>) | null): void {
  refreshHandler = handler;
}

export function getRefreshHandler(): (() => Promise<boolean>) | null {
  return refreshHandler;
}
