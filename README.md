# SmartCampus AI

Plateforme conversationnelle et agentique d'orientation universitaire (IIT / ISB) : un candidat discute en français, en tunisien ou en Arabizi, reçoit une orientation justifiée, se pré-inscrit et est suivi jusqu'au rendez-vous d'inscription. Les décisions officielles restent humaines.

Projet du cours d'IA générative, 3e année génie informatique, IIT Sfax, 2026-2027.

> **État actuel (sprint « Socle Technique », E1)** : squelette du backend FastAPI (santé, erreurs, documentation automatique), frontend Next.js (espaces visiteur, candidat, staff) et environnement Docker. La base de données et l'API du catalogue arrivent avec E2.

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
make up        # construit et démarre backend, frontend, mailpit (attend qu'ils soient sains)
```

Puis ouvrir :

| Service | Adresse |
|---|---|
| Application (frontend) | http://localhost:3000 |
| API : documentation interactive (Swagger) | http://localhost:8000/docs |
| API : documentation ReDoc | http://localhost:8000/redoc |
| API : santé | http://localhost:8000/api/v1/health |
| Boîte mail de test (Mailpit) | http://localhost:8025 |

Arrêter : `make stop` (conserve tout) ou `make down` (supprime les conteneurs).

### Un port est déjà pris ?

Modifier les ports dans `.env`, puis `make up` :

```bash
FRONTEND_HOST_PORT=3100   # au lieu de 3000
```


## 3. Utiliser l'application (frontend)

Ouvrir http://localhost:3000. En haut de page, le **sélecteur de rôle** (mode dev) permet de changer d'identité sans compte :

| Identité | Espace | Pages |
|---|---|---|
| Visiteur (sans compte) | `/` | Accueil et chat de démonstration (flux simulé) |
| Candidat | `/candidat` | Tableau de bord, profil, pré-inscription, rendez-vous |
| Staff (responsable IIT, ISB, entretiens, direction, admin) | `/staff` | Tableau de bord, catalogue, validations, documents, radar des lacunes |

Raccourci pour une démo : ajouter `?dev_role=<clé>` à l'URL, par exemple http://localhost:3000/staff?dev_role=iit_academic_lead (clés : `visitor`, `candidate`, `iit_academic_lead`, `isb_academic_lead`, `interview_lead`, `direction`, `platform_admin`).

Les pages candidat et staff sont pour l'instant des **squelettes** : la structure est en place, le contenu métier arrive avec les prochains sprints. Un indicateur montre en permanence si le backend répond.

## 4. Utiliser l'API

Tout est sous `/api/v1`. Le plus simple est Swagger : http://localhost:8000/docs (bouton « Try it out »).

```bash
curl http://localhost:8000/api/v1/health
```

En dev, l'identité passe par des en-têtes simulés (refusés hors `APP_ENV=dev|test`) : `X-Dev-User-Id` (UUID), `X-Dev-Roles` (ex. `iit_academic_lead`) et `X-Dev-Institution-Id` (facultatif).

### Erreurs

Toutes les erreurs ont le même format :

```json
{ "error": { "code": "VALIDATION_ERROR", "message": "…", "details": [ … ], "request_id": "req_…" } }
```

Le `request_id` (aussi dans l'en-tête `X-Request-ID`) permet de retrouver la requête dans les journaux (`make logs SERVICE=backend`).

## 5. Ce qui est simulé aujourd'hui

| Élément | Aujourd'hui | Plus tard |
|---|---|---|
| Authentification | en-têtes `X-Dev-*` / sélecteur de rôle | connexion réelle candidat / staff |
| Chat | flux simulé (`NEXT_PUBLIC_CHAT_MOCK=true`) | LLM + agents + RAG |
| Base de données | pas encore branchée (`/health/ready` répond 503) | PostgreSQL + pgvector (E2) |

## 6. Commandes utiles

`make help` liste toutes les commandes. Les principales :

| Commande | Effet |
|---|---|
| `make up` / `make stop` / `make down` | démarrer / arrêter / supprimer les conteneurs |
| `make ps`, `make logs SERVICE=backend` | état des services, journaux |
| `make test` | tous les tests (backend pytest + frontend vitest) |
| `make lint` | ruff, eslint, tsc |
| `make shell-backend` | shell dans le conteneur backend |
| `make build` | reconstruire les images (après un changement de dépendances) |

Services optionnels : `docker compose --profile seaweedfs up -d` (stockage S3), `--profile mlflow` (suivi des expériences), `make worker`.

## 7. Organisation du dépôt

| Dossier | Contenu |
|---|---|
| `backend/` | API FastAPI : `app/api` (routes), `app/services` (métier), `app/models` (tables), `app/tools` (outils de l'agent), `alembic/` (migrations), `tests/` |
| `frontend/` | Next.js + Tailwind + shadcn/ui : espaces visiteur, candidat, staff ; client API dans `src/lib/api` |

## 8. Dépannage

| Symptôme | Solution |
|---|---|
| `make up` échoue : port déjà utilisé | changer le port dans `.env` (§ 2) |
| `permission denied` sur Docker | ajouter l'utilisateur au groupe `docker` et se reconnecter |
| Erreur 401 `UNAUTHENTICATED` | ajouter les en-têtes `X-Dev-*` (§ 4) |
| Après un changement de dépendances | `make build` puis `make up` |

Les données de ce dépôt sont **synthétiques** : aucune donnée personnelle réelle.
