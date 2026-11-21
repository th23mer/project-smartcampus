/**
 * Carte source officielle (fonctionnalité signature F1 « Officiel ou rien ») :
 * titre, institution, version, période de validité, extrait.
 */
import type { Citation } from "@/lib/api/chat-types";
import { Badge } from "@/components/ui/badge";

const KIND_LABEL: Record<string, string> = {
  catalogue: "Catalogue officiel",
  document: "Document officiel",
  faq: "FAQ officielle",
};

/** Affiche une date AAAA-MM-JJ en format français (JJ/MM/AAAA), sans décalage de fuseau. */
function frDate(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const [y, m, d] = iso.slice(0, 10).split("-");
  return y && m && d ? `${d}/${m}/${y}` : iso;
}

export function SourceCard({ citation }: { citation: Citation }) {
  const s = citation.source;
  const validTo = frDate(s?.valid_to);
  return (
    <article
      className="rounded-md border border-sky-200 bg-sky-50/60 p-3 text-start text-xs dark:border-sky-900 dark:bg-sky-950/40"
      aria-label={`Source ${citation.id}`}
    >
      <header className="mb-1 flex flex-wrap items-center gap-1.5">
        <Badge variant="secondary" className="font-mono">
          {citation.id}
        </Badge>
        <span className="font-semibold text-foreground">{citation.title}</span>
      </header>
      <p className="flex flex-wrap gap-x-3 gap-y-0.5 text-muted-foreground">
        <span>{KIND_LABEL[citation.kind] ?? "Source officielle"}</span>
        {citation.institution && <span>{citation.institution.toUpperCase()}</span>}
        {s && <span>version {s.version}</span>}
        {validTo && <span>valable jusqu&apos;au {validTo}</span>}
        {citation.page != null && <span>page {citation.page}</span>}
      </p>
      {citation.excerpt && <blockquote className="mt-1.5 border-s-2 ps-2 italic">{citation.excerpt}</blockquote>}
    </article>
  );
}
