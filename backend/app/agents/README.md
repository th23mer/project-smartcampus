# `app/agents/` — couche agentique (E4)

Pipeline d'entrée (STT → langue → garde-fou), orchestrateur (ADR-07, ouvert), agents
(Conseiller, Expert programmes, Orientation, Admissions, Relances). Les prompts sont des
fichiers versionnés dans `prompts/` à la racine, jamais des chaînes en dur. Les agents
n'accèdent jamais directement à la base : ils passent par `app/tools/`. **À remplir par E4.**
