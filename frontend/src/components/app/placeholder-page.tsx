/**
 * Page vide structurée : titre, description et blocs prévus,
 * en attendant les tâches qui les rempliront.
 */
import { Badge } from "@/components/ui/badge";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export interface PlannedBlock {
  title: string;
  description: string;
  /** Tâche ou fonctionnalité qui remplira le bloc (ex. « SA-… », « F3 »). */
  owner?: string;
}

export function PlaceholderPage({
  title,
  description,
  blocks,
}: {
  title: string;
  description: string;
  blocks: PlannedBlock[];
}) {
  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        <p className="mt-1 text-sm text-muted-foreground">{description}</p>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        {blocks.map((b) => (
          <Card key={b.title} className="border-dashed">
            <CardHeader>
              <div className="flex items-start justify-between gap-2">
                <CardTitle className="text-base">{b.title}</CardTitle>
                {b.owner && (
                  <Badge variant="secondary" className="shrink-0 text-[10px]">
                    {b.owner}
                  </Badge>
                )}
              </div>
              <CardDescription>{b.description}</CardDescription>
            </CardHeader>
          </Card>
        ))}
      </div>
    </div>
  );
}
