import type { Metadata } from "next";
import { PlaceholderPage } from "@/components/app/placeholder-page";

export const metadata: Metadata = { title: "Pré-inscription" };

export default function Page() {
  return (
    <PlaceholderPage
      title="Pré-inscription"
      description="Mon dossier pour la formation choisie : données, pièces justificatives, QCM ciblé."
      blocks={[
        { title: "Formation visée", description: "Formation et spécialité, campagne d’admission ouverte (vérifiée par le code).", owner: "SA-12" },
        { title: "Pièces justificatives", description: "Dépôt et statut de vérification (décision humaine).", owner: "SA-13" },
        { title: "QCM ciblé", description: "QCM composé à partir de la banque validée ; retour qualitatif, pas de score affiché (D-G).", owner: "F6" },
        { title: "Demande d’équivalence", description: "Pour les candidats en transfert : relevé de notes et tableau proposé.", owner: "F4" },
      ]}
    />
  );
}
