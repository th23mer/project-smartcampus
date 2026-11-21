import type { Metadata } from "next";
import { PlaceholderPage } from "@/components/app/placeholder-page";

export const metadata: Metadata = { title: "Mon profil" };

export default function Page() {
  return (
    <PlaceholderPage
      title="Mon profil"
      description="Les informations que l’assistant a comprises, avec leur provenance. Je peux les corriger."
      blocks={[
        { title: "Baccalauréat", description: "Série, année, moyenne, notes par matière.", owner: "SA-13" },
        { title: "Objectifs et contraintes", description: "Matières préférées, métier visé, budget, préférence pratique ou théorique.", owner: "F3" },
        { title: "Provenance des champs", description: "Pour chaque fait : saisi par moi ou extrait de la conversation (à confirmer).", owner: "SA-13" },
        { title: "Consentements", description: "Traitement des données, rattachement de la conversation, accès du staff au brut.", owner: "E3" },
      ]}
    />
  );
}
