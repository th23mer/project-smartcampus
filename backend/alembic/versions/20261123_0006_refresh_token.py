"""Jetons de renouvellement de l'authentification (SA-28, E3).

Table `refresh_token` : jeton opaque du cookie `sc_refresh` (SA-5 §1.2, D3), stocké haché
(SHA-256), avec rotation (`replaced_by_id`) et famille (`family_id`) pour révoquer toute la
chaîne si un ancien jeton est réutilisé. Trigger `set_updated_at()`. Les droits du rôle
applicatif viennent des privilèges par défaut de SA-16.

Revision ID: 0006_refresh_token
Revises: 0005_revisions
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006_refresh_token"
down_revision: str | Sequence[str] | None = "0005_revisions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "refresh_token",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaced_by_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("expires_at > created_at", name=op.f("ck_refresh_token_expiry")),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user_account.id"],
            name=op.f("fk_refresh_token_user_id"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["replaced_by_id"],
            ["refresh_token.id"],
            name=op.f("fk_refresh_token_replaced_by_id"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_refresh_token")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_refresh_token_token_hash")),
    )
    op.create_index(op.f("ix_refresh_token_user_id"), "refresh_token", ["user_id"])
    op.create_index(op.f("ix_refresh_token_family_id"), "refresh_token", ["family_id"])
    op.execute(
        "CREATE TRIGGER trg_refresh_token_updated_at BEFORE UPDATE ON refresh_token "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_refresh_token_updated_at ON refresh_token")
    op.drop_index(op.f("ix_refresh_token_family_id"), table_name="refresh_token")
    op.drop_index(op.f("ix_refresh_token_user_id"), table_name="refresh_token")
    op.drop_table("refresh_token")
