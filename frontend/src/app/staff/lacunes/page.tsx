import type { Metadata } from "next";
import { PlaceholderPage } from "@/components/app/placeholder-page";

export const metadata: Metadata = { title: "Radar des lacunes" };

export default function Page() {
  return (
    <PlaceholderPage
      title="Radar des lacunes"
      description="Les questions auxquelles l’assistant n’a pas trouvé de réponse officielle, regroupées chaque semaine (F8)."
      blocks={[
        { title: "Top des lacunes", description: "Groupes de questions sans source officielle, avec fréquence.", owner: "F8" },
        { title: "Suivi de résolution", description: "Lacune fermée quand une fiche ou un document est publié.", owner: "F8" },
      ]}
    />
  );
}
