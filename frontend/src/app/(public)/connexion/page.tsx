import type { Metadata } from "next";
import { LoginForm } from "@/components/auth/auth-forms";

export const metadata: Metadata = { title: "Connexion" };

export default function Page() {
  return (
    <div className="pt-10">
      <LoginForm />
    </div>
  );
}
