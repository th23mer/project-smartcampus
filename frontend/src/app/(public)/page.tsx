import { ChatPanel } from "@/components/chat/chat-panel";

const PROMISES = [
  { title: "Officiel ou rien", text: "Chaque fait (frais, conditions, dates) vient d’une source publiée et datée, affichée sous la réponse." },
  { title: "Ta langue", text: "Français, tunisien ou arabizi, à l’écrit (et bientôt à l’oral)." },
  { title: "Un humain décide", text: "L’assistant explique et recommande ; l’équipe des admissions valide." },
];

/** Accueil visiteur : présentation courte + chat sans compte. */
export default function HomePage() {
  return (
    <div className="grid gap-8 pt-6 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] lg:pt-12">
      <section className="space-y-6">
        <div className="space-y-3">
          <p className="text-sm font-medium text-emerald-700 dark:text-emerald-400">IIT · ISB · Sfax</p>
          <h1 className="text-3xl font-bold tracking-tight sm:text-4xl">Trouve ta voie après le bac, en discutant.</h1>
          <p className="text-muted-foreground">
            Licence, cycle préparatoire ou ingénierie : pose tes questions, compare les parcours et prépare ta
            pré-inscription. Sans compte pour commencer.
          </p>
        </div>
        <ul className="space-y-3">
          {PROMISES.map((p) => (
            <li key={p.title} className="rounded-lg border bg-card p-3">
              <p className="text-sm font-semibold">{p.title}</p>
              <p className="text-sm text-muted-foreground">{p.text}</p>
            </li>
          ))}
        </ul>
      </section>
      <section aria-label="Chat" className="h-[36rem]">
        <ChatPanel className="h-full" />
      </section>
    </div>
  );
}
