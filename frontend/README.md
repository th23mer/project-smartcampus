# SmartCampus AI · frontend (SA-8)

Next.js 16 (App Router) + TypeScript strict + Tailwind 4 + shadcn/ui. Interface en français (`lang="fr"`), classes logiques prêtes pour le RTL.

## Lancer

```bash
cp .env.example .env.local   # NEXT_PUBLIC_API_BASE_URL, NEXT_PUBLIC_APP_ENV, NEXT_PUBLIC_CHAT_MOCK
npm ci
npm run dev                  # http://localhost:3000
npm test                     # vitest (client API + lecteur SSE)
npm run lint && npm run build
```

## Espaces

- `/` : accueil + chat visiteur (faux flux SSE local tant que l'endpoint E4 n'existe pas).
- `/candidat`, `/candidat/profil`, `/candidat/pre-inscription`, `/candidat/rendez-vous`.
- `/staff`, `/staff/catalogue`, `/staff/validations`, `/staff/documents`, `/staff/lacunes`.

## Couche API (`src/lib/api/`)

- `client.ts` : client `fetch` typé, préfixe `/api/v1`, en-têtes `X-Dev-User-Id` / `X-Dev-Roles` si `NEXT_PUBLIC_APP_ENV=dev`.
- `errors.ts` : `ApiError` (code, message, details, request_id) au format SA-5 §1.4 ; `NETWORK_ERROR` si le backend est arrêté.
- `sse.ts` : lecteur SSE (fetch + ReadableStream) et réducteur des événements du chat (SA-5 §3.3).

Outils de dev (seulement si `NEXT_PUBLIC_APP_ENV=dev`) : sélecteur de rôle en bas à droite, `?dev_role=<rôle>` et `?demo=<message>` dans l'URL.
