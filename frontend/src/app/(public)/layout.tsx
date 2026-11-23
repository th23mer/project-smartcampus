import Link from "next/link";
import type { ReactNode } from "react";
import { BackendStatus } from "@/components/app/backend-status";
import { AccountMenu } from "@/components/auth/account-menu";

/** Mise en page publique (visiteur) : en-tête léger, pied de page. */
export default function PublicLayout({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col bg-gradient-to-b from-sky-50 to-background dark:from-sky-950/30">
      <header className="mx-auto flex w-full max-w-6xl items-center justify-between gap-4 px-6 py-4">
        <Link href="/" className="flex items-center gap-2 font-semibold">
          <span className="size-2.5 rounded-full bg-emerald-600" aria-hidden />
          SmartCampus AI
        </Link>
        <nav className="flex items-center gap-4 text-sm">
          <BackendStatus className="hidden sm:inline-flex" />
          <Link href="/candidat" className="text-muted-foreground hover:text-foreground">
            Espace candidat
          </Link>
          <AccountMenu />
        </nav>
      </header>
      <main className="mx-auto w-full max-w-6xl flex-1 px-6 pb-10">{children}</main>
      <footer className="border-t py-4 text-center text-xs text-muted-foreground">
        Projet pédagogique IIT Sfax 2026-2027 · données fictives · les décisions officielles sont prises par un humain.
      </footer>
    </div>
  );
}
