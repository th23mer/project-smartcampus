# syntax=docker/dockerfile:1
# Image du frontend SmartCampus AI (SA-9) : Next.js (App Router), Node 24.
#
# ATTENTION : les variables NEXT_PUBLIC_* sont INCRUSTÉES dans le JavaScript envoyé au
# navigateur au moment de `next build`. Elles sont donc passées en ARGUMENTS DE BUILD
# (build.args dans docker-compose.yml), recopiées en ENV pour `next build` / `next dev`.
# Changer une de ces valeurs = reconstruire l'image (`make build`) pour la cible prod.
# En dev (`next dev`), elles sont relues à chaque démarrage du conteneur depuis l'environnement.
# Aucun secret dans NEXT_PUBLIC_* : tout est visible dans le navigateur.
#
# Cibles : dev (next dev, code monté en volume) ; prod (next build + next start).

ARG NODE_IMAGE=node:24.22.0-bookworm-slim

FROM ${NODE_IMAGE} AS deps
WORKDIR /app
COPY package.json package-lock.json ./
# Installation reproductible depuis le registre npm officiel, figée par package-lock.json.
RUN npm ci --no-audit --no-fund

FROM ${NODE_IMAGE} AS base
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1 \
    NPM_CONFIG_UPDATE_NOTIFIER=false \
    TZ=Africa/Tunis
ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
ARG NEXT_PUBLIC_APP_ENV=dev
ARG NEXT_PUBLIC_CHAT_MOCK=false
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL} \
    NEXT_PUBLIC_APP_ENV=${NEXT_PUBLIC_APP_ENV} \
    NEXT_PUBLIC_CHAT_MOCK=${NEXT_PUBLIC_CHAT_MOCK}

# --- Cible dev ------------------------------------------------------------------------------
FROM base AS dev
# L'image officielle fournit l'utilisateur non root `node` (UID 1000).
COPY --from=deps --chown=node:node /app/node_modules ./node_modules
COPY --chown=node:node . .
RUN mkdir -p .next && chown node:node /app /app/.next
USER node
EXPOSE 3000
# Sonde légère (fichier statique) : en dev, la page d'accueil se compile à la demande et peut
# dépasser le délai de la sonde ; le favicon prouve que le serveur Next.js répond.
HEALTHCHECK --interval=10s --timeout=5s --start-period=120s --retries=6 \
  CMD node -e "fetch('http://127.0.0.1:3000/favicon.ico').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"
CMD ["npx", "next", "dev", "--hostname", "0.0.0.0", "--port", "3000"]

# --- Cible prod -----------------------------------------------------------------------------
FROM base AS build
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM base AS prod
ENV NODE_ENV=production
COPY --from=build --chown=node:node /app ./
USER node
EXPOSE 3000
HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=6 \
  CMD node -e "fetch('http://127.0.0.1:3000/').then(r=>process.exit(r.status<500?0:1)).catch(()=>process.exit(1))"
CMD ["npx", "next", "start", "--hostname", "0.0.0.0", "--port", "3000"]
