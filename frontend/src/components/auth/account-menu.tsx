"use client";

/** En-tête : « Se connecter » pour un anonyme, nom + déconnexion pour un utilisateur connecté. */
import Link from "next/link";
import { useRouter } from "next/navigation";
import { LogIn, LogOut } from "lucide-react";
import { Button } from "@/components/ui/button";
import { logout } from "@/lib/auth/session";
import { useAuth } from "@/lib/auth/use-auth";
import { resetChat } from "@/lib/chat/transport";

export function AccountMenu() {
  const { status, user } = useAuth();
  const router = useRouter();

  if (status === "unknown") return null;
  if (status !== "authenticated" || !user) {
    return (
      <Button asChild size="sm" variant="outline">
        <Link href="/connexion">
          <LogIn /> Se connecter
        </Link>
      </Button>
    );
  }
  return (
    <div className="flex items-center gap-2 text-sm">
      <span className="hidden max-w-48 truncate text-muted-foreground sm:inline" title={user.email}>
        {user.full_name}
      </span>
      <Button
        size="sm"
        variant="ghost"
        onClick={async () => {
          await logout();
          resetChat();
          router.push("/");
        }}
      >
        <LogOut /> Se déconnecter
      </Button>
    </div>
  );
}
