import type { Metadata } from "next";
import { PlaceholderPage } from "@/components/app/placeholder-page";

export const metadata: Metadata = { title: "Tableau de bord" };

export default function Page() {
  return (
    <PlaceholderPage
      title="Tableau de bord"
      description="Où en est mon dossier : étape courante, prochaine action, prochain rendez-vous."
      blocks={[
        { title: "Avancement du dossier", description: "Frise des étapes : conversation, profil, pré-inscription, QCM, rendez-vous, entretien.", owner: "SA-3" },
        { title: "Prochaine action", description: "Ce qui est attendu de moi maintenant (pièce manquante, QCM, confirmation de rendez-vous).", owner: "F7" },
        { title: "Formations envisagées", description: "Ma courte liste de 2 à 3 parcours, comparés côte à côte (Path Explorer).", owner: "F3" },
        { title: "Notifications", description: "Messages et rappels envoyés par la plateforme.", owner: "E3" },
      ]}
    />
  );
}
