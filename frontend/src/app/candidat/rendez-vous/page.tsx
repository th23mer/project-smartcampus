import type { Metadata } from "next";
import { PlaceholderPage } from "@/components/app/placeholder-page";

export const metadata: Metadata = { title: "Rendez-vous" };

export default function Page() {
  return (
    <PlaceholderPage
      title="Rendez-vous"
      description="Créneaux autorisés, réservation, confirmation et rappels par e-mail."
      blocks={[
        { title: "Créneaux disponibles", description: "Liste calculée par le code selon le type de rendez-vous et le statut du dossier.", owner: "SA-3" },
        { title: "Mes rendez-vous", description: "Proposé, réservé, confirmé, réalisé ; annulation avec motif.", owner: "SA-3" },
      ]}
    />
  );
}
