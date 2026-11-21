# `app/services/` — logique métier déterministe

Un module par domaine (catalogue, candidatures, rendez-vous…). Règles d'éligibilité, frais,
dates, créneaux, transitions de statut (machines à états SA-3) : **du code testé, jamais le
LLM**. Les routeurs et les outils d'agent appellent ces services.
