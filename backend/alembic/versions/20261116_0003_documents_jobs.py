"""Documents officiels, RAG hybride et file de jobs générique (SA-14)

Tables embedding_model, document, document_programme, document_version, job, sync_job,
document_chunk (vector(1024) + HNSW cosinus, tsv 'simple' + GIN). SQL brut : contenu
immuable et version publiée figée, contrôle différé job/sync_job, vues v_searchable_chunk
et v_document_index_state, GRANT SELECT de la seule vue RAG à smartcampus_rag_reader.

Révision : 0003_documents_jobs
Révise : 0002_identite_catalogue
Créée le : 2026-11-16 (SA-17)
"""

from collections.abc import Sequence

import pgvector.sqlalchemy.vector  # noqa: F401  (type VECTOR rendu par l'autogénération)
import sqlalchemy as sa
from alembic import op
from sqlalchemy import Text, Uuid  # noqa: F401  (types rendus par l'autogénération)
from sqlalchemy.dialects import postgresql

revision: str = "0003_documents_jobs"
down_revision: str | Sequence[str] | None = "0002_identite_catalogue"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


UPDATED_AT_TABLES = (
    "embedding_model",
    "job",
    "document",
    "document_programme",
    "document_version",
    "sync_job",
    "document_chunk",
)

# Contenu d'une version immuable (SA-14 §4.3) : un nouveau fichier = une nouvelle version.
IMMUTABLE_FUNCTION = """
CREATE FUNCTION guard_document_version_content() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF (NEW.document_id, NEW.version_number, NEW.content_sha256, NEW.storage_path,
      NEW.mime_type, NEW.size_bytes)
     IS DISTINCT FROM
     (OLD.document_id, OLD.version_number, OLD.content_sha256, OLD.storage_path,
      OLD.mime_type, OLD.size_bytes) THEN
    RAISE EXCEPTION 'Contenu de la version % immuable : déposer une nouvelle version.', OLD.id
          USING ERRCODE = 'check_violation', CONSTRAINT = 'gd_document_version_immutable';
  END IF;
  RETURN NEW;
END $$
"""

# Un job vector_sync doit avoir sa ligne sync_job à la fin de la transaction (SA-14 D14).
SYNC_CHECK_FUNCTION = """
CREATE FUNCTION check_vector_sync_job() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF EXISTS (SELECT 1 FROM job WHERE id = NEW.id AND job_type = 'vector_sync')
     AND NOT EXISTS (SELECT 1 FROM sync_job WHERE job_id = NEW.id) THEN
    RAISE EXCEPTION 'Le job vector_sync % n''a pas de ligne sync_job.', NEW.id
          USING ERRCODE = 'foreign_key_violation', CONSTRAINT = 'ct_job_vector_sync_detail';
  END IF;
  RETURN NULL;
END $$
"""

# RAG : seule surface visible par le rôle smartcampus_rag_reader (SA-14 §6.1, D3).
# Vue normale (pas security_invoker) : elle lit les tables avec les droits du propriétaire.
V_SEARCHABLE_CHUNK = """
CREATE VIEW v_searchable_chunk AS
SELECT c.id AS chunk_id, c.content, c.page_start, c.page_end, c.section_path,
       c.embedding, c.tsv,
       v.id AS document_version_id, v.version_number, v.valid_to, v.language,
       d.id AS document_id, d.code, d.title_fr, d.document_type, d.institution_id
FROM document_chunk c
JOIN document_version v ON v.id = c.document_version_id
JOIN document d          ON d.id = v.document_id
JOIN embedding_model m   ON m.id = c.embedding_model_id AND m.is_active
WHERE v.publication_status = 'published'
  AND v.index_status = 'indexed'
  AND v.validity @> CURRENT_DATE
  AND d.archived_at IS NULL
"""

# Version citable aujourd'hui et état de son index, par document (SA-14 §6.3).
V_DOCUMENT_INDEX_STATE = """
CREATE VIEW v_document_index_state AS
SELECT d.id AS document_id, d.code, d.title_fr,
       v.id AS current_version_id, v.version_number, v.index_status, v.indexed_at,
       lj.status AS last_job_status, lj.last_error
FROM document d
LEFT JOIN document_version v
       ON v.document_id = d.id AND v.publication_status = 'published'
      AND v.validity @> CURRENT_DATE
LEFT JOIN LATERAL (SELECT j.status, j.last_error
                   FROM sync_job s JOIN job j ON j.id = s.job_id
                   WHERE s.document_id = d.id
                   ORDER BY j.created_at DESC LIMIT 1) lj ON true
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
        "embedding_model",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("revision", sa.Text(), nullable=False),
        sa.Column("dimension", sa.Integer(), nullable=False),
        sa.Column("distance", sa.Text(), server_default=sa.text("'cosine'"), nullable=False),
        sa.Column("max_input_tokens", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("false"), nullable=False),
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
            "distance IN ('cosine','l2','inner_product')", name=op.f("ck_embedding_model_distance")
        ),
        sa.CheckConstraint("dimension > 0", name=op.f("ck_embedding_model_dimension")),
        sa.CheckConstraint(
            "max_input_tokens > 0", name=op.f("ck_embedding_model_max_input_tokens")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_embedding_model")),
        sa.UniqueConstraint("name", "revision", name=op.f("uq_embedding_model_name_revision")),
    )
    op.create_index(
        "uq_embedding_model_active",
        "embedding_model",
        ["is_active"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )
    op.create_table(
        "job",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("job_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'queued'"), nullable=False),
        sa.Column("priority", sa.SmallInteger(), server_default=sa.text("100"), nullable=False),
        sa.Column(
            "run_after", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default=sa.text("5"), nullable=False),
        sa.Column("locked_by", sa.Text(), nullable=True),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dedup_key", sa.Text(), nullable=True),
        sa.Column("concurrency_key", sa.Text(), nullable=True),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("result", postgresql.JSONB(astext_type=Text()), nullable=True),
        sa.Column("last_error_code", sa.Text(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("requested_by", sa.Uuid(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
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
            "job_type IN ('vector_sync','email','follow_up','equivalence_analysis','purge')",
            name=op.f("ck_job_job_type"),
        ),
        sa.CheckConstraint(
            "status IN ('queued','running','retry_wait','succeeded','skipped','failed','cancelled')",
            name=op.f("ck_job_status"),
        ),
        sa.CheckConstraint("attempts >= 0", name=op.f("ck_job_attempts")),
        sa.CheckConstraint("max_attempts >= 1", name=op.f("ck_job_max_attempts")),
        sa.ForeignKeyConstraint(
            ["requested_by"], ["user_account.id"], name=op.f("fk_job_requested_by")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job")),
    )
    op.create_index(op.f("ix_job_job_type_status"), "job", ["job_type", "status"], unique=False)
    op.create_index(
        "ix_job_ready",
        "job",
        ["priority", "run_after"],
        unique=False,
        postgresql_where=sa.text("status IN ('queued','retry_wait')"),
    )
    op.create_index(op.f("ix_job_requested_by"), "job", ["requested_by"], unique=False)
    op.create_index(
        "ix_job_running_concurrency",
        "job",
        ["concurrency_key"],
        unique=False,
        postgresql_where=sa.text("status = 'running'"),
    )
    op.create_index(
        "uq_job_dedup_active",
        "job",
        ["dedup_key"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued','running','retry_wait')"),
    )
    op.create_table(
        "document",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("document_type", sa.Text(), nullable=False),
        sa.Column("title_fr", sa.Text(), nullable=False),
        sa.Column("title_ar", sa.Text(), nullable=True),
        sa.Column("description_fr", sa.Text(), nullable=True),
        sa.Column("institution_id", sa.Uuid(), nullable=True),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("default_language", sa.Text(), server_default=sa.text("'fr'"), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
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
        sa.CheckConstraint("code ~ '^[A-Z0-9_-]{2,32}$'", name=op.f("ck_document_code")),
        sa.CheckConstraint(
            "default_language IN ('fr','aeb_arab','aeb_latn','ar','en','mixed','unknown')",
            name=op.f("ck_document_default_language"),
        ),
        sa.CheckConstraint(
            "document_type IN ('official_guide','regulation','brochure','faq')",
            name=op.f("ck_document_document_type"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["user_account.id"], name=op.f("fk_document_created_by")
        ),
        sa.ForeignKeyConstraint(
            ["institution_id"],
            ["institution.id"],
            name=op.f("fk_document_institution_id"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"], ["user_account.id"], name=op.f("fk_document_owner_user_id")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document")),
        sa.UniqueConstraint("code", name=op.f("uq_document_code")),
    )
    op.create_index(
        op.f("ix_document_institution_id"), "document", ["institution_id"], unique=False
    )
    op.create_index(op.f("ix_document_owner_user_id"), "document", ["owner_user_id"], unique=False)
    op.create_table(
        "document_programme",
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("programme_id", sa.Uuid(), nullable=False),
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
            ["document_id"],
            ["document.id"],
            name=op.f("fk_document_programme_document_id"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["programme_id"],
            ["programme.id"],
            name=op.f("fk_document_programme_programme_id"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("document_id", "programme_id", name=op.f("pk_document_programme")),
    )
    op.create_index(
        op.f("ix_document_programme_programme_id"),
        "document_programme",
        ["programme_id"],
        unique=False,
    )
    op.create_table(
        "document_version",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.CHAR(length=64), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("original_filename", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("language", sa.Text(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("change_note", sa.Text(), nullable=True),
        sa.Column("review_comment", sa.Text(), nullable=True),
        sa.Column(
            "index_status", sa.Text(), server_default=sa.text("'not_indexed'"), nullable=False
        ),
        sa.Column("indexed_model_id", sa.Uuid(), nullable=True),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
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
            (sa.column("document_id"), "="),
            (sa.column("validity"), "&&"),
            where=sa.text("publication_status = 'published'"),
            using="gist",
            name=op.f("ex_document_version_validity"),
        ),
        sa.CheckConstraint(
            "content_sha256 ~ '^[0-9a-f]{64}$'", name=op.f("ck_document_version_content_sha256")
        ),
        sa.CheckConstraint(
            "index_status IN ('not_indexed','indexing','indexed','failed','removed')",
            name=op.f("ck_document_version_index_status"),
        ),
        sa.CheckConstraint(
            "language IN ('fr','aeb_arab','aeb_latn','ar','en','mixed','unknown')",
            name=op.f("ck_document_version_language"),
        ),
        sa.CheckConstraint(
            "mime_type IN ('application/pdf','text/html','text/markdown','text/plain','application/vnd.openxmlformats-officedocument.wordprocessingml.document')",
            name=op.f("ck_document_version_mime_type"),
        ),
        sa.CheckConstraint(
            "publication_status <> 'published' OR (published_by IS NOT NULL AND published_at IS NOT NULL)",
            name=op.f("ck_document_version_published"),
        ),
        sa.CheckConstraint(
            "publication_status IN ('draft','pending_review','published','archived')",
            name=op.f("ck_document_version_publication_status"),
        ),
        sa.CheckConstraint(
            "publication_status NOT IN ('pending_review','published') OR (valid_from IS NOT NULL AND submitted_by IS NOT NULL AND submitted_at IS NOT NULL)",
            name=op.f("ck_document_version_submitted"),
        ),
        sa.CheckConstraint("page_count > 0", name=op.f("ck_document_version_page_count")),
        sa.CheckConstraint(
            "published_by IS NULL OR published_by <> submitted_by",
            name=op.f("ck_document_version_four_eyes"),
        ),
        sa.CheckConstraint(
            "size_bytes > 0 AND size_bytes <= 52428800", name=op.f("ck_document_version_size_bytes")
        ),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_from IS NULL OR valid_to > valid_from",
            name=op.f("ck_document_version_validity"),
        ),
        sa.CheckConstraint("version_number > 0", name=op.f("ck_document_version_version_number")),
        sa.ForeignKeyConstraint(
            ["created_by"], ["user_account.id"], name=op.f("fk_document_version_created_by")
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["document.id"],
            name=op.f("fk_document_version_document_id"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["indexed_model_id"],
            ["embedding_model.id"],
            name=op.f("fk_document_version_indexed_model_id"),
        ),
        sa.ForeignKeyConstraint(
            ["published_by"], ["user_account.id"], name=op.f("fk_document_version_published_by")
        ),
        sa.ForeignKeyConstraint(
            ["submitted_by"], ["user_account.id"], name=op.f("fk_document_version_submitted_by")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_version")),
        sa.UniqueConstraint(
            "document_id",
            "content_sha256",
            name=op.f("uq_document_version_document_id_content_sha256"),
        ),
        sa.UniqueConstraint(
            "document_id",
            "version_number",
            name=op.f("uq_document_version_document_id_version_number"),
        ),
        sa.UniqueConstraint("storage_path", name=op.f("uq_document_version_storage_path")),
    )
    op.create_index(
        op.f("ix_document_version_indexed_model_id"),
        "document_version",
        ["indexed_model_id"],
        unique=False,
    )
    op.create_index(
        "ix_document_version_lookup",
        "document_version",
        ["document_id", "publication_status", "valid_from"],
        unique=False,
    )
    op.create_index(
        "ix_document_version_to_review",
        "document_version",
        ["submitted_at"],
        unique=False,
        postgresql_where=sa.text("publication_status = 'pending_review'"),
    )
    op.create_table(
        "sync_job",
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("document_version_id", sa.Uuid(), nullable=False),
        sa.Column("operation", sa.Text(), nullable=False),
        sa.Column("trigger", sa.Text(), nullable=False),
        sa.Column("embedding_model_id", sa.Uuid(), nullable=False),
        sa.Column("chunker_version", sa.Text(), nullable=False),
        sa.Column("chunks_written", sa.Integer(), nullable=True),
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
        sa.CheckConstraint("operation IN ('upsert','delete')", name=op.f("ck_sync_job_operation")),
        sa.CheckConstraint(
            "trigger IN ('version_created','archived','expired','model_changed','manual_retry')",
            name=op.f("ck_sync_job_trigger"),
        ),
        sa.CheckConstraint("chunks_written >= 0", name=op.f("ck_sync_job_chunks_written")),
        sa.ForeignKeyConstraint(
            ["document_id"], ["document.id"], name=op.f("fk_sync_job_document_id")
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id"],
            ["document_version.id"],
            name=op.f("fk_sync_job_document_version_id"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["embedding_model_id"],
            ["embedding_model.id"],
            name=op.f("fk_sync_job_embedding_model_id"),
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["job.id"], name=op.f("fk_sync_job_job_id"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("job_id", name=op.f("pk_sync_job")),
    )
    op.create_index(op.f("ix_sync_job_document_id"), "sync_job", ["document_id"], unique=False)
    op.create_index(
        op.f("ix_sync_job_document_version_id"), "sync_job", ["document_version_id"], unique=False
    )
    op.create_index(
        op.f("ix_sync_job_embedding_model_id"), "sync_job", ["embedding_model_id"], unique=False
    )
    op.create_table(
        "document_chunk",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("document_version_id", sa.Uuid(), nullable=False),
        sa.Column("embedding_model_id", sa.Uuid(), nullable=False),
        sa.Column("sync_job_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("char_start", sa.Integer(), nullable=False),
        sa.Column("char_end", sa.Integer(), nullable=False),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
        sa.Column("section_path", sa.Text(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("embedding", pgvector.sqlalchemy.vector.VECTOR(dim=1024), nullable=False),
        sa.Column(
            "tsv",
            postgresql.TSVECTOR(),
            sa.Computed(
                "to_tsvector('simple'::regconfig, coalesce(section_path, '') || ' ' || content)",
                persisted=True,
            ),
            nullable=True,
        ),
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
            "char_start >= 0 AND char_end > char_start", name=op.f("ck_document_chunk_char_range")
        ),
        sa.CheckConstraint("chunk_index >= 0", name=op.f("ck_document_chunk_chunk_index")),
        sa.CheckConstraint(
            "page_end IS NULL OR page_start IS NULL OR page_end >= page_start",
            name=op.f("ck_document_chunk_page_range"),
        ),
        sa.CheckConstraint("token_count > 0", name=op.f("ck_document_chunk_token_count")),
        sa.ForeignKeyConstraint(
            ["document_version_id"],
            ["document_version.id"],
            name=op.f("fk_document_chunk_document_version_id"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["embedding_model_id"],
            ["embedding_model.id"],
            name=op.f("fk_document_chunk_embedding_model_id"),
        ),
        sa.ForeignKeyConstraint(
            ["sync_job_id"], ["sync_job.job_id"], name=op.f("fk_document_chunk_sync_job_id")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_chunk")),
        sa.UniqueConstraint(
            "document_version_id",
            "embedding_model_id",
            "chunk_index",
            name="uq_document_chunk_version_model_index",
        ),
    )
    op.create_index(
        "ix_document_chunk_embedding",
        "document_chunk",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index(
        op.f("ix_document_chunk_embedding_model_id"),
        "document_chunk",
        ["embedding_model_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_document_chunk_sync_job_id"), "document_chunk", ["sync_job_id"], unique=False
    )
    op.create_index(
        "ix_document_chunk_tsv", "document_chunk", ["tsv"], unique=False, postgresql_using="gin"
    )
    op.create_index(
        "ix_document_chunk_version_model",
        "document_chunk",
        ["document_version_id", "embedding_model_id"],
        unique=False,
    )

    # --- SQL brut : triggers, vues, droits ------------------------------------------------------
    _updated_at_triggers(UPDATED_AT_TABLES)
    op.execute(IMMUTABLE_FUNCTION)
    op.execute(
        "CREATE TRIGGER trg_document_version_immutable BEFORE UPDATE ON document_version "
        "FOR EACH ROW EXECUTE FUNCTION guard_document_version_content()"
    )
    # Version publiée figée ; le worker peut encore écrire l'état d'index (SA-14 §5.3).
    op.execute(
        "CREATE TRIGGER trg_document_version_guard_published BEFORE UPDATE OR DELETE "
        "ON document_version FOR EACH ROW EXECUTE FUNCTION "
        "guard_published_version('index_status', 'indexed_model_id', 'indexed_at')"
    )
    op.execute(SYNC_CHECK_FUNCTION)
    op.execute(
        "CREATE CONSTRAINT TRIGGER ct_job_vector_sync_detail AFTER INSERT OR UPDATE OF job_type "
        "ON job DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION check_vector_sync_job()"
    )
    op.execute(V_SEARCHABLE_CHUNK)
    op.execute(V_DOCUMENT_INDEX_STATE)
    # SA-16 : le rôle RAG ne lit QUE cette vue (aucun autre droit).
    _if_role(
        "smartcampus_rag_reader", "GRANT SELECT ON v_searchable_chunk TO smartcampus_rag_reader"
    )


def downgrade() -> None:

    op.execute("DROP VIEW IF EXISTS v_document_index_state")
    op.execute("DROP VIEW IF EXISTS v_searchable_chunk")
    op.execute("DROP TRIGGER IF EXISTS ct_job_vector_sync_detail ON job")
    op.execute("DROP FUNCTION IF EXISTS check_vector_sync_job()")
    op.execute("DROP TRIGGER IF EXISTS trg_document_version_guard_published ON document_version")
    op.execute("DROP TRIGGER IF EXISTS trg_document_version_immutable ON document_version")
    op.execute("DROP FUNCTION IF EXISTS guard_document_version_content()")
    _drop_triggers(UPDATED_AT_TABLES, "updated_at")
    op.drop_index("ix_document_chunk_version_model", table_name="document_chunk")
    op.drop_index("ix_document_chunk_tsv", table_name="document_chunk", postgresql_using="gin")
    op.drop_index(op.f("ix_document_chunk_sync_job_id"), table_name="document_chunk")
    op.drop_index(op.f("ix_document_chunk_embedding_model_id"), table_name="document_chunk")
    op.drop_index(
        "ix_document_chunk_embedding",
        table_name="document_chunk",
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.drop_table("document_chunk")
    op.drop_index(op.f("ix_sync_job_embedding_model_id"), table_name="sync_job")
    op.drop_index(op.f("ix_sync_job_document_version_id"), table_name="sync_job")
    op.drop_index(op.f("ix_sync_job_document_id"), table_name="sync_job")
    op.drop_table("sync_job")
    op.drop_index(
        "ix_document_version_to_review",
        table_name="document_version",
        postgresql_where=sa.text("publication_status = 'pending_review'"),
    )
    op.drop_index("ix_document_version_lookup", table_name="document_version")
    op.drop_index(op.f("ix_document_version_indexed_model_id"), table_name="document_version")
    op.drop_table("document_version")
    op.drop_index(op.f("ix_document_programme_programme_id"), table_name="document_programme")
    op.drop_table("document_programme")
    op.drop_index(op.f("ix_document_owner_user_id"), table_name="document")
    op.drop_index(op.f("ix_document_institution_id"), table_name="document")
    op.drop_table("document")
    op.drop_index(
        "uq_job_dedup_active",
        table_name="job",
        postgresql_where=sa.text("status IN ('queued','running','retry_wait')"),
    )
    op.drop_index(
        "ix_job_running_concurrency",
        table_name="job",
        postgresql_where=sa.text("status = 'running'"),
    )
    op.drop_index(op.f("ix_job_requested_by"), table_name="job")
    op.drop_index(
        "ix_job_ready",
        table_name="job",
        postgresql_where=sa.text("status IN ('queued','retry_wait')"),
    )
    op.drop_index(op.f("ix_job_job_type_status"), table_name="job")
    op.drop_table("job")
    op.drop_index(
        "uq_embedding_model_active",
        table_name="embedding_model",
        postgresql_where=sa.text("is_active"),
    )
    op.drop_table("embedding_model")
