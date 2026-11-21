"""Identité (comptes, rôles) et catalogue académique (SA-12, SA-13 §A)

Tables user_account, role, user_role et les 13 tables du catalogue + catalogue_audit_log.
SQL brut : triggers set_updated_at, audit_catalogue (C5), garde des versions publiées
(SA-12 D17) ; REVOKE UPDATE/DELETE du rôle applicatif sur le journal d'audit (SA-16).

Révision : 0002_identite_catalogue
Révise : 0001_socle
Créée le : 2026-11-16 (SA-17)
"""

from collections.abc import Sequence

import pgvector.sqlalchemy.vector  # noqa: F401  (type VECTOR rendu par l'autogénération)
import sqlalchemy as sa
from alembic import op
from sqlalchemy import Text, Uuid  # noqa: F401  (types rendus par l'autogénération)
from sqlalchemy.dialects import postgresql

revision: str = "0002_identite_catalogue"
down_revision: str | Sequence[str] | None = "0001_socle"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


#: Tables du catalogue journalisées par audit_catalogue() (SA-12 §3, C5).
CATALOGUE_TABLES = (
    "institution",
    "programme",
    "speciality",
    "subject",
    "curriculum",
    "curriculum_subject",
    "prerequisite",
    "admission_condition",
    "admission_subject_requirement",
    "fee_schedule",
    "payment_plan",
    "payment_installment",
    "bridge",
)
#: Faits versionnés (catégorie B) : version publiée figée (SA-12 règle 3, D17).
VERSIONED_TABLES = ("curriculum", "admission_condition", "fee_schedule", "bridge")
#: Tables avec updated_at dans cette révision.
UPDATED_AT_TABLES = (
    "user_account",
    "institution",
    "programme",
    "role",
    "subject",
    "speciality",
    "user_role",
    "admission_condition",
    "bridge",
    "curriculum",
    "fee_schedule",
    "admission_subject_requirement",
    "curriculum_subject",
    "payment_plan",
    "payment_installment",
    "prerequisite",
)

AUDIT_FUNCTION = """
CREATE FUNCTION audit_catalogue() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  o jsonb := CASE WHEN TG_OP <> 'INSERT' THEN to_jsonb(OLD) END;
  n jsonb := CASE WHEN TG_OP <> 'DELETE' THEN to_jsonb(NEW) END;
  act text := lower(TG_OP);
  fields text[];
BEGIN
  IF TG_OP = 'UPDATE' THEN
    SELECT array_agg(k ORDER BY k) INTO fields
      FROM jsonb_object_keys(n) k
     WHERE k NOT IN ('updated_at','validity') AND n -> k IS DISTINCT FROM o -> k;
    IF fields IS NULL THEN RETURN NEW; END IF;          -- rien de significatif n'a changé
    IF n ->> 'publication_status' IS DISTINCT FROM o ->> 'publication_status' THEN
      act := CASE n ->> 'publication_status'
               WHEN 'pending_review' THEN 'submit'
               WHEN 'published'      THEN 'publish'
               WHEN 'draft'          THEN 'reject'
               WHEN 'archived'       THEN 'archive' END;
    END IF;
  END IF;
  INSERT INTO catalogue_audit_log (table_name, row_id, action, actor_id, old_values, new_values,
                                   changed_fields)
  VALUES (TG_TABLE_NAME, COALESCE(n ->> 'id', o ->> 'id')::uuid, act,
          NULLIF(current_setting('app.current_user_id', true), '')::uuid, o, n, fields);
  RETURN NULL;                                          -- trigger AFTER : valeur ignorée
END $$
"""

# Garde des versions publiées (SA-12 règle 3 / D17, SA-14 §4.3) : une version publiée ou
# archivée est figée. Permis : raccourcir valid_to, passer published -> archived, et les
# colonnes passées en argument du trigger (ex. état d'index d'une document_version).
# Suppression interdite (on archive). Erreur check_violation, contrainte gd_<table>_frozen.
GUARD_FUNCTION = """
CREATE FUNCTION guard_published_version() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  o jsonb;
  n jsonb;
  k text;
  allowed text[];
  cname text := 'gd_' || TG_TABLE_NAME || '_frozen';
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF OLD.publication_status IN ('published','archived') THEN
      RAISE EXCEPTION 'Suppression interdite : la ligne % de % est %, il faut l''archiver.',
            OLD.id, TG_TABLE_NAME, OLD.publication_status
            USING ERRCODE = 'check_violation', CONSTRAINT = cname;
    END IF;
    RETURN OLD;
  END IF;
  IF OLD.publication_status NOT IN ('published','archived') THEN
    RETURN NEW;
  END IF;
  -- colonnes générées : pas encore calculées dans un trigger BEFORE, donc ignorées
  allowed := ARRAY['valid_to','publication_status','updated_at'] || TG_ARGV
          || ARRAY(SELECT attname::text FROM pg_attribute
                    WHERE attrelid = TG_RELID AND attgenerated <> '' AND NOT attisdropped);
  o := to_jsonb(OLD);
  n := to_jsonb(NEW);
  FOR k IN SELECT jsonb_object_keys(n) LOOP
    IF n -> k IS DISTINCT FROM o -> k AND NOT k = ANY (allowed) THEN
      RAISE EXCEPTION 'Version publiée figée : la colonne % de % (%) ne peut plus changer ; '
            'créer une nouvelle version.', k, TG_TABLE_NAME, OLD.id
            USING ERRCODE = 'check_violation', CONSTRAINT = cname;
    END IF;
  END LOOP;
  IF NEW.publication_status IS DISTINCT FROM OLD.publication_status
     AND NOT (OLD.publication_status = 'published' AND NEW.publication_status = 'archived') THEN
    RAISE EXCEPTION 'Transition interdite % -> % sur % (%).', OLD.publication_status,
          NEW.publication_status, TG_TABLE_NAME, OLD.id
          USING ERRCODE = 'check_violation', CONSTRAINT = cname;
  END IF;
  IF NEW.valid_to IS DISTINCT FROM OLD.valid_to
     AND (NEW.valid_to IS NULL OR (OLD.valid_to IS NOT NULL AND NEW.valid_to > OLD.valid_to)) THEN
    RAISE EXCEPTION 'Sur une version publiée, valid_to peut seulement être raccourci (% -> %).',
          OLD.valid_to, NEW.valid_to
          USING ERRCODE = 'check_violation', CONSTRAINT = cname;
  END IF;
  RETURN NEW;
END $$
"""


def _if_role(role: str, sql: str) -> None:
    """Exécute `sql` seulement si le rôle SA-16 existe (base créée sans infra/db/init)."""
    sql = sql.replace("'", "''")
    op.execute(
        f"DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') "
        f"THEN EXECUTE '{sql}'; END IF; END $$"
    )


def _updated_at_triggers(tables: Sequence[str]) -> None:
    """Pose le trigger générique `set_updated_at()` (SA-12 D16) sur chaque table."""
    for t in tables:
        op.execute(
            f"CREATE TRIGGER trg_{t}_updated_at BEFORE UPDATE ON {t} "
            "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
        )


def _drop_triggers(tables: Sequence[str], suffix: str) -> None:
    for t in tables:
        op.execute(f"DROP TRIGGER IF EXISTS trg_{t}_{suffix} ON {t}")


def upgrade() -> None:
    op.create_table(
        "user_account",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column("phone", sa.Text(), nullable=True),
        sa.Column("account_type", sa.Text(), nullable=False),
        sa.Column("preferred_language", sa.Text(), server_default=sa.text("'fr'"), nullable=False),
        sa.Column(
            "account_status",
            sa.Text(),
            server_default=sa.text("'pending_verification'"),
            nullable=False,
        ),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("anonymized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "account_status IN ('pending_verification','active','disabled')",
            name=op.f("ck_user_account_account_status"),
        ),
        sa.CheckConstraint(
            "account_type IN ('candidate','staff')", name=op.f("ck_user_account_account_type")
        ),
        sa.CheckConstraint(
            "preferred_language IN ('fr','aeb_arab','aeb_latn','ar','en','mixed','unknown')",
            name=op.f("ck_user_account_preferred_language"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_account")),
        sa.UniqueConstraint("email", name=op.f("uq_user_account_email")),
    )
    op.create_table(
        "catalogue_audit_log",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("table_name", sa.Text(), nullable=False),
        sa.Column("row_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("old_values", postgresql.JSONB(astext_type=Text()), nullable=True),
        sa.Column("new_values", postgresql.JSONB(astext_type=Text()), nullable=True),
        sa.Column("changed_fields", postgresql.ARRAY(Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "action IN ('insert','update','delete','submit','publish','reject','archive')",
            name=op.f("ck_catalogue_audit_log_action"),
        ),
        sa.CheckConstraint(
            "table_name IN ('institution','programme','speciality','subject','curriculum','curriculum_subject','prerequisite','admission_condition','admission_subject_requirement','fee_schedule','payment_plan','payment_installment','bridge')",
            name=op.f("ck_catalogue_audit_log_table_name"),
        ),
        sa.CheckConstraint(
            "old_values IS NOT NULL OR new_values IS NOT NULL",
            name=op.f("ck_catalogue_audit_log_values"),
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["user_account.id"],
            name=op.f("fk_catalogue_audit_log_actor_id"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_catalogue_audit_log")),
    )
    op.create_index(
        "ix_catalogue_audit_log_actor",
        "catalogue_audit_log",
        ["actor_id", sa.literal_column("created_at DESC")],
        unique=False,
    )
    op.create_index(
        "ix_catalogue_audit_log_row",
        "catalogue_audit_log",
        ["table_name", "row_id", sa.literal_column("created_at DESC")],
        unique=False,
    )
    op.create_table(
        "institution",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name_fr", sa.Text(), nullable=False),
        sa.Column("name_ar", sa.Text(), nullable=True),
        sa.Column("city", sa.Text(), nullable=False),
        sa.Column("website_url", sa.Text(), nullable=True),
        sa.Column("description_fr", sa.Text(), nullable=True),
        sa.Column(
            "publication_status", sa.Text(), server_default=sa.text("'draft'"), nullable=False
        ),
        sa.Column("valid_from", sa.Date(), nullable=True),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column(
            "validity",
            postgresql.DATERANGE(),
            sa.Computed("daterange(valid_from, valid_to, '[)')", persisted=True),
            nullable=True,
        ),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("submitted_by", sa.Uuid(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_by", sa.Uuid(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("code ~ '^[A-Z0-9_]{2,16}$'", name=op.f("ck_institution_code")),
        sa.CheckConstraint(
            "publication_status <> 'published' OR (published_by IS NOT NULL AND published_at IS NOT NULL)",
            name=op.f("ck_institution_published"),
        ),
        sa.CheckConstraint(
            "publication_status IN ('draft','pending_review','published','archived')",
            name=op.f("ck_institution_publication_status"),
        ),
        sa.CheckConstraint(
            "publication_status NOT IN ('pending_review','published') OR (valid_from IS NOT NULL AND submitted_by IS NOT NULL AND submitted_at IS NOT NULL)",
            name=op.f("ck_institution_submitted"),
        ),
        sa.CheckConstraint(
            "published_by IS NULL OR published_by <> submitted_by",
            name=op.f("ck_institution_four_eyes"),
        ),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_from IS NULL OR valid_to > valid_from",
            name=op.f("ck_institution_validity"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["user_account.id"], name=op.f("fk_institution_created_by")
        ),
        sa.ForeignKeyConstraint(
            ["published_by"], ["user_account.id"], name=op.f("fk_institution_published_by")
        ),
        sa.ForeignKeyConstraint(
            ["submitted_by"], ["user_account.id"], name=op.f("fk_institution_submitted_by")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_institution")),
        sa.UniqueConstraint("code", name=op.f("uq_institution_code")),
    )
    op.create_table(
        "programme",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("institution_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name_fr", sa.Text(), nullable=False),
        sa.Column("name_ar", sa.Text(), nullable=True),
        sa.Column("programme_type", sa.Text(), nullable=False),
        sa.Column("diploma_name_fr", sa.Text(), nullable=True),
        sa.Column("duration_years", sa.SmallInteger(), nullable=False),
        sa.Column("total_ects", sa.SmallInteger(), nullable=True),
        sa.Column("description_fr", sa.Text(), nullable=True),
        sa.Column("career_outcomes_fr", sa.Text(), nullable=True),
        sa.Column(
            "publication_status", sa.Text(), server_default=sa.text("'draft'"), nullable=False
        ),
        sa.Column("valid_from", sa.Date(), nullable=True),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column(
            "validity",
            postgresql.DATERANGE(),
            sa.Computed("daterange(valid_from, valid_to, '[)')", persisted=True),
            nullable=True,
        ),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("submitted_by", sa.Uuid(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_by", sa.Uuid(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("code ~ '^[A-Z0-9_-]{2,32}$'", name=op.f("ck_programme_code")),
        sa.CheckConstraint(
            "programme_type IN ('preparatory','licence','engineering','master','other')",
            name=op.f("ck_programme_programme_type"),
        ),
        sa.CheckConstraint(
            "publication_status <> 'published' OR (published_by IS NOT NULL AND published_at IS NOT NULL)",
            name=op.f("ck_programme_published"),
        ),
        sa.CheckConstraint(
            "publication_status IN ('draft','pending_review','published','archived')",
            name=op.f("ck_programme_publication_status"),
        ),
        sa.CheckConstraint(
            "publication_status NOT IN ('pending_review','published') OR (valid_from IS NOT NULL AND submitted_by IS NOT NULL AND submitted_at IS NOT NULL)",
            name=op.f("ck_programme_submitted"),
        ),
        sa.CheckConstraint(
            "duration_years BETWEEN 1 AND 6", name=op.f("ck_programme_duration_years")
        ),
        sa.CheckConstraint(
            "published_by IS NULL OR published_by <> submitted_by",
            name=op.f("ck_programme_four_eyes"),
        ),
        sa.CheckConstraint("total_ects > 0", name=op.f("ck_programme_total_ects")),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_from IS NULL OR valid_to > valid_from",
            name=op.f("ck_programme_validity"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["user_account.id"], name=op.f("fk_programme_created_by")
        ),
        sa.ForeignKeyConstraint(
            ["institution_id"],
            ["institution.id"],
            name=op.f("fk_programme_institution_id"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["published_by"], ["user_account.id"], name=op.f("fk_programme_published_by")
        ),
        sa.ForeignKeyConstraint(
            ["submitted_by"], ["user_account.id"], name=op.f("fk_programme_submitted_by")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_programme")),
        sa.UniqueConstraint("code", name=op.f("uq_programme_code")),
    )
    op.create_index(
        "ix_programme_fts",
        "programme",
        [
            sa.literal_column(
                "to_tsvector('french'::regconfig, (name_fr || ' '::text) || COALESCE(description_fr, ''::text))"
            )
        ],
        unique=False,
        postgresql_using="gin",
    )
    op.create_index("ix_programme_institution", "programme", ["institution_id"], unique=False)
    op.create_index(
        "ix_programme_official",
        "programme",
        ["validity"],
        unique=False,
        postgresql_using="gist",
        postgresql_where=sa.text("publication_status = 'published'"),
    )
    op.create_table(
        "role",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("is_staff", sa.Boolean(), nullable=False),
        sa.Column("institution_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["institution_id"], ["institution.id"], name=op.f("fk_role_institution_id")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_role")),
        sa.UniqueConstraint("code", name=op.f("uq_role_code")),
    )
    op.create_index(op.f("ix_role_institution_id"), "role", ["institution_id"], unique=False)
    op.create_table(
        "subject",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("institution_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name_fr", sa.Text(), nullable=False),
        sa.Column("name_ar", sa.Text(), nullable=True),
        sa.Column("domain", sa.Text(), nullable=True),
        sa.Column("description_fr", sa.Text(), nullable=True),
        sa.Column("learning_outcomes_fr", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("code ~ '^[A-Z0-9_-]{2,32}$'", name=op.f("ck_subject_code")),
        sa.ForeignKeyConstraint(
            ["institution_id"],
            ["institution.id"],
            name=op.f("fk_subject_institution_id"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_subject")),
        sa.UniqueConstraint("institution_id", "code", name="uq_subject_institution_code"),
    )
    op.create_index(
        "ix_subject_fts",
        "subject",
        [
            sa.literal_column(
                "to_tsvector('french'::regconfig, (name_fr || ' '::text) || COALESCE(description_fr, ''::text))"
            )
        ],
        unique=False,
        postgresql_using="gin",
    )
    op.create_index("ix_subject_institution", "subject", ["institution_id"], unique=False)
    op.create_table(
        "speciality",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("programme_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name_fr", sa.Text(), nullable=False),
        sa.Column("name_ar", sa.Text(), nullable=True),
        sa.Column("description_fr", sa.Text(), nullable=True),
        sa.Column("career_outcomes_fr", sa.Text(), nullable=True),
        sa.Column(
            "publication_status", sa.Text(), server_default=sa.text("'draft'"), nullable=False
        ),
        sa.Column("valid_from", sa.Date(), nullable=True),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column(
            "validity",
            postgresql.DATERANGE(),
            sa.Computed("daterange(valid_from, valid_to, '[)')", persisted=True),
            nullable=True,
        ),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("submitted_by", sa.Uuid(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_by", sa.Uuid(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("code ~ '^[A-Z0-9_-]{2,32}$'", name=op.f("ck_speciality_code")),
        sa.CheckConstraint(
            "publication_status <> 'published' OR (published_by IS NOT NULL AND published_at IS NOT NULL)",
            name=op.f("ck_speciality_published"),
        ),
        sa.CheckConstraint(
            "publication_status IN ('draft','pending_review','published','archived')",
            name=op.f("ck_speciality_publication_status"),
        ),
        sa.CheckConstraint(
            "publication_status NOT IN ('pending_review','published') OR (valid_from IS NOT NULL AND submitted_by IS NOT NULL AND submitted_at IS NOT NULL)",
            name=op.f("ck_speciality_submitted"),
        ),
        sa.CheckConstraint(
            "published_by IS NULL OR published_by <> submitted_by",
            name=op.f("ck_speciality_four_eyes"),
        ),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_from IS NULL OR valid_to > valid_from",
            name=op.f("ck_speciality_validity"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["user_account.id"], name=op.f("fk_speciality_created_by")
        ),
        sa.ForeignKeyConstraint(
            ["programme_id"],
            ["programme.id"],
            name=op.f("fk_speciality_programme_id"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["published_by"], ["user_account.id"], name=op.f("fk_speciality_published_by")
        ),
        sa.ForeignKeyConstraint(
            ["submitted_by"], ["user_account.id"], name=op.f("fk_speciality_submitted_by")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_speciality")),
        sa.UniqueConstraint("id", "programme_id", name="uq_speciality_id_programme"),
        sa.UniqueConstraint("programme_id", "code", name="uq_speciality_programme_code"),
    )
    op.create_index(
        "ix_speciality_fts",
        "speciality",
        [
            sa.literal_column(
                "to_tsvector('french'::regconfig, (name_fr || ' '::text) || COALESCE(description_fr, ''::text))"
            )
        ],
        unique=False,
        postgresql_using="gin",
    )
    op.create_index(
        "ix_speciality_official",
        "speciality",
        ["programme_id", "validity"],
        unique=False,
        postgresql_using="gist",
        postgresql_where=sa.text("publication_status = 'published'"),
    )
    op.create_table(
        "user_role",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column("granted_by", sa.Uuid(), nullable=True),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["granted_by"], ["user_account.id"], name=op.f("fk_user_role_granted_by")
        ),
        sa.ForeignKeyConstraint(["role_id"], ["role.id"], name=op.f("fk_user_role_role_id")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["user_account.id"], name=op.f("fk_user_role_user_id")
        ),
        sa.PrimaryKeyConstraint("user_id", "role_id", name=op.f("pk_user_role")),
    )
    op.create_index(
        "ix_user_role_role_active",
        "user_role",
        ["role_id"],
        unique=False,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.create_table(
        "admission_condition",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("programme_id", sa.Uuid(), nullable=False),
        sa.Column("speciality_id", sa.Uuid(), nullable=True),
        sa.Column("entry_level", sa.SmallInteger(), nullable=False),
        sa.Column("applicant_category", sa.Text(), nullable=False),
        sa.Column("required_diploma", sa.Text(), nullable=False),
        sa.Column("accepted_bac_sections", postgresql.ARRAY(Text()), nullable=True),
        sa.Column(
            "min_validated_years", sa.SmallInteger(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("min_average", sa.Numeric(precision=4, scale=2), nullable=True),
        sa.Column("average_basis", sa.Text(), nullable=True),
        sa.Column(
            "requires_application_file",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("requires_test", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "requires_interview", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("max_places", sa.Integer(), nullable=True),
        sa.Column("academic_year", sa.Text(), nullable=False),
        sa.Column("summary_fr", sa.Text(), nullable=False),
        sa.Column(
            "publication_status", sa.Text(), server_default=sa.text("'draft'"), nullable=False
        ),
        sa.Column("valid_from", sa.Date(), nullable=True),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column(
            "validity",
            postgresql.DATERANGE(),
            sa.Computed("daterange(valid_from, valid_to, '[)')", persisted=True),
            nullable=True,
        ),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("submitted_by", sa.Uuid(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_by", sa.Uuid(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        postgresql.ExcludeConstraint(
            (sa.column("programme_id"), "="),
            (sa.text("COALESCE(speciality_id, '00000000-0000-0000-0000-000000000000'::uuid)"), "="),
            (sa.column("entry_level"), "="),
            (sa.column("applicant_category"), "="),
            (sa.column("academic_year"), "="),
            (sa.column("validity"), "&&"),
            where=sa.text("publication_status = 'published'"),
            using="gist",
            name=op.f("ex_admission_condition_one_published"),
        ),
        sa.CheckConstraint(
            "academic_year ~ '^[0-9]{4}-[0-9]{4}$'",
            name=op.f("ck_admission_condition_academic_year"),
        ),
        sa.CheckConstraint(
            "accepted_bac_sections <@ ARRAY['mathematiques', 'sciences_experimentales', 'sciences_techniques', 'sciences_informatique', 'economie_gestion', 'lettres', 'sport']::text[]",
            name=op.f("ck_admission_condition_accepted_bac_sections"),
        ),
        sa.CheckConstraint(
            "applicant_category IN ('new_bachelor','higher_education_graduate','transfer_student')",
            name=op.f("ck_admission_condition_applicant_category"),
        ),
        sa.CheckConstraint(
            "average_basis IS NULL OR average_basis IN ('bac_average','last_year_average','cycle_average')",
            name=op.f("ck_admission_condition_average_basis"),
        ),
        sa.CheckConstraint(
            "publication_status <> 'published' OR (published_by IS NOT NULL AND published_at IS NOT NULL)",
            name=op.f("ck_admission_condition_published"),
        ),
        sa.CheckConstraint(
            "publication_status IN ('draft','pending_review','published','archived')",
            name=op.f("ck_admission_condition_publication_status"),
        ),
        sa.CheckConstraint(
            "publication_status NOT IN ('pending_review','published') OR (valid_from IS NOT NULL AND submitted_by IS NOT NULL AND submitted_at IS NOT NULL)",
            name=op.f("ck_admission_condition_submitted"),
        ),
        sa.CheckConstraint(
            "required_diploma = 'baccalaureate' OR accepted_bac_sections IS NULL",
            name=op.f("ck_admission_condition_bac"),
        ),
        sa.CheckConstraint(
            "required_diploma IN ('baccalaureate','preparatory_cycle','licence','other_higher_education')",
            name=op.f("ck_admission_condition_required_diploma"),
        ),
        sa.CheckConstraint(
            "(min_average IS NULL) = (average_basis IS NULL)",
            name=op.f("ck_admission_condition_average"),
        ),
        sa.CheckConstraint(
            "entry_level BETWEEN 1 AND 5", name=op.f("ck_admission_condition_entry_level")
        ),
        sa.CheckConstraint("max_places > 0", name=op.f("ck_admission_condition_max_places")),
        sa.CheckConstraint(
            "min_average BETWEEN 0 AND 20", name=op.f("ck_admission_condition_min_average")
        ),
        sa.CheckConstraint(
            "min_validated_years BETWEEN 0 AND 5",
            name=op.f("ck_admission_condition_min_validated_years"),
        ),
        sa.CheckConstraint(
            "published_by IS NULL OR published_by <> submitted_by",
            name=op.f("ck_admission_condition_four_eyes"),
        ),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_from IS NULL OR valid_to > valid_from",
            name=op.f("ck_admission_condition_validity"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["user_account.id"], name=op.f("fk_admission_condition_created_by")
        ),
        sa.ForeignKeyConstraint(
            ["programme_id"],
            ["programme.id"],
            name=op.f("fk_admission_condition_programme_id"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["published_by"], ["user_account.id"], name=op.f("fk_admission_condition_published_by")
        ),
        sa.ForeignKeyConstraint(
            ["speciality_id", "programme_id"],
            ["speciality.id", "speciality.programme_id"],
            name="fk_admission_condition_speciality",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["submitted_by"], ["user_account.id"], name=op.f("fk_admission_condition_submitted_by")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_admission_condition")),
    )
    op.create_index(
        "ix_admission_condition_programme", "admission_condition", ["programme_id"], unique=False
    )
    op.create_index(
        "ix_admission_condition_sections",
        "admission_condition",
        ["accepted_bac_sections"],
        unique=False,
        postgresql_using="gin",
    )
    op.create_index(
        "ix_admission_condition_speciality", "admission_condition", ["speciality_id"], unique=False
    )
    op.create_index(
        "ix_admission_condition_status",
        "admission_condition",
        ["publication_status", sa.literal_column("updated_at DESC")],
        unique=False,
    )
    op.create_table(
        "bridge",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("source_programme_id", sa.Uuid(), nullable=False),
        sa.Column("source_speciality_id", sa.Uuid(), nullable=True),
        sa.Column("source_min_completed_years", sa.SmallInteger(), nullable=False),
        sa.Column("target_programme_id", sa.Uuid(), nullable=False),
        sa.Column("target_speciality_id", sa.Uuid(), nullable=True),
        sa.Column("target_entry_level", sa.SmallInteger(), nullable=False),
        sa.Column("access_mode", sa.Text(), nullable=False),
        sa.Column("conditions_summary_fr", sa.Text(), nullable=False),
        sa.Column(
            "publication_status", sa.Text(), server_default=sa.text("'draft'"), nullable=False
        ),
        sa.Column("valid_from", sa.Date(), nullable=True),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column(
            "validity",
            postgresql.DATERANGE(),
            sa.Computed("daterange(valid_from, valid_to, '[)')", persisted=True),
            nullable=True,
        ),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("submitted_by", sa.Uuid(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_by", sa.Uuid(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        postgresql.ExcludeConstraint(
            (sa.column("source_programme_id"), "="),
            (
                sa.text(
                    "COALESCE(source_speciality_id, '00000000-0000-0000-0000-000000000000'::uuid)"
                ),
                "=",
            ),
            (sa.column("target_programme_id"), "="),
            (
                sa.text(
                    "COALESCE(target_speciality_id, '00000000-0000-0000-0000-000000000000'::uuid)"
                ),
                "=",
            ),
            (sa.column("target_entry_level"), "="),
            (sa.column("validity"), "&&"),
            where=sa.text("publication_status = 'published'"),
            using="gist",
            name=op.f("ex_bridge_one_published"),
        ),
        sa.CheckConstraint(
            "access_mode IN ('automatic','on_application','competitive_exam')",
            name=op.f("ck_bridge_access_mode"),
        ),
        sa.CheckConstraint(
            "publication_status <> 'published' OR (published_by IS NOT NULL AND published_at IS NOT NULL)",
            name=op.f("ck_bridge_published"),
        ),
        sa.CheckConstraint(
            "publication_status IN ('draft','pending_review','published','archived')",
            name=op.f("ck_bridge_publication_status"),
        ),
        sa.CheckConstraint(
            "publication_status NOT IN ('pending_review','published') OR (valid_from IS NOT NULL AND submitted_by IS NOT NULL AND submitted_at IS NOT NULL)",
            name=op.f("ck_bridge_submitted"),
        ),
        sa.CheckConstraint(
            "published_by IS NULL OR published_by <> submitted_by", name=op.f("ck_bridge_four_eyes")
        ),
        sa.CheckConstraint(
            "source_min_completed_years BETWEEN 0 AND 6",
            name=op.f("ck_bridge_source_min_completed_years"),
        ),
        sa.CheckConstraint(
            "source_programme_id <> target_programme_id OR source_speciality_id IS DISTINCT FROM target_speciality_id",
            name=op.f("ck_bridge_distinct"),
        ),
        sa.CheckConstraint(
            "target_entry_level BETWEEN 1 AND 5", name=op.f("ck_bridge_target_entry_level")
        ),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_from IS NULL OR valid_to > valid_from",
            name=op.f("ck_bridge_validity"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["user_account.id"], name=op.f("fk_bridge_created_by")
        ),
        sa.ForeignKeyConstraint(
            ["published_by"], ["user_account.id"], name=op.f("fk_bridge_published_by")
        ),
        sa.ForeignKeyConstraint(
            ["source_programme_id"],
            ["programme.id"],
            name=op.f("fk_bridge_source_programme_id"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_speciality_id", "source_programme_id"],
            ["speciality.id", "speciality.programme_id"],
            name="fk_bridge_source_speciality",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["submitted_by"], ["user_account.id"], name=op.f("fk_bridge_submitted_by")
        ),
        sa.ForeignKeyConstraint(
            ["target_programme_id"],
            ["programme.id"],
            name=op.f("fk_bridge_target_programme_id"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["target_speciality_id", "target_programme_id"],
            ["speciality.id", "speciality.programme_id"],
            name="fk_bridge_target_speciality",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bridge")),
    )
    op.create_index("ix_bridge_source", "bridge", ["source_programme_id"], unique=False)
    op.create_index("ix_bridge_target", "bridge", ["target_programme_id"], unique=False)
    op.create_table(
        "curriculum",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("programme_id", sa.Uuid(), nullable=False),
        sa.Column("speciality_id", sa.Uuid(), nullable=True),
        sa.Column("version_label", sa.Text(), nullable=False),
        sa.Column("academic_year", sa.Text(), nullable=False),
        sa.Column("total_ects", sa.SmallInteger(), nullable=True),
        sa.Column("notes_fr", sa.Text(), nullable=True),
        sa.Column(
            "publication_status", sa.Text(), server_default=sa.text("'draft'"), nullable=False
        ),
        sa.Column("valid_from", sa.Date(), nullable=True),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column(
            "validity",
            postgresql.DATERANGE(),
            sa.Computed("daterange(valid_from, valid_to, '[)')", persisted=True),
            nullable=True,
        ),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("submitted_by", sa.Uuid(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_by", sa.Uuid(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        postgresql.ExcludeConstraint(
            (sa.column("programme_id"), "="),
            (sa.text("COALESCE(speciality_id, '00000000-0000-0000-0000-000000000000'::uuid)"), "="),
            (sa.column("validity"), "&&"),
            where=sa.text("publication_status = 'published'"),
            using="gist",
            name=op.f("ex_curriculum_one_published"),
        ),
        sa.CheckConstraint(
            "academic_year ~ '^[0-9]{4}-[0-9]{4}$'", name=op.f("ck_curriculum_academic_year")
        ),
        sa.CheckConstraint(
            "publication_status <> 'published' OR (published_by IS NOT NULL AND published_at IS NOT NULL)",
            name=op.f("ck_curriculum_published"),
        ),
        sa.CheckConstraint(
            "publication_status IN ('draft','pending_review','published','archived')",
            name=op.f("ck_curriculum_publication_status"),
        ),
        sa.CheckConstraint(
            "publication_status NOT IN ('pending_review','published') OR (valid_from IS NOT NULL AND submitted_by IS NOT NULL AND submitted_at IS NOT NULL)",
            name=op.f("ck_curriculum_submitted"),
        ),
        sa.CheckConstraint(
            "published_by IS NULL OR published_by <> submitted_by",
            name=op.f("ck_curriculum_four_eyes"),
        ),
        sa.CheckConstraint("total_ects > 0", name=op.f("ck_curriculum_total_ects")),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_from IS NULL OR valid_to > valid_from",
            name=op.f("ck_curriculum_validity"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["user_account.id"], name=op.f("fk_curriculum_created_by")
        ),
        sa.ForeignKeyConstraint(
            ["programme_id"],
            ["programme.id"],
            name=op.f("fk_curriculum_programme_id"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["published_by"], ["user_account.id"], name=op.f("fk_curriculum_published_by")
        ),
        sa.ForeignKeyConstraint(
            ["speciality_id", "programme_id"],
            ["speciality.id", "speciality.programme_id"],
            name="fk_curriculum_speciality",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["submitted_by"], ["user_account.id"], name=op.f("fk_curriculum_submitted_by")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_curriculum")),
        sa.UniqueConstraint(
            "programme_id",
            "speciality_id",
            "version_label",
            name="uq_curriculum_version",
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_index("ix_curriculum_programme", "curriculum", ["programme_id"], unique=False)
    op.create_index("ix_curriculum_speciality", "curriculum", ["speciality_id"], unique=False)
    op.create_index(
        "ix_curriculum_status",
        "curriculum",
        ["publication_status", sa.literal_column("updated_at DESC")],
        unique=False,
    )
    op.create_table(
        "fee_schedule",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("programme_id", sa.Uuid(), nullable=False),
        sa.Column("speciality_id", sa.Uuid(), nullable=True),
        sa.Column("study_year", sa.SmallInteger(), nullable=True),
        sa.Column(
            "student_category", sa.Text(), server_default=sa.text("'tunisian'"), nullable=False
        ),
        sa.Column("academic_year", sa.Text(), nullable=False),
        sa.Column("currency", sa.CHAR(length=3), server_default=sa.text("'TND'"), nullable=False),
        sa.Column("registration_fee", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column("annual_tuition_fee", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column(
            "other_fees",
            sa.Numeric(precision=12, scale=3),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("other_fees_label_fr", sa.Text(), nullable=True),
        sa.Column(
            "annual_total",
            sa.Numeric(precision=12, scale=3),
            sa.Computed("registration_fee + annual_tuition_fee + other_fees", persisted=True),
            nullable=True,
        ),
        sa.Column("notes_fr", sa.Text(), nullable=True),
        sa.Column(
            "publication_status", sa.Text(), server_default=sa.text("'draft'"), nullable=False
        ),
        sa.Column("valid_from", sa.Date(), nullable=True),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column(
            "validity",
            postgresql.DATERANGE(),
            sa.Computed("daterange(valid_from, valid_to, '[)')", persisted=True),
            nullable=True,
        ),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("submitted_by", sa.Uuid(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_by", sa.Uuid(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        postgresql.ExcludeConstraint(
            (sa.column("programme_id"), "="),
            (sa.text("COALESCE(speciality_id, '00000000-0000-0000-0000-000000000000'::uuid)"), "="),
            (sa.text("COALESCE(study_year, 0::smallint)"), "="),
            (sa.column("student_category"), "="),
            (sa.column("academic_year"), "="),
            (sa.column("validity"), "&&"),
            where=sa.text("publication_status = 'published'"),
            using="gist",
            name=op.f("ex_fee_schedule_one_published"),
        ),
        sa.CheckConstraint(
            "academic_year ~ '^[0-9]{4}-[0-9]{4}$'", name=op.f("ck_fee_schedule_academic_year")
        ),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name=op.f("ck_fee_schedule_currency")),
        sa.CheckConstraint(
            "publication_status <> 'published' OR (published_by IS NOT NULL AND published_at IS NOT NULL)",
            name=op.f("ck_fee_schedule_published"),
        ),
        sa.CheckConstraint(
            "publication_status IN ('draft','pending_review','published','archived')",
            name=op.f("ck_fee_schedule_publication_status"),
        ),
        sa.CheckConstraint(
            "publication_status NOT IN ('pending_review','published') OR (valid_from IS NOT NULL AND submitted_by IS NOT NULL AND submitted_at IS NOT NULL)",
            name=op.f("ck_fee_schedule_submitted"),
        ),
        sa.CheckConstraint(
            "student_category IN ('tunisian','foreign')",
            name=op.f("ck_fee_schedule_student_category"),
        ),
        sa.CheckConstraint(
            "annual_tuition_fee >= 0", name=op.f("ck_fee_schedule_annual_tuition_fee")
        ),
        sa.CheckConstraint(
            "other_fees = 0 OR other_fees_label_fr IS NOT NULL",
            name=op.f("ck_fee_schedule_other_label"),
        ),
        sa.CheckConstraint("other_fees >= 0", name=op.f("ck_fee_schedule_other_fees")),
        sa.CheckConstraint(
            "published_by IS NULL OR published_by <> submitted_by",
            name=op.f("ck_fee_schedule_four_eyes"),
        ),
        sa.CheckConstraint("registration_fee >= 0", name=op.f("ck_fee_schedule_registration_fee")),
        sa.CheckConstraint("study_year BETWEEN 1 AND 6", name=op.f("ck_fee_schedule_study_year")),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_from IS NULL OR valid_to > valid_from",
            name=op.f("ck_fee_schedule_validity"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["user_account.id"], name=op.f("fk_fee_schedule_created_by")
        ),
        sa.ForeignKeyConstraint(
            ["programme_id"],
            ["programme.id"],
            name=op.f("fk_fee_schedule_programme_id"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["published_by"], ["user_account.id"], name=op.f("fk_fee_schedule_published_by")
        ),
        sa.ForeignKeyConstraint(
            ["speciality_id", "programme_id"],
            ["speciality.id", "speciality.programme_id"],
            name="fk_fee_schedule_speciality",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["submitted_by"], ["user_account.id"], name=op.f("fk_fee_schedule_submitted_by")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fee_schedule")),
    )
    op.create_index("ix_fee_schedule_programme", "fee_schedule", ["programme_id"], unique=False)
    op.create_index("ix_fee_schedule_speciality", "fee_schedule", ["speciality_id"], unique=False)
    op.create_index(
        "ix_fee_schedule_status",
        "fee_schedule",
        ["publication_status", sa.literal_column("updated_at DESC")],
        unique=False,
    )
    op.create_table(
        "admission_subject_requirement",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("admission_condition_id", sa.Uuid(), nullable=False),
        sa.Column("subject_key", sa.Text(), nullable=False),
        sa.Column("subject_name_fr", sa.Text(), nullable=False),
        sa.Column("min_grade", sa.Numeric(precision=4, scale=2), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "subject_key ~ '^[a-z_]{2,40}$'",
            name=op.f("ck_admission_subject_requirement_subject_key"),
        ),
        sa.CheckConstraint(
            "min_grade BETWEEN 0 AND 20", name=op.f("ck_admission_subject_requirement_min_grade")
        ),
        sa.ForeignKeyConstraint(
            ["admission_condition_id"],
            ["admission_condition.id"],
            name=op.f("fk_admission_subject_requirement_admission_condition_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_admission_subject_requirement")),
        sa.UniqueConstraint(
            "admission_condition_id", "subject_key", name="uq_admission_subject_requirement"
        ),
    )
    op.create_table(
        "curriculum_subject",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("curriculum_id", sa.Uuid(), nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column("semester", sa.SmallInteger(), nullable=False),
        sa.Column("teaching_unit_code", sa.Text(), nullable=True),
        sa.Column("teaching_unit_name_fr", sa.Text(), nullable=True),
        sa.Column("coefficient", sa.Numeric(precision=4, scale=2), nullable=False),
        sa.Column("ects_credits", sa.Numeric(precision=4, scale=1), nullable=False),
        sa.Column(
            "hours_lecture",
            sa.Numeric(precision=5, scale=1),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "hours_tutorial",
            sa.Numeric(precision=5, scale=1),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "hours_practical",
            sa.Numeric(precision=5, scale=1),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "hours_total",
            sa.Numeric(precision=6, scale=1),
            sa.Computed("hours_lecture + hours_tutorial + hours_practical", persisted=True),
            nullable=True,
        ),
        sa.Column("is_elective", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("coefficient > 0", name=op.f("ck_curriculum_subject_coefficient")),
        sa.CheckConstraint("ects_credits >= 0", name=op.f("ck_curriculum_subject_ects_credits")),
        sa.CheckConstraint("hours_lecture >= 0", name=op.f("ck_curriculum_subject_hours_lecture")),
        sa.CheckConstraint(
            "hours_practical >= 0", name=op.f("ck_curriculum_subject_hours_practical")
        ),
        sa.CheckConstraint(
            "hours_tutorial >= 0", name=op.f("ck_curriculum_subject_hours_tutorial")
        ),
        sa.CheckConstraint(
            "semester BETWEEN 1 AND 10", name=op.f("ck_curriculum_subject_semester")
        ),
        sa.ForeignKeyConstraint(
            ["curriculum_id"],
            ["curriculum.id"],
            name=op.f("fk_curriculum_subject_curriculum_id"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["subject_id"],
            ["subject.id"],
            name=op.f("fk_curriculum_subject_subject_id"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_curriculum_subject")),
        sa.UniqueConstraint("curriculum_id", "subject_id", name="uq_curriculum_subject"),
        sa.UniqueConstraint("id", "curriculum_id", name="uq_curriculum_subject_id_curriculum"),
    )
    op.create_index(
        "ix_curriculum_subject_subject", "curriculum_subject", ["subject_id"], unique=False
    )
    op.create_table(
        "payment_plan",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("fee_schedule_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("label_fr", sa.Text(), nullable=False),
        sa.Column("installment_count", sa.SmallInteger(), nullable=False),
        sa.Column(
            "discount_rate",
            sa.Numeric(precision=5, scale=2),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("is_default", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("code ~ '^[A-Z0-9_-]{2,32}$'", name=op.f("ck_payment_plan_code")),
        sa.CheckConstraint(
            "discount_rate BETWEEN 0 AND 100", name=op.f("ck_payment_plan_discount_rate")
        ),
        sa.CheckConstraint(
            "installment_count BETWEEN 1 AND 12", name=op.f("ck_payment_plan_installment_count")
        ),
        sa.ForeignKeyConstraint(
            ["fee_schedule_id"],
            ["fee_schedule.id"],
            name=op.f("fk_payment_plan_fee_schedule_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payment_plan")),
        sa.UniqueConstraint("fee_schedule_id", "code", name="uq_payment_plan_code"),
    )
    op.create_index(
        "uq_payment_plan_default",
        "payment_plan",
        ["fee_schedule_id"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )
    op.create_table(
        "payment_installment",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("payment_plan_id", sa.Uuid(), nullable=False),
        sa.Column("installment_no", sa.SmallInteger(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("due_label_fr", sa.Text(), nullable=True),
        sa.Column("amount", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("amount > 0", name=op.f("ck_payment_installment_amount")),
        sa.CheckConstraint(
            "due_date IS NOT NULL OR due_label_fr IS NOT NULL",
            name=op.f("ck_payment_installment_due"),
        ),
        sa.CheckConstraint(
            "installment_no >= 1", name=op.f("ck_payment_installment_installment_no")
        ),
        sa.ForeignKeyConstraint(
            ["payment_plan_id"],
            ["payment_plan.id"],
            name=op.f("fk_payment_installment_payment_plan_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payment_installment")),
        sa.UniqueConstraint("payment_plan_id", "installment_no", name="uq_payment_installment_no"),
    )
    op.create_table(
        "prerequisite",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("curriculum_id", sa.Uuid(), nullable=False),
        sa.Column("curriculum_subject_id", sa.Uuid(), nullable=True),
        sa.Column("required_subject_id", sa.Uuid(), nullable=True),
        sa.Column("required_knowledge_fr", sa.Text(), nullable=True),
        sa.Column("is_mandatory", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "required_subject_id IS NOT NULL OR required_knowledge_fr IS NOT NULL",
            name=op.f("ck_prerequisite_content"),
        ),
        sa.ForeignKeyConstraint(
            ["curriculum_id"],
            ["curriculum.id"],
            name=op.f("fk_prerequisite_curriculum_id"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["curriculum_subject_id", "curriculum_id"],
            ["curriculum_subject.id", "curriculum_subject.curriculum_id"],
            name="fk_prerequisite_target",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["required_subject_id"],
            ["subject.id"],
            name=op.f("fk_prerequisite_required_subject_id"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_prerequisite")),
    )
    op.create_index("ix_prerequisite_curriculum", "prerequisite", ["curriculum_id"], unique=False)
    op.create_index(
        "ix_prerequisite_required", "prerequisite", ["required_subject_id"], unique=False
    )
    op.create_index(
        "ix_prerequisite_target", "prerequisite", ["curriculum_subject_id"], unique=False
    )

    # --- SQL brut : triggers, journal d'audit, garde des versions, droits -------------------
    _updated_at_triggers(UPDATED_AT_TABLES)
    op.execute(AUDIT_FUNCTION)
    for t in CATALOGUE_TABLES:
        op.execute(
            f"CREATE TRIGGER trg_{t}_audit AFTER INSERT OR UPDATE OR DELETE ON {t} "
            "FOR EACH ROW EXECUTE FUNCTION audit_catalogue()"
        )
    op.execute(GUARD_FUNCTION)
    for t in VERSIONED_TABLES:
        op.execute(
            f"CREATE TRIGGER trg_{t}_guard_published BEFORE UPDATE OR DELETE ON {t} "
            "FOR EACH ROW EXECUTE FUNCTION guard_published_version()"
        )
    # Journal append-only : le rôle applicatif peut insérer (via le trigger) et lire, rien d'autre.
    _if_role(
        "smartcampus_app",
        "REVOKE UPDATE, DELETE, TRUNCATE ON catalogue_audit_log FROM smartcampus_app",
    )


def downgrade() -> None:

    _drop_triggers(VERSIONED_TABLES, "guard_published")
    _drop_triggers(CATALOGUE_TABLES, "audit")
    _drop_triggers(UPDATED_AT_TABLES, "updated_at")
    op.execute("DROP FUNCTION IF EXISTS guard_published_version()")
    op.execute("DROP FUNCTION IF EXISTS audit_catalogue()")
    op.drop_index("ix_prerequisite_target", table_name="prerequisite")
    op.drop_index("ix_prerequisite_required", table_name="prerequisite")
    op.drop_index("ix_prerequisite_curriculum", table_name="prerequisite")
    op.drop_table("prerequisite")
    op.drop_table("payment_installment")
    op.drop_index(
        "uq_payment_plan_default", table_name="payment_plan", postgresql_where=sa.text("is_default")
    )
    op.drop_table("payment_plan")
    op.drop_index("ix_curriculum_subject_subject", table_name="curriculum_subject")
    op.drop_table("curriculum_subject")
    op.drop_table("admission_subject_requirement")
    op.drop_index("ix_fee_schedule_status", table_name="fee_schedule")
    op.drop_index("ix_fee_schedule_speciality", table_name="fee_schedule")
    op.drop_index("ix_fee_schedule_programme", table_name="fee_schedule")
    op.drop_table("fee_schedule")
    op.drop_index("ix_curriculum_status", table_name="curriculum")
    op.drop_index("ix_curriculum_speciality", table_name="curriculum")
    op.drop_index("ix_curriculum_programme", table_name="curriculum")
    op.drop_table("curriculum")
    op.drop_index("ix_bridge_target", table_name="bridge")
    op.drop_index("ix_bridge_source", table_name="bridge")
    op.drop_table("bridge")
    op.drop_index("ix_admission_condition_status", table_name="admission_condition")
    op.drop_index("ix_admission_condition_speciality", table_name="admission_condition")
    op.drop_index(
        "ix_admission_condition_sections", table_name="admission_condition", postgresql_using="gin"
    )
    op.drop_index("ix_admission_condition_programme", table_name="admission_condition")
    op.drop_table("admission_condition")
    op.drop_index(
        "ix_user_role_role_active",
        table_name="user_role",
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.drop_table("user_role")
    op.drop_index(
        "ix_speciality_official",
        table_name="speciality",
        postgresql_using="gist",
        postgresql_where=sa.text("publication_status = 'published'"),
    )
    op.drop_index("ix_speciality_fts", table_name="speciality", postgresql_using="gin")
    op.drop_table("speciality")
    op.drop_index("ix_subject_institution", table_name="subject")
    op.drop_index("ix_subject_fts", table_name="subject", postgresql_using="gin")
    op.drop_table("subject")
    op.drop_index(op.f("ix_role_institution_id"), table_name="role")
    op.drop_table("role")
    op.drop_index(
        "ix_programme_official",
        table_name="programme",
        postgresql_using="gist",
        postgresql_where=sa.text("publication_status = 'published'"),
    )
    op.drop_index("ix_programme_institution", table_name="programme")
    op.drop_index("ix_programme_fts", table_name="programme", postgresql_using="gin")
    op.drop_table("programme")
    op.drop_table("institution")
    op.drop_index("ix_catalogue_audit_log_row", table_name="catalogue_audit_log")
    op.drop_index("ix_catalogue_audit_log_actor", table_name="catalogue_audit_log")
    op.drop_table("catalogue_audit_log")
    op.drop_table("user_account")
