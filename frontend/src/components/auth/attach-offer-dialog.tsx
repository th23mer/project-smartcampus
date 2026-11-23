"use client";

/**
 * SA-29 : après connexion ou inscription, si le navigateur portait une conversation
 * visiteur, on demande au candidat s'il veut la garder dans son compte.
 * Le consentement est **explicite** (deux boutons, aucune case précochée) ; le serveur
 * vérifie en plus que la session appartient bien à ce navigateur (cookie).
 */
import { useState } from "react";
import { Loader2, MessagesSquare } from "lucide-react";
import { Button } from "@/components/ui/button";
import { userMessage } from "@/lib/api/errors";
import { answerAttachOffer, dismissAttachOffer } from "@/lib/auth/session";
import { useAuth } from "@/lib/auth/use-auth";

export function AttachOfferDialog() {
  const { attachOffer } = useAuth();
  const [busy, setBusy] = useState<"yes" | "no" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  if (!attachOffer && !done) return null;

  async function answer(consent: boolean) {
    setBusy(consent ? "yes" : "no");
    setError(null);
    try {
      const res = await answerAttachOffer(consent);
      setDone(
        res.attachment_status === "attached"
          ? "Ta conversation est enregistrée dans ton compte."
          : "D'accord : ta conversation n'a pas été ajoutée à ton compte.",
      );
    } catch (err) {
      setError(userMessage(err));
    } finally {
      setBusy(null);
    }
  }

  if (done) {
    return (
      <div
        role="status"
        className="fixed bottom-16 start-1/2 z-50 flex -translate-x-1/2 items-center gap-3 rounded-lg border bg-card px-4 py-2.5 text-sm shadow-lg rtl:translate-x-1/2"
      >
        <span>{done}</span>
        <Button size="sm" variant="ghost" className="h-7" onClick={() => setDone(null)}>
          OK
        </Button>
      </div>
    );
  }

  const n = attachOffer!.message_count;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="attach-title"
        aria-describedby="attach-desc"
        className="w-full max-w-md space-y-4 rounded-xl border bg-card p-6 shadow-xl"
      >
        <div className="flex items-start gap-3">
          <MessagesSquare className="mt-0.5 size-5 shrink-0 text-sky-600" aria-hidden />
          <div className="space-y-2">
            <h2 id="attach-title" className="font-semibold">
              Garder ta conversation ?
            </h2>
            <p id="attach-desc" className="text-sm text-muted-foreground">
              Tu as discuté avec l&apos;assistant avant de te connecter ({n} message{n > 1 ? "s" : ""}).
              Veux-tu l&apos;enregistrer dans ton compte pour la retrouver plus tard ? Sans ton accord,
              elle reste temporaire et sera supprimée à l&apos;expiration de ta session.
            </p>
          </div>
        </div>
        {error && (
          <p className="text-sm text-red-700 dark:text-red-400" role="alert">
            {error}
          </p>
        )}
        <div className="flex flex-wrap justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={() => dismissAttachOffer()} disabled={busy !== null}>
            Plus tard
          </Button>
          <Button variant="outline" size="sm" onClick={() => void answer(false)} disabled={busy !== null}>
            {busy === "no" && <Loader2 className="animate-spin" />}
            Non merci
          </Button>
          <Button size="sm" onClick={() => void answer(true)} disabled={busy !== null}>
            {busy === "yes" && <Loader2 className="animate-spin" />}
            Oui, garder ma conversation
          </Button>
        </div>
      </div>
    </div>
  );
}
