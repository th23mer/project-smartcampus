"""Environnement Alembic (SA-7).

- Métadonnées : `app.core.db.Base.metadata`, remplies par l'import de `app.models` (SA-17).
- Connexion : **synchrone** (psycopg 3) via `MIGRATION_DATABASE_URL`, compte propriétaire du
  schéma (séparé du compte applicatif, SA-4 §9.1).
"""

from __future__ import annotations

from logging.config import fileConfig

from sqlalchemy import create_engine, pool

import app.models  # noqa: F401  (enregistre toutes les tables dans Base.metadata)
from alembic import context
from app.core.config import get_settings
from app.core.db import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _migration_url() -> str:
    url = get_settings().migration_database_url
    if not url:
        raise RuntimeError("MIGRATION_DATABASE_URL n'est pas définie (voir backend/.env.example).")
    return url


def run_migrations_offline() -> None:
    """Génère le SQL sans se connecter (`alembic upgrade head --sql`)."""
    context.configure(
        url=_migration_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Applique les migrations sur la base."""
    connectable = create_engine(_migration_url(), poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
