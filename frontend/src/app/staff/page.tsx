import type { Metadata } from "next";
import { PlaceholderPage } from "@/components/app/placeholder-page";

export const metadata: Metadata = { title: "Vue d’ensemble" };

export default function Page() {
  return (
    <PlaceholderPage
      title="Vue d’ensemble"
      description="Entonnoir visiteurs → pré-inscriptions → entretiens → inscriptions, et tâches du jour."
      blocks={[
        { title: "Entonnoir", description: "Chiffres calculés par le code sur les dossiers de mon périmètre.", owner: "Pilotage" },
        { title: "À traiter aujourd’hui", description: "Validations, entretiens et relances escaladées qui m’attendent.", owner: "F7" },
      ]}
    />
  );
}
