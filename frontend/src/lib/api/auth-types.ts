/** Types de l'authentification et du rattachement (SA-5 §5.2, E3 : SA-28, SA-29). */
import type { DevRole } from "./types";

export interface AuthUser {
  id: string;
  account_type: "candidate" | "staff";
  email: string;
  full_name: string;
  account_status: "pending_verification" | "active" | "disabled";
  roles: DevRole[];
  candidate_id: string | null;
  created_at: string;
}

/** Offre de rattachement de la conversation visiteur (SA-29). */
export interface AttachOffer {
  visitor_session_id: string;
  conversation_count: number;
  message_count: number;
  offer_expires_at: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: "Bearer";
  expires_in: number;
}

export interface AuthResponse extends TokenResponse {
  user: AuthUser;
  attach_offer: AttachOffer | null;
}

export interface RegisterRequest {
  email: string;
  password: string;
  full_name: string;
  phone?: string | null;
  consents: { terms_accepted: boolean; data_processing: boolean };
}

export interface AttachResponse {
  attachment_status: "offered" | "consented" | "declined" | "ownership_failed" | "attached" | "expired";
  visitor_session_status: "active" | "attached" | "expired" | "purged" | null;
  conversation_ids: string[];
}

/** Longueur minimale du mot de passe (SA-5 RegisterRequest). */
export const PASSWORD_MIN_LENGTH = 10;
