import type { Metadata } from "next";
import { PlaceholderPage } from "@/components/app/placeholder-page";

export const metadata: Metadata = { title: "Catalogue" };

export default function Page() {
  return (
    <PlaceholderPage
      title="Catalogue"
      description="Formations, conditions d’admission, frais et passerelles, avec publication en double validation (D-B)."
      blocks={[
        { title: "Formations et spécialités", description: "Brouillon → soumis → publié ; validité datée.", owner: "SA-12" },
        { title: "Frais par année universitaire", description: "Une grille officielle par année (D-A).", owner: "SA-12" },
        { title: "Conditions d’admission", description: "Par année universitaire (D-I).", owner: "SA-12" },
        { title: "Publication à quatre yeux", description: "La personne qui publie doit être différente de celle qui a soumis.", owner: "SA-21" },
      ]}
    />
  );
}
