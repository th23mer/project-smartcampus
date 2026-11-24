# SmartCampus AI · frontend (SA-8)

Next.js 16 (App Router) + TypeScript strict + Tailwind 4 + shadcn/ui. Interface en français (`lang="fr"`), classes logiques prêtes pour le RTL.

## Lancer

```bash
cp .env.example .env.local   # NEXT_PUBLIC_API_BASE_URL, NEXT_PUBLIC_APP_ENV, NEXT_PUBLIC_CHAT_MOCK
npm ci
npm run dev                  # http://localhost:3000
npm test                     # vitest (client API, lecteur SSE, session, transport du chat)
npm run lint && npm run build
```

## Espaces

- `/` : accueil + chat visiteur, sans compte (API réelle ; faux flux si `NEXT_PUBLIC_CHAT_MOCK=true`).
- `/connexion`, `/inscription` : connexion candidat ou staff, création d'un compte candidat (E3).
- `/candidat`, `/candidat/profil`, `/candidat/pre-inscription`, `/candidat/rendez-vous`.
- `/staff`, `/staff/catalogue`, `/staff/validations`, `/staff/documents`, `/staff/lacunes`.

## Couche API (`src/lib/api/`)

- `client.ts` : client `fetch` typé, préfixe `/api/v1`, cookies inclus ; `Authorization: Bearer` si l'utilisateur est connecté (un 401 renouvelle le jeton une fois), sinon en-têtes `X-Dev-User-Id` / `X-Dev-Roles` si `NEXT_PUBLIC_APP_ENV=dev`.
- `errors.ts` : `ApiError` (code, message, details, request_id) au format SA-5 §1.4 ; `NETWORK_ERROR` si le backend est arrêté.
- `sse.ts` : lecteur SSE (fetch + ReadableStream) et réducteur des événements du chat (SA-5 §3.3).

## Authentification et chat (E3, `src/lib/auth/`, `src/lib/chat/`)

- `auth/session.ts` : connexion, inscription, déconnexion ; jeton d'accès **en mémoire** (`auth/token.ts`), cookie httpOnly `sc_refresh` pour le renouveler ; `restoreSession()` au chargement de la page.
- Après connexion / inscription, si une conversation visiteur existe, la fenêtre « Garder ta conversation ? » demande le consentement (SA-29) puis appelle `/auth/attach-visitor-session`.
- `chat/transport.ts` : au premier message, session visiteur (`POST /visitor-sessions`, cookie `sc_visitor`) puis conversation ; réponse JSON aujourd'hui, SSE quand E4 l'aura branché ; secours affiché si le LLM est indisponible ; quota visiteur affiché (30 messages / 24 h).
- `components/auth/require-role.tsx` : les espaces `/candidat` et `/staff` demandent une connexion (ou, en dev, l'identité simulée du même espace). Ce n'est qu'un affichage : le backend vérifie les droits.

Outils de dev (seulement si `NEXT_PUBLIC_APP_ENV=dev`) : sélecteur de rôle en bas à droite, `?dev_role=<rôle>` et `?demo=<message>` dans l'URL.
