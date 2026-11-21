"""Révisions des entités stables publiées (SA-20 D1, validée le 17/11/2026).

Table `catalogue_revision` : champs proposés (jsonb) pour une institution, une formation ou une
spécialité déjà publiée ; la ligne publiée reste visible jusqu'à la publication de la révision
(double validation). Trigger `set_updated_at()`. Les droits du rôle applicatif viennent des
privilèges par défaut de SA-16.

Revision ID: 0005_revisions
Revises: 0004_candidatures
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0005_revisions"
down_revision: str | Sequence[str] | None = "0004_candidatures"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "catalogue_revision",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'draft'"), nullable=False),
        sa.Column("changes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("reason_fr", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("submitted_by", sa.Uuid(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_by", sa.Uuid(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_by", sa.Uuid(), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "entity_type IN ('institution','programme','speciality')",
            name=op.f("ck_catalogue_revision_entity_type"),
        ),
        sa.CheckConstraint(
            "status IN ('draft','pending_review','published','rejected')",
            name=op.f("ck_catalogue_revision_status"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(changes) = 'object' AND changes <> '{}'::jsonb",
            name=op.f("ck_catalogue_revision_changes"),
        ),
        sa.CheckConstraint(
            "status NOT IN ('pending_review','published') OR "
            "(submitted_by IS NOT NULL AND submitted_at IS NOT NULL)",
            name=op.f("ck_catalogue_revision_submitted"),
        ),
        sa.CheckConstraint(
            "status <> 'published' OR (published_by IS NOT NULL AND published_at IS NOT NULL)",
            name=op.f("ck_catalogue_revision_published"),
        ),
        sa.CheckConstraint(
            "status <> 'rejected' OR (rejected_by IS NOT NULL AND rejected_at IS NOT NULL)",
            name=op.f("ck_catalogue_revision_rejected"),
        ),
        sa.CheckConstraint(
            "published_by IS NULL OR published_by <> submitted_by",
            name=op.f("ck_catalogue_revision_four_eyes"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["user_account.id"], name=op.f("fk_catalogue_revision_created_by")
        ),
        sa.ForeignKeyConstraint(
            ["submitted_by"], ["user_account.id"], name=op.f("fk_catalogue_revision_submitted_by")
        ),
        sa.ForeignKeyConstraint(
            ["published_by"], ["user_account.id"], name=op.f("fk_catalogue_revision_published_by")
        ),
        sa.ForeignKeyConstraint(
            ["rejected_by"], ["user_account.id"], name=op.f("fk_catalogue_revision_rejected_by")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_catalogue_revision")),
    )
    op.create_index(
        "ix_catalogue_revision_entity",
        "catalogue_revision",
        ["entity_type", "entity_id", sa.text("created_at DESC")],
        unique=False,
    )
    op.create_index(
        "uq_catalogue_revision_open",
        "catalogue_revision",
        ["entity_type", "entity_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('draft','pending_review')"),
    )
    op.execute(
        "CREATE TRIGGER trg_catalogue_revision_updated_at BEFORE UPDATE ON catalogue_revision "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_catalogue_revision_updated_at ON catalogue_revision")
    op.drop_index("uq_catalogue_revision_open", table_name="catalogue_revision")
    op.drop_index("ix_catalogue_revision_entity", table_name="catalogue_revision")
    op.drop_table("catalogue_revision")
