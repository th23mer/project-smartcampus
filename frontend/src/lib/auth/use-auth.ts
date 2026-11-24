"use client";

import { useSyncExternalStore } from "react";
import { getAuthState, getServerAuthState, subscribeAuth, type AuthState } from "./session";

/** État de connexion courant (se met à jour à la connexion / déconnexion). */
export function useAuth(): AuthState {
  return useSyncExternalStore(subscribeAuth, getAuthState, getServerAuthState);
}
