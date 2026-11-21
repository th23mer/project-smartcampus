"use client";

/**
 * Sélecteur de rôle de dev : visible uniquement si `NEXT_PUBLIC_APP_ENV=dev`.
 * Il choisit l'identité simulée (en-têtes X-Dev-*) et ouvre l'espace correspondant.
 * Ce n'est PAS un contrôle d'accès : les droits sont vérifiés par le backend.
 */
import { useEffect, useSyncExternalStore } from "react";
import { useRouter } from "next/navigation";
import { isDev } from "@/lib/config";
import {
  DEFAULT_DEV_IDENTITY,
  DEV_IDENTITIES,
  getDevIdentity,
  loadDevIdentity,
  setDevIdentity,
  subscribeDevIdentity,
} from "@/lib/api/dev-identity";

const SPACE_HOME = { visitor: "/", candidate: "/candidat", staff: "/staff" } as const;

export function DevRoleSwitcher() {
  const router = useRouter();
  const identity = useSyncExternalStore(subscribeDevIdentity, getDevIdentity, () => DEFAULT_DEV_IDENTITY);

  useEffect(() => {
    loadDevIdentity();
  }, []);

  if (!isDev) return null;

  return (
    <div className="fixed bottom-3 end-3 z-50 flex items-center gap-2 rounded-lg border border-dashed border-amber-500 bg-amber-50 px-3 py-2 text-xs text-amber-900 shadow-sm dark:bg-amber-950 dark:text-amber-100">
      <label htmlFor="dev-role" className="font-semibold">
        Rôle de dev
      </label>
      <select
        id="dev-role"
        value={identity.key}
        onChange={(e) => {
          setDevIdentity(e.target.value);
          const next = DEV_IDENTITIES.find((d) => d.key === e.target.value);
          if (next) router.push(SPACE_HOME[next.space]);
        }}
        className="rounded border border-amber-400 bg-white px-1.5 py-0.5 text-xs text-foreground dark:bg-amber-900"
      >
        <optgroup label="Public">
          {DEV_IDENTITIES.filter((d) => d.space !== "staff").map((d) => (
            <option key={d.key} value={d.key}>
              {d.label}
            </option>
          ))}
        </optgroup>
        <optgroup label="Staff (sous-rôles)">
          {DEV_IDENTITIES.filter((d) => d.space === "staff").map((d) => (
            <option key={d.key} value={d.key}>
              {d.label}
            </option>
          ))}
        </optgroup>
      </select>
    </div>
  );
}
