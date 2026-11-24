/**
 * Identité simulée de dev (auth factice de la vague 2).
 *
 * Le backend (SA-7) accepte les en-têtes `X-Dev-User-Id` et `X-Dev-Roles`
 * seulement si `APP_ENV=dev|test`. Le front ne les envoie que si
 * `NEXT_PUBLIC_APP_ENV=dev`. Un utilisateur réellement connecté (jeton Bearer, E3) passe
 * avant : le client n'envoie alors plus ces en-têtes.
 */
import type { DevRole, StaffRole } from "./types";

export interface DevIdentity {
  /** Clé stable du profil de dev (sélecteur). */
  key: string;
  label: string;
  /** `null` pour un visiteur : aucun en-tête envoyé. */
  userId: string | null;
  roles: DevRole[];
  space: "visitor" | "candidate" | "staff";
}

/** Profils fictifs (UUID synthétiques, aucune donnée réelle). */
export const DEV_IDENTITIES: readonly DevIdentity[] = [
  { key: "visitor", label: "Visiteur (sans compte)", userId: null, roles: [], space: "visitor" },
  {
    key: "candidate",
    label: "Candidat",
    userId: "00000000-0000-4000-8000-000000000001",
    roles: ["candidate"],
    space: "candidate",
  },
  ...(
    [
      ["iit_academic_lead", "Staff · responsable IIT"],
      ["isb_academic_lead", "Staff · responsable ISB"],
      ["interview_lead", "Staff · responsable entretiens"],
      ["direction", "Staff · direction"],
      ["platform_admin", "Staff · administrateur"],
    ] as const
  ).map(
    ([role, label], i): DevIdentity => ({
      key: role,
      label,
      userId: `00000000-0000-4000-8000-0000000001${String(i).padStart(2, "0")}`,
      roles: [role as StaffRole],
      space: "staff",
    }),
  ),
];

export const DEFAULT_DEV_IDENTITY: DevIdentity = DEV_IDENTITIES[0];

const STORAGE_KEY = "sc_dev_identity";

let current: DevIdentity = DEFAULT_DEV_IDENTITY;
const listeners = new Set<() => void>();

export function getDevIdentity(): DevIdentity {
  return current;
}

export function setDevIdentity(key: string): void {
  const next = DEV_IDENTITIES.find((d) => d.key === key) ?? DEFAULT_DEV_IDENTITY;
  current = next;
  try {
    window.localStorage.setItem(STORAGE_KEY, next.key);
  } catch {
    // Stockage indisponible (navigation privée) : on garde l'état en mémoire.
  }
  listeners.forEach((l) => l());
}

/** Relit le choix mémorisé, ou le paramètre d'URL `?dev_role=` (captures, démos). */
export function loadDevIdentity(): void {
  try {
    const fromUrl = new URLSearchParams(window.location.search).get("dev_role");
    if (fromUrl && DEV_IDENTITIES.some((d) => d.key === fromUrl)) {
      setDevIdentity(fromUrl);
      return;
    }
    const saved = window.localStorage.getItem(STORAGE_KEY);
    if (saved && saved !== current.key) {
      current = DEV_IDENTITIES.find((d) => d.key === saved) ?? DEFAULT_DEV_IDENTITY;
      listeners.forEach((l) => l());
    }
  } catch {
    // Ignoré.
  }
}

export function subscribeDevIdentity(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** En-têtes d'auth simulée ; vide pour un visiteur. Rôles séparés par des virgules. */
export function devAuthHeaders(identity: DevIdentity = current): Record<string, string> {
  if (!identity.userId) return {};
  return {
    "X-Dev-User-Id": identity.userId,
    "X-Dev-Roles": identity.roles.join(","),
  };
}
