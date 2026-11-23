"use client";

/**
 * Garde d'affichage des espaces candidat et staff. Ce n'est PAS la sécurité : le backend
 * refuse toute requête sans le bon rôle (401 / 403). La garde évite seulement d'afficher un
 * espace vide à quelqu'un qui n'est pas connecté.
 *
 * Accès : utilisateur connecté avec le bon rôle, ou (en dev) identité simulée du même espace.
 */
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useSyncExternalStore, type ReactNode } from "react";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { isDev } from "@/lib/config";
import { DEFAULT_DEV_IDENTITY, getDevIdentity, subscribeDevIdentity } from "@/lib/api/dev-identity";
import { isStaff } from "@/lib/auth/session";
import { useAuth } from "@/lib/auth/use-auth";

export function RequireRole({ space, children }: { space: "candidate" | "staff"; children: ReactNode }) {
  const { status, user } = useAuth();
  const pathname = usePathname();
  const devIdentity = useSyncExternalStore(subscribeDevIdentity, getDevIdentity, () => DEFAULT_DEV_IDENTITY);

  const label = space === "staff" ? "la console staff" : "l'espace candidat";
  if (status === "authenticated" && user) {
    const ok = space === "staff" ? isStaff(user) : user.roles.includes("candidate");
    if (ok) return <>{children}</>;
    return (
      <Gate
        title="Accès réservé"
        text={`Ton compte n'a pas accès à ${label}.`}
        action={<Link href={isStaff(user) ? "/staff" : "/candidat"}>Aller à mon espace</Link>}
      />
    );
  }
  if (isDev && devIdentity.space === space) return <>{children}</>;
  if (status === "unknown") {
    return (
      <div className="flex justify-center py-16 text-muted-foreground">
        <Loader2 className="animate-spin" aria-label="Chargement" />
      </div>
    );
  }
  return (
    <Gate
      title="Connexion requise"
      text={`Connecte-toi pour accéder à ${label}.`}
      action={<Link href={`/connexion?next=${encodeURIComponent(pathname)}`}>Se connecter</Link>}
    />
  );
}

function Gate({ title, text, action }: { title: string; text: string; action: ReactNode }) {
  return (
    <Card className="mx-auto mt-10 max-w-md">
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>{text}</CardDescription>
        <Button asChild className="mt-3 w-fit">
          {action}
        </Button>
      </CardHeader>
    </Card>
  );
}
