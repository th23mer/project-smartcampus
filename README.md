# SmartCampus AI

Plateforme conversationnelle et agentique d'orientation universitaire (IIT / ISB) : un candidat discute en français, en tunisien ou en Arabizi, reçoit une orientation justifiée, se pré-inscrit et est suivi jusqu'au rendez-vous d'inscription. Les décisions officielles restent humaines.

Projet du cours d'IA générative, 3e année génie informatique, IIT Sfax, 2026-2027.

> **État actuel (sprint « Socle Technique »)** : base de données, API du catalogue (formations, cursus, frais, conditions d'admission), squelette du frontend, environnement Docker, et (E3) **chat sans compte avec session visiteur et mémoire, connexion / inscription, rattachement de la conversation au compte**. Le LLM et le RAG arrivent avec E4 : en attendant, l'assistant répond par un **message de secours** (voir § 5).

---

## 1. Prérequis

| Outil | Version | Vérifier |
|---|---|---|
| Docker Engine + Compose v2 | Docker ≥ 24, Compose ≥ 2.24 | `docker info` doit répondre **sans sudo** (Linux : `sudo usermod -aG docker $USER`, puis se reconnecter). macOS / Windows : Docker Desktop (Windows : depuis WSL 2). |
| GNU make | toute version | `make --version` |
| uv, Node.js 24 | facultatifs | Seulement pour l'IDE ou lancer hors conteneur. Tout tourne dans Docker. |

## 2. Démarrage rapide

```bash
git clone https://github.com/th23mer/smartcampus-ai.git
cd smartcampus-ai

make env       # crée .env à partir de .env.example (mots de passe factices de dev)
make up        # construit et démarre db, db-test, backend, frontend, mailpit (attend qu'ils soient sains)
make migrate   # crée les tables (migrations Alembic)
make seed      # charge les données de démonstration (100 % fictives)
```

Puis ouvrir :

| Service | Adresse |
|---|---|
| Application (frontend) | http://localhost:3000 |
| API : documentation interactive (Swagger) | http://localhost:8000/docs |
| API : documentation ReDoc | http://localhost:8000/redoc |
| API : santé | http://localhost:8000/api/v1/health/ready |
| Boîte mail de test (Mailpit) | http://localhost:8025 |

Arrêter : `make stop` (conserve tout) ou `make down` (supprime les conteneurs, **garde** la base).

### Un port est déjà pris ?

Modifier les ports dans `.env`, puis `make up` :

```bash
DB_HOST_PORT=55432        # au lieu de 5432
FRONTEND_HOST_PORT=3100   # au lieu de 3000
```

Si vous changez `DB_HOST_PORT`, changez aussi le port dans `DATABASE_URL`, `MIGRATION_DATABASE_URL` et `RAG_READER_DATABASE_URL` (même chose pour `DB_TEST_HOST_PORT` et les variables `TEST_*`). Tous les ports sont ouverts sur `127.0.0.1` seulement.

## 3. Utiliser l'application (frontend)

Ouvrir http://localhost:3000.

**Comptes réels (E3)** :

- le chat de l'accueil fonctionne **sans compte** : au premier message, une session visiteur et une conversation sont créées (cookie httpOnly) ; le compteur « n/30 messages » s'affiche. Sans LLM branché, l'assistant répond par le **message de secours** (E4 branchera le modèle) ;
- **Se connecter** (`/connexion`) ou **Créer un compte** (`/inscription`, compte candidat, deux accords obligatoires) ;
- après connexion, si tu as discuté avant, la fenêtre **« Garder ta conversation ? »** demande ton accord (SA-29) ; « Oui » enregistre la conversation dans ton compte ;
- `/candidat` et `/staff` demandent une connexion avec le bon rôle ; la session est retrouvée au rechargement de la page, **Se déconnecter** la ferme ;
- compte staff : `make shell-backend` puis `uv run python scripts/create_staff.py --email … --full-name … --roles iit_academic_lead` (après `make seed`).

**Sélecteur de rôle** (mode dev, en bas à droite) : il reste disponible pour parcourir les espaces sans compte, par en-têtes simulés (ignorés dès qu'un utilisateur est connecté) :

| Identité | Espace | Pages |
|---|---|---|
| Visiteur (sans compte) | `/` | Accueil et chat |
| Candidat | `/candidat` | Tableau de bord, profil, pré-inscription, rendez-vous |
| Staff (responsable IIT, ISB, entretiens, direction, admin) | `/staff` | Tableau de bord, catalogue, validations, documents, radar des lacunes |

Raccourci pour une démo : ajouter `?dev_role=<clé>` à l'URL, par exemple http://localhost:3000/staff?dev_role=iit_academic_lead (clés : `visitor`, `candidate`, `iit_academic_lead`, `isb_academic_lead`, `interview_lead`, `direction`, `platform_admin`).

Les pages candidat et staff sont pour l'instant des **squelettes** : la structure est en place, le contenu métier arrive avec les prochains sprints. Un indicateur montre en permanence si le backend répond.

## 4. Utiliser l'API

Tout est sous `/api/v1`. Le plus simple est Swagger : http://localhost:8000/docs (bouton « Try it out »).

### Consulter le catalogue public (sans identité)

Seules les données **publiées et valides** à la date demandée sont renvoyées.

```bash
curl http://localhost:8000/api/v1/catalogue/institutions
curl "http://localhost:8000/api/v1/catalogue/programmes?q=informatique"
curl "http://localhost:8000/api/v1/catalogue/programmes/<programme_id>/fees?academic_year=2026-2027"
```

L'année universitaire est **obligatoire** pour les frais et les conditions d'admission (sinon `422 ACADEMIC_YEAR_REQUIRED`, avec la liste des années publiées).

### Agir comme responsable (routes `/staff/catalogue/...`)

En dev, l'identité passe par des en-têtes simulés (refusés hors `APP_ENV=dev|test`) :

| En-tête | Rôle |
|---|---|
| `X-Dev-User-Id` | UUID de l'utilisateur (obligatoire) |
| `X-Dev-Roles` | rôles séparés par des virgules, ex. `iit_academic_lead` |
| `X-Dev-Institution-Id` | périmètre : IIT `5eed0000-0000-4000-8000-000000001001`, ISB `5eed0000-0000-4000-8000-000000001002` |

Comptes staff de démonstration créés par `make seed` (aucun mot de passe réel) :

| Rôle | `X-Dev-User-Id` |
|---|---|
| Responsable académique IIT (A) | `5eed0000-0000-4000-8000-000000000001` |
| Responsable académique IIT (B) | `5eed0000-0000-4000-8000-000000000002` |
| Responsable académique ISB | `5eed0000-0000-4000-8000-000000000003` |
| Responsable entretiens | `5eed0000-0000-4000-8000-000000000004` |
| Direction | `5eed0000-0000-4000-8000-000000000005` |
| Administrateur plateforme | `5eed0000-0000-4000-8000-000000000006` |

Exemple : lister les formations côté responsable IIT.

```bash
curl http://localhost:8000/api/v1/staff/catalogue/programmes \
  -H "X-Dev-User-Id: 5eed0000-0000-4000-8000-000000000001" \
  -H "X-Dev-Roles: iit_academic_lead" \
  -H "X-Dev-Institution-Id: 5eed0000-0000-4000-8000-000000001001"
```

### Cycle de publication d'une donnée officielle

`brouillon` → `soumettre` → `en relecture` → `publier` → `publiée` → `archiver`

- **Double validation** : celui qui soumet ne peut pas publier. Utilisez le responsable IIT (A) pour soumettre et le responsable IIT (B) ou la direction pour publier (sinon `403 FOUR_EYES_REQUIRED`). L'administrateur ne publie jamais.
- Une donnée publiée est figée : pour la corriger, créer une **nouvelle version**.
- **Supprimer** n'est possible que pour un brouillon ; une donnée publiée s'archive.
- Les modifications utilisent l'en-tête `If-Match` (version reçue dans l'`ETag`) pour éviter d'écraser le travail d'un autre.

### Visiteurs, comptes et conversations (E3 : SA-25, SA-26, SA-28, SA-29)

Pré-requis : `JWT_SECRET` (32 caractères minimum) dans `.env`, puis `make migrate` (révision `0006`).
Dans Swagger (`/docs`), les cookies sont gérés par le navigateur ; le jeton d'accès se colle dans **Authorize**.

| Tâche | Routes | Règles |
|---|---|---|
| SA-25 Sessions visiteur | `POST /visitor-sessions`, `GET` / `DELETE /visitor-sessions/current` | cookie `sc_visitor` (httpOnly, jeton haché en base) ; session réutilisée par le même navigateur ; 24 h d'inactivité, 7 j max ; 30 messages / 24 h (`429 VISITOR_QUOTA_EXCEEDED`) ; « oublier ma session » ; purge 30 j après expiration (`python -m app.jobs.purge_visitor_sessions`) |
| SA-26 Mémoire | `POST` / `GET /conversations`, `GET /conversations/{id}`, `GET` / `POST /conversations/{id}/messages` | messages dans `message` ; chacun ne voit que ses conversations (404 sinon) ; envoi idempotent par `client_message_id` ; quota compté dans la même transaction ; contexte de l'agent = 20 derniers messages ; sans LLM branché : `503 LLM_UNAVAILABLE` + secours déterministe, message conservé |
| SA-28 Authentification | `POST /auth/register`, `/auth/login`, `/auth/refresh`, `/auth/logout`, `GET /auth/me` | inscription publique = candidat ; Argon2id ; JWT 15 min + cookie `sc_refresh` 7 j avec rotation ; 5 échecs / 15 min → 429 ; comptes staff : `uv run python scripts/create_staff.py --email … --full-name … --roles iit_academic_lead` |
| SA-29 Rattachement | `attach_offer` à l'inscription / connexion, puis `POST /auth/attach-visitor-session` | jeton candidat **et** cookie de la même session ; `consent` booléen strict ; refus = rien ne bouge ; accord = conversations déplacées vers le compte, consentement journalisé ; un seul propriétaire (409) |

Exemple rapide (curl garde les cookies dans `jar.txt`) :

```bash
API=http://localhost:8000/api/v1
curl -s -c jar.txt -b jar.txt -X POST $API/visitor-sessions -H 'Content-Type: application/json' -d '{}'
CONV=$(curl -s -c jar.txt -b jar.txt -X POST $API/conversations -H 'Content-Type: application/json' -d '{}' | jq -r .id)
curl -s -c jar.txt -b jar.txt -X POST $API/conversations/$CONV/messages -H 'Content-Type: application/json' \
  -d "{\"client_message_id\": \"$(uuidgen)\", \"content\": {\"type\": \"text\", \"text\": \"Bonjour\"}}"
curl -s -c jar.txt -b jar.txt -X POST $API/auth/register -H 'Content-Type: application/json' \
  -d '{"email":"candidat@example.com","password":"MotDePasse-2026","full_name":"Candidat Fictif","consents":{"terms_accepted":true,"data_processing":true}}'
```

La réponse de l'inscription contient `attach_offer` ; le candidat accepte avec
`POST /auth/attach-visitor-session` (`{"visitor_session_id": "…", "consent": true}`, en-tête `Authorization: Bearer …`).

### Erreurs

Toutes les erreurs ont le même format :

```json
{ "error": { "code": "VALIDATION_ERROR", "message": "…", "details": [ … ], "request_id": "req_…" } }
```

Le `request_id` (aussi dans l'en-tête `X-Request-ID`) permet de retrouver la requête dans les journaux (`make logs SERVICE=backend`).

## 5. Ce qui est simulé aujourd'hui

| Élément | Aujourd'hui | Plus tard |
|---|---|---|
| Réponse de l'assistant | secours déterministe (texte fixe) ; faux flux de démonstration avec `NEXT_PUBLIC_CHAT_MOCK=true` | LLM + agents + RAG (E4 branche `set_chat_responder`, flux SSE) |
| Sélecteur de rôle (dev) | en-têtes `X-Dev-*` pour parcourir les espaces sans compte | retiré hors dev |
| Worker de synchronisation RAG | service provisoire (profil `worker`) | indexation des documents |

## 6. Commandes utiles

`make help` liste toutes les commandes. Les principales :

| Commande | Effet |
|---|---|
| `make up` / `make stop` / `make down` | démarrer / arrêter / supprimer les conteneurs (la base est conservée) |
| `make ps`, `make logs SERVICE=backend` | état des services, journaux |
| `make migrate`, `make migrate-status` | appliquer les migrations, voir la révision courante |
| `make seed` | (re)charger les données de démo ; relancé, il ne crée aucun doublon |
| `make test` | tous les tests (backend pytest + frontend vitest), ≈ 5 min |
| `make lint` | ruff, eslint, tsc |
| `make psql`, `make shell-backend` | console SQL, shell dans le conteneur backend |
| `make reset-db` | **supprime** la base de dev (demande confirmation) |
| `make build` | reconstruire les images (après un changement de dépendances) |

Services optionnels : `docker compose --profile seaweedfs up -d` (stockage S3), `--profile mlflow` (suivi des expériences), `make worker`.

## 7. Organisation du dépôt

| Dossier | Contenu |
|---|---|
| `backend/` | API FastAPI : `app/api` (routes), `app/services` (métier), `app/models` (tables), `app/tools` (outils de l'agent), `alembic/` (migrations), `scripts/seed.py`, `tests/` |
| `frontend/` | Next.js + Tailwind + shadcn/ui : espaces visiteur, candidat, staff ; client API dans `src/lib/api` |
| `infra/` | initialisation de PostgreSQL (rôles et droits) |

## 8. Dépannage

| Symptôme | Solution |
|---|---|
| `make up` échoue : port déjà utilisé | changer le port dans `.env` (§ 2) |
| `permission denied` sur Docker | ajouter l'utilisateur au groupe `docker` et se reconnecter |
| `/health/ready` renvoie 503 | la base démarre encore : attendre ou `make ps` / `make logs SERVICE=db` |
| Erreur « relation does not exist » | lancer `make migrate` |
| Catalogue vide | lancer `make seed` |
| Erreur 401 `UNAUTHENTICATED` sur `/staff/...` | ajouter les en-têtes `X-Dev-*` (§ 4) |
| Erreur 403 `FOUR_EYES_REQUIRED` | publier avec un autre compte que celui qui a soumis |
| Après un changement de dépendances | `make build` puis `make up` |

Les données de ce dépôt sont **synthétiques** : aucune donnée personnelle réelle.
