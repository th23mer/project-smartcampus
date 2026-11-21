# Migrations Alembic

- `uv run alembic revision --autogenerate -m "message"` puis relire la migration générée.
- `uv run alembic upgrade head` (utilise `MIGRATION_DATABASE_URL`, pilote psycopg 3).
- `versions/` est rempli par SA-17 (modèles E2). Les extensions (`vector`, `btree_gist`,
  `pgcrypto` si besoin) sont créées par les scripts d'initialisation de SA-16 ou par la
  première migration.
