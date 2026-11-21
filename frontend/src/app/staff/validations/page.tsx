import type { Metadata } from "next";
import { PlaceholderPage } from "@/components/app/placeholder-page";

export const metadata: Metadata = { title: "Validations en attente" };

export default function Page() {
  return (
    <PlaceholderPage
      title="Validations en attente"
      description="Toutes les décisions humaines préparées par l’IA : l’IA recommande, le staff décide."
      blocks={[
        { title: "Recommandations d’orientation", description: "Confirmer ou ajuster, avec motif.", owner: "F3" },
        { title: "Tableaux d’équivalence", description: "Accepter, modifier ou refuser ligne par ligne.", owner: "F4" },
        { title: "Pièces justificatives", description: "Accepter ou refuser les pièces déposées.", owner: "SA-13" },
        { title: "Publications à relire", description: "Données officielles soumises par un collègue.", owner: "D-B" },
      ]}
    />
  );
}
