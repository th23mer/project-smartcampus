"use client";

/**
 * Navigation propre à chaque espace. Déclarée côté client car les icônes
 * (composants) ne peuvent pas être passées d'un layout serveur à un composant client.
 */
import type { ReactNode } from "react";
import {
  BookOpen,
  CalendarClock,
  ClipboardCheck,
  FileStack,
  FileText,
  LayoutDashboard,
  Radar,
  UserRound,
} from "lucide-react";
import { SpaceShell, type NavItem } from "./space-shell";
import { RequireRole } from "@/components/auth/require-role";

const CANDIDATE_NAV: NavItem[] = [
  { href: "/candidat", label: "Tableau de bord", icon: LayoutDashboard },
  { href: "/candidat/profil", label: "Mon profil", icon: UserRound },
  { href: "/candidat/pre-inscription", label: "Pré-inscription", icon: FileText },
  { href: "/candidat/rendez-vous", label: "Rendez-vous", icon: CalendarClock },
];

const STAFF_NAV: NavItem[] = [
  { href: "/staff", label: "Vue d'ensemble", icon: LayoutDashboard },
  { href: "/staff/catalogue", label: "Catalogue", icon: BookOpen },
  { href: "/staff/validations", label: "Validations en attente", icon: ClipboardCheck },
  { href: "/staff/documents", label: "Documents officiels", icon: FileStack },
  { href: "/staff/lacunes", label: "Radar des lacunes", icon: Radar },
];

export function CandidateShell({ children }: { children: ReactNode }) {
  return (
    <SpaceShell spaceLabel="Espace candidat" accentClass="bg-sky-600" nav={CANDIDATE_NAV}>
      <RequireRole space="candidate">{children}</RequireRole>
    </SpaceShell>
  );
}

export function StaffShell({ children }: { children: ReactNode }) {
  return (
    <SpaceShell spaceLabel="Console staff" accentClass="bg-violet-600" nav={STAFF_NAV}>
      <RequireRole space="staff">{children}</RequireRole>
    </SpaceShell>
  );
}
