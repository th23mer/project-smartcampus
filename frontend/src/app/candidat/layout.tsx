import type { Metadata } from "next";
import type { ReactNode } from "react";
import { CandidateShell } from "@/components/app/space-shells";

export const metadata: Metadata = { title: { default: "Espace candidat", template: "%s · Espace candidat" } };

export default function CandidateLayout({ children }: { children: ReactNode }) {
  return <CandidateShell>{children}</CandidateShell>;
}
