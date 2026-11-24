"use client";

/**
 * Formulaires de connexion et d'inscription (SA-28).
 * - inscription publique = compte **candidat** ; les comptes staff sont créés par
 *   l'administration (script `create_staff.py`) ;
 * - les deux consentements obligatoires sont des cases **non cochées** par défaut ;
 * - après succès : redirection vers `?next=` (même site) ou vers l'espace de l'utilisateur ;
 *   l'offre de rattachement (SA-29) s'affiche par-dessus si elle existe.
 */
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent, type ReactNode } from "react";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { PASSWORD_MIN_LENGTH, type AuthResponse } from "@/lib/api/auth-types";
import { ApiError, userMessage } from "@/lib/api/errors";
import { homeFor, login, register } from "@/lib/auth/session";
import { resetChat } from "@/lib/chat/transport";

/** Cible de redirection sûre : chemin interne seulement (pas de `//autre-site`). */
export function safeNext(raw: string | null): string | null {
  return raw && raw.startsWith("/") && !raw.startsWith("//") ? raw : null;
}

function useAfterAuth() {
  const router = useRouter();
  return (res: AuthResponse) => {
    // La conversation visiteur sera rattachée (ou non) par la fenêtre SA-29 ;
    // le chat repart avec l'identité du compte.
    resetChat();
    const next = safeNext(new URLSearchParams(window.location.search).get("next"));
    router.push(next ?? homeFor(res.user));
  };
}

function Field({ id, label, hint, children }: { id: string; label: string; hint?: string; children: ReactNode }) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      {children}
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}

function errorText(err: unknown): string {
  if (err instanceof ApiError) {
    switch (err.code) {
      case "INVALID_CREDENTIALS":
        return "E-mail ou mot de passe incorrect.";
      case "RATE_LIMITED":
        return "Trop de tentatives. Réessaie dans quelques minutes.";
      case "EMAIL_ALREADY_USED":
        return "Un compte existe déjà avec cet e-mail : connecte-toi.";
      case "CONSENT_REQUIRED":
        return "Les deux accords sont nécessaires pour créer un compte.";
      case "VALIDATION_ERROR":
        return "Vérifie les champs : e-mail valide, mot de passe d'au moins 10 caractères.";
    }
  }
  return userMessage(err);
}

export function LoginForm() {
  const afterAuth = useAfterAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      afterAuth(await login(email.trim(), password));
    } catch (err) {
      setError(errorText(err));
      setBusy(false);
    }
  }

  return (
    <Card className="mx-auto w-full max-w-md">
      <CardHeader>
        <CardTitle>Se connecter</CardTitle>
        <CardDescription>Candidat ou membre de l&apos;équipe des admissions.</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={onSubmit} className="space-y-4" noValidate>
          <Field id="email" label="E-mail">
            <Input id="email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </Field>
          <Field id="password" label="Mot de passe">
            <Input
              id="password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </Field>
          {error && (
            <p className="text-sm text-red-700 dark:text-red-400" role="alert">
              {error}
            </p>
          )}
          <Button type="submit" className="w-full" disabled={busy || !email || !password}>
            {busy && <Loader2 className="animate-spin" />} Se connecter
          </Button>
          <p className="text-center text-sm text-muted-foreground">
            Pas encore de compte ?{" "}
            <Link href="/inscription" className="font-medium text-foreground underline-offset-4 hover:underline">
              Créer un compte candidat
            </Link>
          </p>
        </form>
      </CardContent>
    </Card>
  );
}

export function RegisterForm() {
  const afterAuth = useAfterAuth();
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [terms, setTerms] = useState(false);
  const [data, setData] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const tooShort = password.length > 0 && password.length < PASSWORD_MIN_LENGTH;
  const ready = fullName.trim() && email.trim() && password.length >= PASSWORD_MIN_LENGTH && terms && data;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!ready) return;
    setBusy(true);
    setError(null);
    try {
      afterAuth(
        await register({
          email: email.trim(),
          password,
          full_name: fullName.trim(),
          consents: { terms_accepted: terms, data_processing: data },
        }),
      );
    } catch (err) {
      setError(errorText(err));
      setBusy(false);
    }
  }

  return (
    <Card className="mx-auto w-full max-w-md">
      <CardHeader>
        <CardTitle>Créer un compte candidat</CardTitle>
        <CardDescription>Pour retrouver tes conversations et suivre ta pré-inscription.</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={onSubmit} className="space-y-4" noValidate>
          <Field id="full_name" label="Nom complet">
            <Input id="full_name" autoComplete="name" required value={fullName} onChange={(e) => setFullName(e.target.value)} />
          </Field>
          <Field id="email" label="E-mail">
            <Input id="email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </Field>
          <Field id="password" label="Mot de passe" hint={`${PASSWORD_MIN_LENGTH} caractères minimum.`}>
            <Input
              id="password"
              type="password"
              autoComplete="new-password"
              required
              aria-invalid={tooShort || undefined}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </Field>
          <fieldset className="space-y-2 text-sm">
            <legend className="sr-only">Accords obligatoires</legend>
            <label className="flex items-start gap-2">
              <input type="checkbox" className="mt-0.5 size-4" checked={terms} onChange={(e) => setTerms(e.target.checked)} />
              <span>J&apos;accepte les conditions d&apos;utilisation de SmartCampus AI.</span>
            </label>
            <label className="flex items-start gap-2">
              <input type="checkbox" className="mt-0.5 size-4" checked={data} onChange={(e) => setData(e.target.checked)} />
              <span>
                J&apos;accepte le traitement de mes données pour mon orientation et ma pré-inscription (données
                conservées le temps du dossier).
              </span>
            </label>
          </fieldset>
          {error && (
            <p className="text-sm text-red-700 dark:text-red-400" role="alert">
              {error}
            </p>
          )}
          <Button type="submit" className="w-full" disabled={busy || !ready}>
            {busy && <Loader2 className="animate-spin" />} Créer mon compte
          </Button>
          <p className="text-center text-sm text-muted-foreground">
            Déjà un compte ?{" "}
            <Link href="/connexion" className="font-medium text-foreground underline-offset-4 hover:underline">
              Se connecter
            </Link>
          </p>
        </form>
      </CardContent>
    </Card>
  );
}
