/**
 * Session de l'utilisateur connecté (E3 : SA-28, SA-29), côté navigateur.
 *
 * - connexion / inscription : `POST /auth/login|register` → jeton d'accès gardé **en mémoire**
 *   (`token.ts`) + cookie httpOnly `sc_refresh` posé par le serveur ;
 * - au chargement de la page : `restoreSession()` tente `POST /auth/refresh` (le cookie suffit),
 *   puis relit `GET /auth/me` ;
 * - un 401 sur une route protégée déclenche un renouvellement (une seule requête à la fois) ;
 * - `attach_offer` (SA-29) est conservée jusqu'à la réponse du candidat
 *   (`answerAttachOffer`, consentement explicite) ;
 * - les rôles affichés ne sont **pas** un contrôle d'accès : le backend vérifie tout.
 */
import { api } from "@/lib/api/client";
import type {
  AttachOffer,
  AttachResponse,
  AuthResponse,
  AuthUser,
  RegisterRequest,
  TokenResponse,
} from "@/lib/api/auth-types";
import { setAccessToken, setRefreshHandler } from "./token";

export type AuthStatus = "unknown" | "anonymous" | "authenticated";

export interface AuthState {
  status: AuthStatus;
  user: AuthUser | null;
  /** Proposition de garder la conversation visiteur, en attente de réponse. */
  attachOffer: AttachOffer | null;
}

const INITIAL: AuthState = { status: "unknown", user: null, attachOffer: null };

let state: AuthState = INITIAL;
const listeners = new Set<() => void>();

function setState(next: Partial<AuthState>): void {
  state = { ...state, ...next };
  listeners.forEach((l) => l());
}

export function getAuthState(): AuthState {
  return state;
}

/** État côté serveur (rendu initial) : inconnu. */
export function getServerAuthState(): AuthState {
  return INITIAL;
}

export function subscribeAuth(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function applyAuthResponse(res: AuthResponse): AuthResponse {
  setAccessToken(res.access_token);
  setState({ status: "authenticated", user: res.user, attachOffer: res.attach_offer });
  return res;
}

export async function login(email: string, password: string): Promise<AuthResponse> {
  const res = await api.post<AuthResponse>("/auth/login", { email, password }, { noRefresh: true });
  return applyAuthResponse(res);
}

export async function register(body: RegisterRequest): Promise<AuthResponse> {
  const res = await api.post<AuthResponse>("/auth/register", body, { noRefresh: true });
  return applyAuthResponse(res);
}

let refreshing: Promise<boolean> | null = null;

/** Renouvelle le jeton grâce au cookie `sc_refresh` ; une seule requête à la fois. */
export function refreshAccessToken(): Promise<boolean> {
  refreshing ??= (async () => {
    try {
      const res = await api.post<TokenResponse>("/auth/refresh", undefined, { noRefresh: true });
      setAccessToken(res.access_token);
      return true;
    } catch {
      setAccessToken(null);
      setState({ status: "anonymous", user: null, attachOffer: null });
      return false;
    } finally {
      refreshing = null;
    }
  })();
  return refreshing;
}

setRefreshHandler(refreshAccessToken);

let restoring: Promise<void> | null = null;

/** Au chargement : retrouve la session si le cookie de renouvellement est encore valide. */
export function restoreSession(): Promise<void> {
  if (state.status !== "unknown") return Promise.resolve();
  restoring ??= (async () => {
    if (!(await refreshAccessToken())) return;
    try {
      const user = await api.get<AuthUser>("/auth/me", { noRefresh: true });
      setState({ status: "authenticated", user });
    } catch {
      setAccessToken(null);
      setState({ status: "anonymous", user: null });
    }
  })().finally(() => {
    restoring = null;
  });
  return restoring;
}

export async function logout(): Promise<void> {
  try {
    await api.post<void>("/auth/logout", undefined, { noRefresh: true });
  } catch {
    // Jeton déjà expiré ou serveur injoignable : on se déconnecte quand même localement.
  }
  setAccessToken(null);
  setState({ status: "anonymous", user: null, attachOffer: null });
}

/** Réponse du candidat à l'offre de rattachement (consentement explicite, SA-29). */
export async function answerAttachOffer(consent: boolean): Promise<AttachResponse> {
  const offer = state.attachOffer;
  if (!offer) throw new Error("Aucune proposition de rattachement en attente.");
  const res = await api.post<AttachResponse>(
    "/auth/attach-visitor-session",
    { visitor_session_id: offer.visitor_session_id, consent },
    { idempotencyKey: newUuid() },
  );
  setState({ attachOffer: null });
  return res;
}

/** Ferme la proposition sans répondre (elle expire côté serveur). */
export function dismissAttachOffer(): void {
  setState({ attachOffer: null });
}

export function isStaff(user: AuthUser | null): boolean {
  return !!user && user.roles.some((r) => r !== "candidate");
}

/** Page d'accueil de l'utilisateur après connexion. */
export function homeFor(user: AuthUser): string {
  return isStaff(user) ? "/staff" : "/candidat";
}

export function newUuid(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : "10000000-1000-4000-8000-100000000000".replace(/[018]/g, (c) =>
        (Number(c) ^ (Math.random() * 16) >> (Number(c) / 4)).toString(16),
      );
}

/** Tests uniquement : remet l'état à zéro. */
export function resetAuthForTests(): void {
  setAccessToken(null);
  state = INITIAL;
  refreshing = null;
  restoring = null;
}
