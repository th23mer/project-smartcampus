#!/usr/bin/env bash
# SA-16 · Lance la vérification PostgreSQL (infra/db/check_db.py) avec uv.
# Prérequis : docker compose up -d db db-test ; fichier .env à la racine.
# Usage : infra/db/check_db.sh [--target dev|test|all] [--env-file chemin]
set -euo pipefail
RACINE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
UV="${UV:-$(command -v uv || echo "$HOME/.local/bin/uv")}"
if [[ ! -f "$RACINE/.env" ]]; then
  echo "Fichier .env absent : cp .env.example .env puis adapter les valeurs." >&2
  exit 2
fi
exec "$UV" run --quiet --python 3.12 --script "$RACINE/infra/db/check_db.py" "$@"
