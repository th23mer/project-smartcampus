"""Socle : extensions et fonction générique set_updated_at()

Extensions : citext (e-mail, SA-13), btree_gist (exclusions, SA-12 D2), pgcrypto (digest),
vector (pgvector, créée par le superutilisateur à l'init SA-16 : seulement vérifiée ici).

Révision : 0001_socle
Révise : <base>
Créée le : 2026-11-16 (SA-17)
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001_socle"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # vector n'est pas « trusted » : le rôle propriétaire ne peut pas la créer (SA-16).
    op.execute(
        """
        DO $$ BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector') THEN
            RAISE EXCEPTION 'Extension vector absente : elle doit être créée par un '
              'superutilisateur (SA-16, infra/db/init/01-roles.sh).';
          END IF;
        END $$
        """
    )
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")
    # Fonction générique : met à jour updated_at à chaque UPDATE (SA-12 D16, partagée).
    op.execute(
        """
        CREATE FUNCTION set_updated_at() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          NEW.updated_at := now();
          RETURN NEW;
        END $$
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS set_updated_at()")
    # btree_gist, pgcrypto et vector viennent de l'init SA-16 : on ne les supprime pas.
    op.execute("DROP EXTENSION IF EXISTS citext")
