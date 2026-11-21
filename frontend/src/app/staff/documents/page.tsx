import type { Metadata } from "next";
import { PlaceholderPage } from "@/components/app/placeholder-page";

export const metadata: Metadata = { title: "Documents officiels" };

export default function Page() {
  return (
    <PlaceholderPage
      title="Documents officiels"
      description="Documents du RAG : dépôt, versions, état d’indexation, publication (refusée tant que non indexé, D-C)."
      blocks={[
        { title: "Documents et versions", description: "Brouillon indexé dès le dépôt, invisible au RAG jusqu’à publication.", owner: "SA-14" },
        { title: "Synchronisation vectorielle", description: "File de jobs, état par version, erreurs.", owner: "SA-14" },
      ]}
    />
  );
}
