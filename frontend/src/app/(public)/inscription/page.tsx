import type { Metadata } from "next";
import { RegisterForm } from "@/components/auth/auth-forms";

export const metadata: Metadata = { title: "Créer un compte" };

export default function Page() {
  return (
    <div className="pt-10">
      <RegisterForm />
    </div>
  );
}
