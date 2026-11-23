"use client";

/**
 * Monté une fois à la racine : retrouve la session au chargement (cookie `sc_refresh`)
 * et affiche la proposition de rattachement de la conversation visiteur (SA-29).
 */
import { useEffect } from "react";
import { restoreSession } from "@/lib/auth/session";
import { AttachOfferDialog } from "./attach-offer-dialog";

export function AuthBootstrap() {
  useEffect(() => {
    void restoreSession();
  }, []);
  return <AttachOfferDialog />;
}
