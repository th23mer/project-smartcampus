"use client";

/**
 * Mise en page commune aux espaces connectés (candidat, staff) :
 * barre latérale de navigation + en-tête. Les classes logiques (start/end,
 * ps/pe, border-e) préparent l'affichage de droite à gauche (RTL).
 */
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { BackendStatus } from "./backend-status";
import { AccountMenu } from "@/components/auth/account-menu";
import { cn } from "@/lib/utils";

export interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
}

export function SpaceShell({
  spaceLabel,
  accentClass,
  nav,
  children,
}: {
  spaceLabel: string;
  /** Couleur de repère de l'espace (classe Tailwind de fond). */
  accentClass: string;
  nav: NavItem[];
  children: ReactNode;
}) {
  const pathname = usePathname();
  return (
    <div className="flex min-h-screen flex-col md:flex-row">
      <aside className="border-b bg-sidebar text-sidebar-foreground md:w-64 md:shrink-0 md:border-e md:border-b-0">
        <div className="flex items-center gap-2 px-5 py-4">
          <span className={cn("size-2.5 rounded-full", accentClass)} aria-hidden />
          <Link href="/" className="font-semibold">
            SmartCampus AI
          </Link>
        </div>
        <p className="px-5 pb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">{spaceLabel}</p>
        <nav className="flex gap-1 overflow-x-auto px-3 pb-3 md:flex-col md:overflow-visible">
          {nav.map((item) => {
            const active = pathname === item.href;
            const Icon = item.icon;
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex shrink-0 items-center gap-2.5 rounded-md px-3 py-2 text-sm transition-colors",
                  active
                    ? "bg-sidebar-accent font-medium text-sidebar-accent-foreground"
                    : "text-muted-foreground hover:bg-sidebar-accent/60 hover:text-foreground",
                )}
              >
                <Icon className="size-4" aria-hidden />
                {item.label}
              </Link>
            );
          })}
        </nav>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-end gap-3 border-b px-6 py-3">
          <BackendStatus />
          <AccountMenu />
        </header>
        <main className="flex-1 px-6 py-6">{children}</main>
      </div>
    </div>
  );
}
