"""Visiteurs, conversations, dossiers candidats, processus et journaux (SA-13, SA-14 §4.7)

Tables de SA-13 (sessions, conversations, messages, profil, recommandations,
pré-inscriptions, QCM, équivalences, rendez-vous, entretiens, relances, notifications,
journaux, lacunes, idempotence) + candidate_attachment (SA-14). SQL brut : triggers
set_updated_at, vue v_pending_validation, droits append-only (status_history,
agent_action_log, consent).

Révision : 0004_candidatures
Révise : 0003_documents_jobs
Créée le : 2026-11-16 (SA-17)
"""

from collections.abc import Sequence

import pgvector.sqlalchemy.vector  # noqa: F401  (type VECTOR rendu par l'autogénération)
import sqlalchemy as sa
from alembic import op
from sqlalchemy import Text, Uuid  # noqa: F401  (types rendus par l'autogénération)
from sqlalchemy.dialects import postgresql

revision: str = "0004_candidatures"
down_revision: str | Sequence[str] | None = "0003_documents_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


UPDATED_AT_TABLES = (
    "candidate_profile",
    "visitor_session",
    "appointment_slot",
    "conversation",
    "idempotency_key",
    "knowledge_gap",
    "mcq_question",
    "recommendation",
    "conversation_attachment",
    "message",
    "recommendation_item",
    "knowledge_gap_question",
    "message_feedback",
    "preregistration",
    "appointment",
    "equivalence_request",
    "follow_up",
    "mcq_attempt",
    "candidate_attachment",
    "equivalence_item",
    "interview",
    "mcq_attempt_item",
    "notification",
    "academic_record",
    "academic_record_subject",
)
#: Journaux append-only : ni UPDATE ni DELETE pour le rôle applicatif (SA-16, SA-13).
APPEND_ONLY_TABLES = ("status_history", "agent_action_log", "consent")

# File des validations humaines en attente (SA-13 Q10, D4).
V_PENDING_VALIDATION = """
CREATE VIEW v_pending_validation AS
  SELECT 'recommendation' AS kind, id AS entity_id, created_at
    FROM recommendation WHERE status = 'pending_validation'
  UNION ALL
  SELECT 'equivalence_request', id, created_at
    FROM equivalence_request WHERE status = 'under_review'
  UNION ALL
  SELECT 'preregistration', id, created_at
    FROM preregistration WHERE status = 'decision_pending'
  UNION ALL
  SELECT 'mcq_question', id, created_at
    FROM mcq_question WHERE status = 'draft'
  UNION ALL
  SELECT 'interview', id, created_at
    FROM interview WHERE status = 'scheduled'
                     AND appointment_id IN (SELECT id FROM appointment
                                            WHERE status = 'completed')
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
        "candidate_profile",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_type", sa.Text(), nullable=False),
        sa.Column("birth_date", sa.Date(), nullable=True),
        sa.Column("city", sa.Text(), nullable=True),
        sa.Column(
            "interests",
            postgresql.JSONB(astext_type=Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("goals", sa.Text(), nullable=True),
        sa.Column(
            "constraints",
            postgresql.JSONB(astext_type=Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "profile_status", sa.Text(), server_default=sa.text("'ai_draft'"), nullable=False
        ),
        sa.Column(
            "field_sources",
            postgresql.JSONB(astext_type=Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
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
            "candidate_type IN ('new_bachelor','transfer','other')",
            name=op.f("ck_candidate_profile_candidate_type"),
        ),
        sa.CheckConstraint(
            "profile_status IN ('ai_draft','confirmed')",
            name=op.f("ck_candidate_profile_profile_status"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["user_account.id"], name=op.f("fk_candidate_profile_user_id")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_candidate_profile")),
        sa.UniqueConstraint("user_id", name=op.f("uq_candidate_profile_user_id")),
    )
    op.create_table(
        "status_history",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("from_status", sa.Text(), nullable=True),
        sa.Column("to_status", sa.Text(), nullable=False),
        sa.Column("actor_type", sa.Text(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("requires_human", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "changed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "NOT requires_human OR (actor_type = 'staff' AND actor_user_id IS NOT NULL)",
            name=op.f("ck_status_history_human_actor"),
        ),
        sa.CheckConstraint(
            "actor_type IN ('visitor','candidate','staff','ai_agent','system')",
            name=op.f("ck_status_history_actor_type"),
        ),
        sa.CheckConstraint(
            "entity_type IN ('preregistration','equivalence_request','equivalence_item','appointment','appointment_slot','interview','recommendation','mcq_attempt','mcq_question','visitor_session','conversation','conversation_attachment','user_account','follow_up','knowledge_gap','candidate_attachment','document_version','institution','programme','speciality','curriculum','admission_condition','fee_schedule','bridge')",
            name=op.f("ck_status_history_entity_type"),
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"], ["user_account.id"], name=op.f("fk_status_history_actor_user_id")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_status_history")),
    )
    op.create_index(
        op.f("ix_status_history_actor_user_id"), "status_history", ["actor_user_id"], unique=False
    )
    op.create_index(
        op.f("ix_status_history_entity_type_entity_id_changed_at"),
        "status_history",
        ["entity_type", "entity_id", "changed_at"],
        unique=False,
    )
    op.create_table(
        "visitor_session",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'active'"), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("idle_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("hard_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("message_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("audio_seconds", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("llm_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("quota_window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("client_fingerprint_hash", sa.LargeBinary(), nullable=True),
        sa.Column("detected_language", sa.Text(), nullable=True),
        sa.Column("attached_user_id", sa.Uuid(), nullable=True),
        sa.Column("attached_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("purged_at", sa.DateTime(timezone=True), nullable=True),
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
            "(status = 'attached') = (attached_user_id IS NOT NULL)",
            name=op.f("ck_visitor_session_attached"),
        ),
        sa.CheckConstraint(
            "detected_language IS NULL OR detected_language IN ('fr','aeb_arab','aeb_latn','ar','en','mixed','unknown')",
            name=op.f("ck_visitor_session_detected_language"),
        ),
        sa.CheckConstraint(
            "status IN ('active','attached','expired','purged')",
            name=op.f("ck_visitor_session_status"),
        ),
        sa.CheckConstraint("audio_seconds >= 0", name=op.f("ck_visitor_session_audio_seconds")),
        sa.CheckConstraint(
            "hard_expires_at > created_at", name=op.f("ck_visitor_session_hard_expiry")
        ),
        sa.CheckConstraint("llm_tokens >= 0", name=op.f("ck_visitor_session_llm_tokens")),
        sa.CheckConstraint("message_count >= 0", name=op.f("ck_visitor_session_message_count")),
        sa.ForeignKeyConstraint(
            ["attached_user_id"],
            ["user_account.id"],
            name=op.f("fk_visitor_session_attached_user_id"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_visitor_session")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_visitor_session_token_hash")),
    )
    op.create_index(
        op.f("ix_visitor_session_attached_user_id"),
        "visitor_session",
        ["attached_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_visitor_session_status_idle_expires_at"),
        "visitor_session",
        ["status", "idle_expires_at"],
        unique=False,
    )
    op.create_table(
        "appointment_slot",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("institution_id", sa.Uuid(), nullable=False),
        sa.Column("appointment_type", sa.Text(), nullable=False),
        sa.Column("staff_user_id", sa.Uuid(), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("location", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'open'"), nullable=False),
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
        postgresql.ExcludeConstraint(
            (sa.column("staff_user_id"), "="),
            (sa.text("tstzrange(starts_at, ends_at)"), "&&"),
            where=sa.text("status <> 'cancelled'"),
            using="gist",
            name=op.f("ex_appointment_slot_staff_overlap"),
        ),
        sa.CheckConstraint(
            "appointment_type IN ('interview','enrolment','advisory')",
            name=op.f("ck_appointment_slot_appointment_type"),
        ),
        sa.CheckConstraint("mode IN ('onsite','online')", name=op.f("ck_appointment_slot_mode")),
        sa.CheckConstraint(
            "status IN ('open','closed','cancelled')", name=op.f("ck_appointment_slot_status")
        ),
        sa.CheckConstraint("ends_at > starts_at", name=op.f("ck_appointment_slot_period")),
        sa.ForeignKeyConstraint(
            ["created_by"], ["user_account.id"], name=op.f("fk_appointment_slot_created_by")
        ),
        sa.ForeignKeyConstraint(
            ["institution_id"], ["institution.id"], name=op.f("fk_appointment_slot_institution_id")
        ),
        sa.ForeignKeyConstraint(
            ["staff_user_id"], ["user_account.id"], name=op.f("fk_appointment_slot_staff_user_id")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_appointment_slot")),
    )
    op.create_index(
        "ix_appointment_slot_open",
        "appointment_slot",
        ["institution_id", "appointment_type", "starts_at"],
        unique=False,
        postgresql_where=sa.text("status = 'open'"),
    )
    op.create_table(
        "conversation",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("visitor_session_id", sa.Uuid(), nullable=True),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("origin_visitor_session_id", sa.Uuid(), nullable=True),
        sa.Column("channel", sa.Text(), server_default=sa.text("'text'"), nullable=False),
        sa.Column("detected_language", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'open'"), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("summary_model", sa.Text(), nullable=True),
        sa.Column("summary_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("message_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
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
            "channel IN ('text','audio','mixed')", name=op.f("ck_conversation_channel")
        ),
        sa.CheckConstraint(
            "detected_language IS NULL OR detected_language IN ('fr','aeb_arab','aeb_latn','ar','en','mixed','unknown')",
            name=op.f("ck_conversation_detected_language"),
        ),
        sa.CheckConstraint(
            "status IN ('open','closed','archived')", name=op.f("ck_conversation_status")
        ),
        sa.CheckConstraint("message_count >= 0", name=op.f("ck_conversation_message_count")),
        sa.CheckConstraint(
            "num_nonnulls(visitor_session_id, user_id) = 1", name=op.f("ck_conversation_owner")
        ),
        sa.ForeignKeyConstraint(
            ["origin_visitor_session_id"],
            ["visitor_session.id"],
            name=op.f("fk_conversation_origin_visitor_session_id"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["user_account.id"], name=op.f("fk_conversation_user_id")
        ),
        sa.ForeignKeyConstraint(
            ["visitor_session_id"],
            ["visitor_session.id"],
            name=op.f("fk_conversation_visitor_session_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversation")),
    )
    op.create_index(
        op.f("ix_conversation_origin_visitor_session_id"),
        "conversation",
        ["origin_visitor_session_id"],
        unique=False,
    )
    op.create_index(
        "ix_conversation_user_last_message",
        "conversation",
        ["user_id", sa.literal_column("last_message_at DESC")],
        unique=False,
    )
    op.create_index(
        op.f("ix_conversation_visitor_session_id"),
        "conversation",
        ["visitor_session_id"],
        unique=False,
    )
    op.create_table(
        "idempotency_key",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("visitor_session_id", sa.Uuid(), nullable=True),
        sa.Column("idempotency_key", sa.Uuid(), nullable=False),
        sa.Column("method", sa.Text(), nullable=False),
        sa.Column("route", sa.Text(), nullable=False),
        sa.Column("request_hash", sa.LargeBinary(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("response_status", sa.SmallInteger(), nullable=True),
        sa.Column("response_body", postgresql.JSONB(astext_type=Text()), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
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
            "state = 'in_progress' OR response_status BETWEEN 200 AND 499",
            name=op.f("ck_idempotency_key_response"),
        ),
        sa.CheckConstraint(
            "state IN ('in_progress','completed')", name=op.f("ck_idempotency_key_state")
        ),
        sa.CheckConstraint(
            "num_nonnulls(user_id, visitor_session_id) = 1", name=op.f("ck_idempotency_key_caller")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user_account.id"],
            name=op.f("fk_idempotency_key_user_id"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["visitor_session_id"],
            ["visitor_session.id"],
            name=op.f("fk_idempotency_key_visitor_session_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_idempotency_key")),
    )
    op.create_index(
        op.f("ix_idempotency_key_expires_at"), "idempotency_key", ["expires_at"], unique=False
    )
    op.create_index(
        op.f("ix_idempotency_key_user_id"), "idempotency_key", ["user_id"], unique=False
    )
    op.create_index(
        op.f("ix_idempotency_key_visitor_session_id"),
        "idempotency_key",
        ["visitor_session_id"],
        unique=False,
    )
    op.create_index(
        "uq_idempotency_key_caller_key",
        "idempotency_key",
        [sa.literal_column("COALESCE(user_id, visitor_session_id)"), "idempotency_key"],
        unique=True,
    )
    op.create_table(
        "consent",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("visitor_session_id", sa.Uuid(), nullable=True),
        sa.Column("consent_type", sa.Text(), nullable=False),
        sa.Column("granted", sa.Boolean(), nullable=False),
        sa.Column("policy_version", sa.Text(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=True),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "channel IN ('web_form','chat_button','staff_on_behalf')",
            name=op.f("ck_consent_channel"),
        ),
        sa.CheckConstraint(
            "consent_type IN ('terms_accepted','data_processing','contact_by_email','conversation_link','raw_conversation_access','parent_share')",
            name=op.f("ck_consent_consent_type"),
        ),
        sa.CheckConstraint(
            "num_nonnulls(user_id, visitor_session_id) >= 1", name=op.f("ck_consent_holder")
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversation.id"],
            name=op.f("fk_consent_conversation_id"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user_account.id"], name=op.f("fk_consent_user_id")),
        sa.ForeignKeyConstraint(
            ["visitor_session_id"],
            ["visitor_session.id"],
            name=op.f("fk_consent_visitor_session_id"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_consent")),
    )
    op.create_index(
        op.f("ix_consent_conversation_id"), "consent", ["conversation_id"], unique=False
    )
    op.create_index(
        op.f("ix_consent_user_id_consent_type"),
        "consent",
        ["user_id", "consent_type", sa.literal_column("recorded_at DESC")],
        unique=False,
    )
    op.create_index(
        op.f("ix_consent_visitor_session_id"), "consent", ["visitor_session_id"], unique=False
    )
    op.create_table(
        "knowledge_gap",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("cluster_label", sa.Text(), nullable=False),
        sa.Column("institution_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'open'"), nullable=False),
        sa.Column("question_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "example_questions",
            postgresql.JSONB(astext_type=Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("clustered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_document_id", sa.Uuid(), nullable=True),
        sa.Column("resolution_entity", postgresql.JSONB(astext_type=Text()), nullable=True),
        sa.Column("resolution_comment", sa.Text(), nullable=True),
        sa.Column("resolved_by", sa.Uuid(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
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
            "status IN ('open','in_progress','resolved','dismissed')",
            name=op.f("ck_knowledge_gap_status"),
        ),
        sa.CheckConstraint(
            "status NOT IN ('resolved','dismissed') OR resolved_by IS NOT NULL",
            name=op.f("ck_knowledge_gap_human_resolution"),
        ),
        sa.CheckConstraint("question_count >= 0", name=op.f("ck_knowledge_gap_question_count")),
        sa.ForeignKeyConstraint(
            ["institution_id"], ["institution.id"], name=op.f("fk_knowledge_gap_institution_id")
        ),
        sa.ForeignKeyConstraint(
            ["resolution_document_id"],
            ["document.id"],
            name=op.f("fk_knowledge_gap_resolution_document_id"),
        ),
        sa.ForeignKeyConstraint(
            ["resolved_by"], ["user_account.id"], name=op.f("fk_knowledge_gap_resolved_by")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_knowledge_gap")),
    )
    op.create_index(
        op.f("ix_knowledge_gap_institution_id"), "knowledge_gap", ["institution_id"], unique=False
    )
    op.create_index(
        op.f("ix_knowledge_gap_status"),
        "knowledge_gap",
        ["status", sa.literal_column("last_seen_at DESC")],
        unique=False,
    )
    op.create_table(
        "mcq_question",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("programme_id", sa.Uuid(), nullable=True),
        sa.Column("topic", sa.Text(), nullable=False),
        sa.Column("difficulty", sa.SmallInteger(), nullable=False),
        sa.Column("stem", sa.Text(), nullable=False),
        sa.Column("options", postgresql.JSONB(astext_type=Text()), nullable=False),
        sa.Column("correct_keys", postgresql.ARRAY(Text()), nullable=False),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'draft'"), nullable=False),
        sa.Column("generator_model", sa.Text(), nullable=True),
        sa.Column("validated_by", sa.Uuid(), nullable=True),
        sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
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
            "origin IN ('staff','ai_generated')", name=op.f("ck_mcq_question_origin")
        ),
        sa.CheckConstraint(
            "status = 'draft' OR validated_by IS NOT NULL",
            name=op.f("ck_mcq_question_human_validation"),
        ),
        sa.CheckConstraint(
            "status IN ('draft','validated','retired')", name=op.f("ck_mcq_question_status")
        ),
        sa.CheckConstraint("difficulty BETWEEN 1 AND 5", name=op.f("ck_mcq_question_difficulty")),
        sa.ForeignKeyConstraint(
            ["programme_id"], ["programme.id"], name=op.f("fk_mcq_question_programme_id")
        ),
        sa.ForeignKeyConstraint(
            ["validated_by"], ["user_account.id"], name=op.f("fk_mcq_question_validated_by")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mcq_question")),
    )
    op.create_index(
        "ix_mcq_question_validated",
        "mcq_question",
        ["programme_id", "topic", "difficulty"],
        unique=False,
        postgresql_where=sa.text("status = 'validated'"),
    )
    op.create_table(
        "recommendation",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("candidate_profile_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'draft'"), nullable=False),
        sa.Column("model_name", sa.Text(), nullable=False),
        sa.Column("prompt_version", sa.Text(), nullable=False),
        sa.Column("profile_snapshot", postgresql.JSONB(astext_type=Text()), nullable=False),
        sa.Column("reviewed_by", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_comment", sa.Text(), nullable=True),
        sa.Column("superseded_by", sa.Uuid(), nullable=True),
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
            "status IN ('draft','proposed','pending_validation','confirmed','adjusted','superseded')",
            name=op.f("ck_recommendation_status"),
        ),
        sa.CheckConstraint(
            "status NOT IN ('confirmed','adjusted') OR reviewed_by IS NOT NULL",
            name=op.f("ck_recommendation_human_review"),
        ),
        sa.ForeignKeyConstraint(
            ["candidate_profile_id"],
            ["candidate_profile.id"],
            name=op.f("fk_recommendation_candidate_profile_id"),
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversation.id"],
            name=op.f("fk_recommendation_conversation_id"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by"], ["user_account.id"], name=op.f("fk_recommendation_reviewed_by")
        ),
        sa.ForeignKeyConstraint(
            ["superseded_by"], ["recommendation.id"], name=op.f("fk_recommendation_superseded_by")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_recommendation")),
    )
    op.create_index(
        op.f("ix_recommendation_candidate_profile_id"),
        "recommendation",
        ["candidate_profile_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_recommendation_conversation_id"),
        "recommendation",
        ["conversation_id"],
        unique=False,
    )
    op.create_index(op.f("ix_recommendation_status"), "recommendation", ["status"], unique=False)
    op.create_table(
        "conversation_attachment",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("visitor_session_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'offered'"), nullable=False),
        sa.Column(
            "offered_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("offer_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ownership_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consent_id", sa.Uuid(), nullable=True),
        sa.Column("conversations_moved", sa.Integer(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
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
            "status <> 'attached' OR (consent_id IS NOT NULL AND ownership_checked_at IS NOT NULL)",
            name=op.f("ck_conversation_attachment_attached_proof"),
        ),
        sa.CheckConstraint(
            "status IN ('offered','consented','declined','ownership_failed','attached','expired')",
            name=op.f("ck_conversation_attachment_status"),
        ),
        sa.CheckConstraint(
            "conversations_moved >= 0", name=op.f("ck_conversation_attachment_conversations_moved")
        ),
        sa.ForeignKeyConstraint(
            ["consent_id"], ["consent.id"], name=op.f("fk_conversation_attachment_consent_id")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["user_account.id"], name=op.f("fk_conversation_attachment_user_id")
        ),
        sa.ForeignKeyConstraint(
            ["visitor_session_id"],
            ["visitor_session.id"],
            name=op.f("fk_conversation_attachment_visitor_session_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversation_attachment")),
    )
    op.create_index(
        op.f("ix_conversation_attachment_consent_id"),
        "conversation_attachment",
        ["consent_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_conversation_attachment_user_id"),
        "conversation_attachment",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "uq_conversation_attachment_attached",
        "conversation_attachment",
        ["visitor_session_id"],
        unique=True,
        postgresql_where=sa.text("status = 'attached'"),
    )
    op.create_table(
        "message",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("client_message_id", sa.Uuid(), nullable=True),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("input_modality", sa.Text(), server_default=sa.text("'text'"), nullable=False),
        sa.Column("audio_storage_path", sa.Text(), nullable=True),
        sa.Column("audio_purge_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("audio_duration_ms", sa.Integer(), nullable=True),
        sa.Column("transcript_raw", sa.Text(), nullable=True),
        sa.Column("stt_confidence", sa.REAL(), nullable=True),
        sa.Column("detected_language", sa.Text(), nullable=True),
        sa.Column("reply_language", sa.Text(), nullable=True),
        sa.Column("language_confidence", sa.REAL(), nullable=True),
        sa.Column(
            "sources",
            postgresql.JSONB(astext_type=Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("tool_calls", postgresql.JSONB(astext_type=Text()), nullable=True),
        sa.Column("tool_call_id", sa.Text(), nullable=True),
        sa.Column("tool_name", sa.Text(), nullable=True),
        sa.Column("grounding", sa.Text(), nullable=True),
        sa.Column("knowledge_gap_id", sa.Uuid(), nullable=True),
        sa.Column("finish_reason", sa.Text(), nullable=True),
        sa.Column("model_name", sa.Text(), nullable=True),
        sa.Column("prompt_version", sa.Text(), nullable=True),
        sa.Column("tokens_in", sa.Integer(), nullable=True),
        sa.Column("tokens_out", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
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
            "(role = 'tool') = (tool_call_id IS NOT NULL)", name=op.f("ck_message_tool_call")
        ),
        sa.CheckConstraint(
            "client_message_id IS NULL OR role = 'user'", name=op.f("ck_message_client_message_id")
        ),
        sa.CheckConstraint(
            "detected_language IS NULL OR detected_language IN ('fr','aeb_arab','aeb_latn','ar','en','mixed','unknown')",
            name=op.f("ck_message_detected_language"),
        ),
        sa.CheckConstraint(
            "finish_reason IS NULL OR finish_reason IN ('completed','clarification_requested','fallback_human','fallback_deterministic','length','refused')",
            name=op.f("ck_message_finish_reason"),
        ),
        sa.CheckConstraint(
            "grounding IS DISTINCT FROM 'no_official_source' OR knowledge_gap_id IS NOT NULL",
            name=op.f("ck_message_knowledge_gap"),
        ),
        sa.CheckConstraint(
            "grounding IS NULL OR grounding IN ('grounded','partial','no_official_source','not_applicable')",
            name=op.f("ck_message_grounding"),
        ),
        sa.CheckConstraint(
            "input_modality IN ('text','audio')", name=op.f("ck_message_input_modality")
        ),
        sa.CheckConstraint(
            "reply_language IS NULL OR reply_language IN ('fr','aeb_arab','aeb_latn','ar','en','mixed','unknown')",
            name=op.f("ck_message_reply_language"),
        ),
        sa.CheckConstraint("role IN ('user','assistant','tool')", name=op.f("ck_message_role")),
        sa.CheckConstraint("audio_duration_ms > 0", name=op.f("ck_message_audio_duration_ms")),
        sa.CheckConstraint(
            "language_confidence BETWEEN 0 AND 1", name=op.f("ck_message_language_confidence")
        ),
        sa.CheckConstraint("latency_ms >= 0", name=op.f("ck_message_latency_ms")),
        sa.CheckConstraint(
            "stt_confidence BETWEEN 0 AND 1", name=op.f("ck_message_stt_confidence")
        ),
        sa.CheckConstraint("tokens_in >= 0", name=op.f("ck_message_tokens_in")),
        sa.CheckConstraint("tokens_out >= 0", name=op.f("ck_message_tokens_out")),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversation.id"],
            name=op.f("fk_message_conversation_id"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["knowledge_gap_id"],
            ["knowledge_gap.id"],
            name=op.f("fk_message_knowledge_gap_id"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_message")),
        sa.UniqueConstraint(
            "conversation_id",
            "client_message_id",
            name=op.f("uq_message_conversation_id_client_message_id"),
        ),
        sa.UniqueConstraint("conversation_id", "seq", name=op.f("uq_message_conversation_id_seq")),
    )
    op.create_index(
        "ix_message_audio_purge",
        "message",
        ["audio_purge_at"],
        unique=False,
        postgresql_where=sa.text("audio_storage_path IS NOT NULL"),
    )
    op.create_index(
        op.f("ix_message_knowledge_gap_id"),
        "message",
        ["knowledge_gap_id"],
        unique=False,
        postgresql_where=sa.text("knowledge_gap_id IS NOT NULL"),
    )
    op.create_table(
        "recommendation_item",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("recommendation_id", sa.Uuid(), nullable=False),
        sa.Column("rank", sa.SmallInteger(), nullable=False),
        sa.Column("programme_id", sa.Uuid(), nullable=False),
        sa.Column("speciality_id", sa.Uuid(), nullable=True),
        sa.Column("eligibility", postgresql.JSONB(astext_type=Text()), nullable=False),
        sa.Column("total_duration_years", sa.SmallInteger(), nullable=True),
        sa.Column("total_cost", sa.Numeric(precision=12, scale=3), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column(
            "sources",
            postgresql.JSONB(astext_type=Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("staff_decision", sa.Text(), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("chosen_by_candidate_at", sa.DateTime(timezone=True), nullable=True),
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
            "staff_decision IN ('pending','kept','removed','added_by_staff')",
            name=op.f("ck_recommendation_item_staff_decision"),
        ),
        sa.CheckConstraint("rank BETWEEN 1 AND 5", name=op.f("ck_recommendation_item_rank")),
        sa.ForeignKeyConstraint(
            ["programme_id"], ["programme.id"], name=op.f("fk_recommendation_item_programme_id")
        ),
        sa.ForeignKeyConstraint(
            ["recommendation_id"],
            ["recommendation.id"],
            name=op.f("fk_recommendation_item_recommendation_id"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["speciality_id"], ["speciality.id"], name=op.f("fk_recommendation_item_speciality_id")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_recommendation_item")),
        sa.UniqueConstraint(
            "recommendation_id", "rank", name=op.f("uq_recommendation_item_recommendation_id_rank")
        ),
    )
    op.create_index(
        op.f("ix_recommendation_item_programme_id"),
        "recommendation_item",
        ["programme_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_recommendation_item_speciality_id"),
        "recommendation_item",
        ["speciality_id"],
        unique=False,
    )
    op.create_table(
        "agent_action_log",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=True),
        sa.Column("message_id", sa.Uuid(), nullable=True),
        sa.Column("request_id", sa.Text(), nullable=True),
        sa.Column("agent", sa.Text(), nullable=False),
        sa.Column("step_type", sa.Text(), nullable=False),
        sa.Column("tool_name", sa.Text(), nullable=True),
        sa.Column("tool_kind", sa.Text(), nullable=True),
        sa.Column("call_id", sa.Text(), nullable=True),
        sa.Column("arguments", postgresql.JSONB(astext_type=Text()), nullable=True),
        sa.Column("result", postgresql.JSONB(astext_type=Text()), nullable=True),
        sa.Column("result_summary", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("model_name", sa.Text(), nullable=True),
        sa.Column("prompt_version", sa.Text(), nullable=True),
        sa.Column("tokens_in", sa.Integer(), nullable=True),
        sa.Column("tokens_out", sa.Integer(), nullable=True),
        sa.Column("cost_estimate_usd", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column("actor_type", sa.Text(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("visitor_session_id", sa.Uuid(), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "actor_type IN ('visitor','candidate','staff','ai_agent','system')",
            name=op.f("ck_agent_action_log_actor_type"),
        ),
        sa.CheckConstraint(
            "status IN ('succeeded','failed','timeout','refused')",
            name=op.f("ck_agent_action_log_status"),
        ),
        sa.CheckConstraint(
            "step_type IN ('llm_call','tool_call','retrieval','stt','guardrail','output_check')",
            name=op.f("ck_agent_action_log_step_type"),
        ),
        sa.CheckConstraint(
            "tool_kind IS NULL OR tool_kind IN ('deterministic','retrieval','ai')",
            name=op.f("ck_agent_action_log_tool_kind"),
        ),
        sa.CheckConstraint(
            "cost_estimate_usd >= 0", name=op.f("ck_agent_action_log_cost_estimate_usd")
        ),
        sa.CheckConstraint("duration_ms >= 0", name=op.f("ck_agent_action_log_duration_ms")),
        sa.CheckConstraint("tokens_in >= 0", name=op.f("ck_agent_action_log_tokens_in")),
        sa.CheckConstraint("tokens_out >= 0", name=op.f("ck_agent_action_log_tokens_out")),
        sa.ForeignKeyConstraint(
            ["actor_user_id"], ["user_account.id"], name=op.f("fk_agent_action_log_actor_user_id")
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversation.id"],
            name=op.f("fk_agent_action_log_conversation_id"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["message.id"],
            name=op.f("fk_agent_action_log_message_id"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["visitor_session_id"],
            ["visitor_session.id"],
            name=op.f("fk_agent_action_log_visitor_session_id"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_action_log")),
    )
    op.create_index(
        op.f("ix_agent_action_log_conversation_id_occurred_at"),
        "agent_action_log",
        ["conversation_id", "occurred_at"],
        unique=False,
    )
    op.create_index(
        "ix_agent_action_log_errors",
        "agent_action_log",
        ["occurred_at"],
        unique=False,
        postgresql_where=sa.text("status <> 'succeeded'"),
    )
    op.create_index(
        op.f("ix_agent_action_log_message_id"), "agent_action_log", ["message_id"], unique=False
    )
    op.create_index(
        op.f("ix_agent_action_log_tool_name_occurred_at"),
        "agent_action_log",
        ["tool_name", "occurred_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_agent_action_log_visitor_session_id"),
        "agent_action_log",
        ["visitor_session_id"],
        unique=False,
    )
    op.create_table(
        "knowledge_gap_question",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("knowledge_gap_id", sa.Uuid(), nullable=False),
        sa.Column("message_id", sa.Uuid(), nullable=True),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("language", sa.Text(), nullable=True),
        sa.Column("grounding", sa.Text(), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.vector.VECTOR(dim=1024), nullable=True),
        sa.Column("asked_at", sa.DateTime(timezone=True), nullable=False),
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
            "grounding IN ('no_official_source','partial')",
            name=op.f("ck_knowledge_gap_question_grounding"),
        ),
        sa.CheckConstraint(
            "language IS NULL OR language IN ('fr','aeb_arab','aeb_latn','ar','en','mixed','unknown')",
            name=op.f("ck_knowledge_gap_question_language"),
        ),
        sa.ForeignKeyConstraint(
            ["knowledge_gap_id"],
            ["knowledge_gap.id"],
            name=op.f("fk_knowledge_gap_question_knowledge_gap_id"),
        ),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["message.id"],
            name=op.f("fk_knowledge_gap_question_message_id"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_knowledge_gap_question")),
    )
    op.create_index(
        "ix_knowledge_gap_question_embedding",
        "knowledge_gap_question",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index(
        op.f("ix_knowledge_gap_question_knowledge_gap_id"),
        "knowledge_gap_question",
        ["knowledge_gap_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_gap_question_message_id"),
        "knowledge_gap_question",
        ["message_id"],
        unique=False,
    )
    op.create_table(
        "message_feedback",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("rating", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("author_user_id", sa.Uuid(), nullable=True),
        sa.Column("author_visitor_session_id", sa.Uuid(), nullable=True),
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
        sa.CheckConstraint("rating IN ('up','down')", name=op.f("ck_message_feedback_rating")),
        sa.CheckConstraint(
            "reason IS NULL OR reason IN ('incorrect_information','outdated_information','not_understood','wrong_language','incomplete','other')",
            name=op.f("ck_message_feedback_reason"),
        ),
        sa.CheckConstraint("length(comment) <= 1000", name=op.f("ck_message_feedback_comment")),
        sa.ForeignKeyConstraint(
            ["author_user_id"], ["user_account.id"], name=op.f("fk_message_feedback_author_user_id")
        ),
        sa.ForeignKeyConstraint(
            ["author_visitor_session_id"],
            ["visitor_session.id"],
            name=op.f("fk_message_feedback_author_visitor_session_id"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["message.id"],
            name=op.f("fk_message_feedback_message_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_message_feedback")),
        sa.UniqueConstraint("message_id", name=op.f("uq_message_feedback_message_id")),
    )
    op.create_index(
        op.f("ix_message_feedback_author_user_id"),
        "message_feedback",
        ["author_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_message_feedback_author_visitor_session_id"),
        "message_feedback",
        ["author_visitor_session_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_message_feedback_rating_created_at"),
        "message_feedback",
        ["rating", "created_at"],
        unique=False,
    )
    op.create_table(
        "preregistration",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("candidate_profile_id", sa.Uuid(), nullable=False),
        sa.Column("programme_id", sa.Uuid(), nullable=False),
        sa.Column("speciality_id", sa.Uuid(), nullable=True),
        sa.Column("academic_year", sa.Text(), nullable=False),
        sa.Column("entry_level", sa.SmallInteger(), server_default=sa.text("1"), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'draft'"), nullable=False),
        sa.Column("recommendation_item_id", sa.Uuid(), nullable=True),
        sa.Column("consent_id", sa.Uuid(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("assigned_to", sa.Uuid(), nullable=True),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
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
            "academic_year ~ '^[0-9]{4}-[0-9]{4}$'", name=op.f("ck_preregistration_academic_year")
        ),
        sa.CheckConstraint(
            "status IN ('draft','submitted','incomplete','under_review','interview_stage','decision_pending','waitlisted','admitted','enrolled','rejected','withdrawn','abandoned')",
            name=op.f("ck_preregistration_status"),
        ),
        sa.CheckConstraint(
            "status NOT IN ('waitlisted','admitted','enrolled','rejected') OR decided_by IS NOT NULL",
            name=op.f("ck_preregistration_human_decision"),
        ),
        sa.CheckConstraint(
            "entry_level BETWEEN 1 AND 5", name=op.f("ck_preregistration_entry_level")
        ),
        sa.ForeignKeyConstraint(
            ["assigned_to"], ["user_account.id"], name=op.f("fk_preregistration_assigned_to")
        ),
        sa.ForeignKeyConstraint(
            ["candidate_profile_id"],
            ["candidate_profile.id"],
            name=op.f("fk_preregistration_candidate_profile_id"),
        ),
        sa.ForeignKeyConstraint(
            ["consent_id"], ["consent.id"], name=op.f("fk_preregistration_consent_id")
        ),
        sa.ForeignKeyConstraint(
            ["decided_by"], ["user_account.id"], name=op.f("fk_preregistration_decided_by")
        ),
        sa.ForeignKeyConstraint(
            ["programme_id"], ["programme.id"], name=op.f("fk_preregistration_programme_id")
        ),
        sa.ForeignKeyConstraint(
            ["recommendation_item_id"],
            ["recommendation_item.id"],
            name=op.f("fk_preregistration_recommendation_item_id"),
        ),
        sa.ForeignKeyConstraint(
            ["speciality_id"], ["speciality.id"], name=op.f("fk_preregistration_speciality_id")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_preregistration")),
    )
    op.create_index(
        op.f("ix_preregistration_candidate_profile_id"),
        "preregistration",
        ["candidate_profile_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_preregistration_status_programme_id"),
        "preregistration",
        ["status", "programme_id"],
        unique=False,
    )
    op.create_index(
        "uq_preregistration_active",
        "preregistration",
        ["candidate_profile_id", "programme_id", "academic_year"],
        unique=True,
        postgresql_where=sa.text("status NOT IN ('withdrawn','abandoned','rejected')"),
    )
    op.create_table(
        "appointment",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("appointment_type", sa.Text(), nullable=False),
        sa.Column("slot_id", sa.Uuid(), nullable=True),
        sa.Column(
            "offered_slot_ids",
            postgresql.ARRAY(Uuid()),
            server_default=sa.text("'{}'::uuid[]"),
            nullable=False,
        ),
        sa.Column("candidate_profile_id", sa.Uuid(), nullable=False),
        sa.Column("preregistration_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'proposed'"), nullable=False),
        sa.Column("booked_via", sa.Text(), nullable=False),
        sa.Column("booked_by", sa.Uuid(), nullable=True),
        sa.Column("invitation_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_reason", sa.Text(), nullable=True),
        sa.Column("rescheduled_from_id", sa.Uuid(), nullable=True),
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
            "appointment_type IN ('interview','enrolment','advisory')",
            name=op.f("ck_appointment_appointment_type"),
        ),
        sa.CheckConstraint(
            "booked_via IN ('candidate_ui','agent_tool','staff')",
            name=op.f("ck_appointment_booked_via"),
        ),
        sa.CheckConstraint(
            "status IN ('proposed','cancelled') OR slot_id IS NOT NULL",
            name=op.f("ck_appointment_slot_required"),
        ),
        sa.CheckConstraint(
            "status IN ('proposed','scheduled','confirmed','completed','cancelled','no_show')",
            name=op.f("ck_appointment_status"),
        ),
        sa.ForeignKeyConstraint(
            ["booked_by"], ["user_account.id"], name=op.f("fk_appointment_booked_by")
        ),
        sa.ForeignKeyConstraint(
            ["candidate_profile_id"],
            ["candidate_profile.id"],
            name=op.f("fk_appointment_candidate_profile_id"),
        ),
        sa.ForeignKeyConstraint(
            ["preregistration_id"],
            ["preregistration.id"],
            name=op.f("fk_appointment_preregistration_id"),
        ),
        sa.ForeignKeyConstraint(
            ["rescheduled_from_id"],
            ["appointment.id"],
            name=op.f("fk_appointment_rescheduled_from_id"),
        ),
        sa.ForeignKeyConstraint(
            ["slot_id"], ["appointment_slot.id"], name=op.f("fk_appointment_slot_id")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_appointment")),
    )
    op.create_index(
        op.f("ix_appointment_candidate_profile_id"),
        "appointment",
        ["candidate_profile_id"],
        unique=False,
    )
    op.create_index(op.f("ix_appointment_slot_id"), "appointment", ["slot_id"], unique=False)
    op.create_index(
        "uq_appointment_active_slot",
        "appointment",
        ["slot_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('scheduled','confirmed')"),
    )
    op.create_index(
        "uq_appointment_active_type",
        "appointment",
        ["preregistration_id", "appointment_type"],
        unique=True,
        postgresql_where=sa.text("status IN ('proposed','scheduled','confirmed')"),
    )
    op.create_table(
        "equivalence_request",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("candidate_profile_id", sa.Uuid(), nullable=False),
        sa.Column("preregistration_id", sa.Uuid(), nullable=True),
        sa.Column("target_curriculum_id", sa.Uuid(), nullable=False),
        sa.Column("target_level", sa.SmallInteger(), nullable=False),
        sa.Column("origin_institution_name", sa.Text(), nullable=False),
        sa.Column("origin_programme_label", sa.Text(), nullable=False),
        sa.Column("transcript_attachment_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'draft'"), nullable=False),
        sa.Column("ai_model", sa.Text(), nullable=True),
        sa.Column("ai_prompt_version", sa.Text(), nullable=True),
        sa.Column("ai_analysed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
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
            "status IN ('draft','submitted','incomplete','analysis_in_progress','analysis_ready','under_review','approved','partially_approved','rejected','withdrawn')",
            name=op.f("ck_equivalence_request_status"),
        ),
        sa.CheckConstraint(
            "status NOT IN ('approved','partially_approved','rejected') OR decided_by IS NOT NULL",
            name=op.f("ck_equivalence_request_human_decision"),
        ),
        sa.CheckConstraint("target_level >= 1", name=op.f("ck_equivalence_request_target_level")),
        sa.ForeignKeyConstraint(
            ["candidate_profile_id"],
            ["candidate_profile.id"],
            name=op.f("fk_equivalence_request_candidate_profile_id"),
        ),
        sa.ForeignKeyConstraint(
            ["decided_by"], ["user_account.id"], name=op.f("fk_equivalence_request_decided_by")
        ),
        sa.ForeignKeyConstraint(
            ["preregistration_id"],
            ["preregistration.id"],
            name=op.f("fk_equivalence_request_preregistration_id"),
        ),
        sa.ForeignKeyConstraint(
            ["target_curriculum_id"],
            ["curriculum.id"],
            name=op.f("fk_equivalence_request_target_curriculum_id"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_equivalence_request")),
    )
    op.create_index(
        op.f("ix_equivalence_request_candidate_profile_id"),
        "equivalence_request",
        ["candidate_profile_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_equivalence_request_preregistration_id"),
        "equivalence_request",
        ["preregistration_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_equivalence_request_status"), "equivalence_request", ["status"], unique=False
    )
    op.create_index(
        op.f("ix_equivalence_request_transcript_attachment_id"),
        "equivalence_request",
        ["transcript_attachment_id"],
        unique=False,
    )
    op.create_table(
        "follow_up",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("candidate_profile_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("preregistration_id", sa.Uuid(), nullable=True),
        sa.Column("attempt_no", sa.SmallInteger(), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'planned'"), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("message_body", sa.Text(), nullable=True),
        sa.Column("escalated_to", sa.Uuid(), nullable=True),
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
        sa.CheckConstraint("channel IN ('email','in_app')", name=op.f("ck_follow_up_channel")),
        sa.CheckConstraint(
            "reason IN ('inactivity','missing_document','appointment_unconfirmed','qcm_not_started','appointment_reminder')",
            name=op.f("ck_follow_up_reason"),
        ),
        sa.CheckConstraint(
            "status IN ('planned','sent','cancelled','failed','escalated')",
            name=op.f("ck_follow_up_status"),
        ),
        sa.CheckConstraint("attempt_no >= 1", name=op.f("ck_follow_up_attempt_no")),
        sa.ForeignKeyConstraint(
            ["candidate_profile_id"],
            ["candidate_profile.id"],
            name=op.f("fk_follow_up_candidate_profile_id"),
        ),
        sa.ForeignKeyConstraint(
            ["escalated_to"], ["user_account.id"], name=op.f("fk_follow_up_escalated_to")
        ),
        sa.ForeignKeyConstraint(
            ["preregistration_id"],
            ["preregistration.id"],
            name=op.f("fk_follow_up_preregistration_id"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_follow_up")),
    )
    op.create_index(
        op.f("ix_follow_up_candidate_profile_id"),
        "follow_up",
        ["candidate_profile_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_follow_up_status_scheduled_at"),
        "follow_up",
        ["status", "scheduled_at"],
        unique=False,
    )
    op.create_table(
        "mcq_attempt",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("preregistration_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'generated'"), nullable=False),
        sa.Column("generator_model", sa.Text(), nullable=True),
        sa.Column("question_count", sa.SmallInteger(), nullable=False),
        sa.Column("time_limit_minutes", sa.SmallInteger(), nullable=True),
        sa.Column("assigned_by", sa.Uuid(), nullable=True),
        sa.Column("prompt_version", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("score", sa.Numeric(precision=6, scale=2), nullable=True),
        sa.Column("max_score", sa.Numeric(precision=6, scale=2), nullable=True),
        sa.Column("ai_summary", postgresql.JSONB(astext_type=Text()), nullable=True),
        sa.Column("candidate_feedback", sa.Text(), nullable=True),
        sa.Column("candidate_feedback_released_at", sa.DateTime(timezone=True), nullable=True),
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
            "status IN ('generated','assigned','in_progress','submitted','graded','expired','cancelled')",
            name=op.f("ck_mcq_attempt_status"),
        ),
        sa.CheckConstraint("max_score > 0", name=op.f("ck_mcq_attempt_max_score")),
        sa.CheckConstraint("question_count > 0", name=op.f("ck_mcq_attempt_question_count")),
        sa.CheckConstraint("score >= 0", name=op.f("ck_mcq_attempt_score")),
        sa.CheckConstraint(
            "time_limit_minutes > 0", name=op.f("ck_mcq_attempt_time_limit_minutes")
        ),
        sa.ForeignKeyConstraint(
            ["assigned_by"], ["user_account.id"], name=op.f("fk_mcq_attempt_assigned_by")
        ),
        sa.ForeignKeyConstraint(
            ["preregistration_id"],
            ["preregistration.id"],
            name=op.f("fk_mcq_attempt_preregistration_id"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mcq_attempt")),
    )
    op.create_index(
        op.f("ix_mcq_attempt_preregistration_id"),
        "mcq_attempt",
        ["preregistration_id"],
        unique=False,
    )
    op.create_index(
        "uq_mcq_attempt_open",
        "mcq_attempt",
        ["preregistration_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('generated','assigned','in_progress')"),
    )
    op.create_table(
        "candidate_attachment",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("candidate_profile_id", sa.Uuid(), nullable=False),
        sa.Column("attachment_type", sa.Text(), nullable=False),
        sa.Column("preregistration_id", sa.Uuid(), nullable=True),
        sa.Column("equivalence_request_id", sa.Uuid(), nullable=True),
        sa.Column("content_sha256", sa.CHAR(length=64), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("original_filename", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("review_status", sa.Text(), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("reviewed_by", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("supersedes_id", sa.Uuid(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("uploaded_by", sa.Uuid(), nullable=False),
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
            "attachment_type IN ('id_document','bac_transcript','diploma','grade_transcript','syllabus','photo','other')",
            name=op.f("ck_candidate_attachment_attachment_type"),
        ),
        sa.CheckConstraint(
            "content_sha256 ~ '^[0-9a-f]{64}$'", name=op.f("ck_candidate_attachment_content_sha256")
        ),
        sa.CheckConstraint(
            "mime_type IN ('application/pdf','text/html','text/markdown','text/plain','application/vnd.openxmlformats-officedocument.wordprocessingml.document','image/jpeg','image/png')",
            name=op.f("ck_candidate_attachment_mime_type"),
        ),
        sa.CheckConstraint(
            "review_status <> 'rejected' OR rejection_reason IS NOT NULL",
            name=op.f("ck_candidate_attachment_rejection_reason"),
        ),
        sa.CheckConstraint(
            "review_status = 'pending' OR (reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL)",
            name=op.f("ck_candidate_attachment_human_review"),
        ),
        sa.CheckConstraint(
            "review_status IN ('pending','accepted','rejected')",
            name=op.f("ck_candidate_attachment_review_status"),
        ),
        sa.CheckConstraint(
            "size_bytes > 0 AND size_bytes <= 52428800",
            name=op.f("ck_candidate_attachment_size_bytes"),
        ),
        sa.ForeignKeyConstraint(
            ["candidate_profile_id"],
            ["candidate_profile.id"],
            name=op.f("fk_candidate_attachment_candidate_profile_id"),
        ),
        sa.ForeignKeyConstraint(
            ["equivalence_request_id"],
            ["equivalence_request.id"],
            name=op.f("fk_candidate_attachment_equivalence_request_id"),
        ),
        sa.ForeignKeyConstraint(
            ["preregistration_id"],
            ["preregistration.id"],
            name=op.f("fk_candidate_attachment_preregistration_id"),
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by"], ["user_account.id"], name=op.f("fk_candidate_attachment_reviewed_by")
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_id"],
            ["candidate_attachment.id"],
            name=op.f("fk_candidate_attachment_supersedes_id"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by"], ["user_account.id"], name=op.f("fk_candidate_attachment_uploaded_by")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_candidate_attachment")),
        sa.UniqueConstraint(
            "candidate_profile_id",
            "content_sha256",
            name=op.f("uq_candidate_attachment_candidate_profile_id_content_sha256"),
        ),
        sa.UniqueConstraint("storage_path", name=op.f("uq_candidate_attachment_storage_path")),
    )
    op.create_index(
        op.f("ix_candidate_attachment_candidate_profile_id"),
        "candidate_attachment",
        ["candidate_profile_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_candidate_attachment_equivalence_request_id"),
        "candidate_attachment",
        ["equivalence_request_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_candidate_attachment_preregistration_id"),
        "candidate_attachment",
        ["preregistration_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_candidate_attachment_supersedes_id"),
        "candidate_attachment",
        ["supersedes_id"],
        unique=False,
    )
    op.create_table(
        "equivalence_item",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("equivalence_request_id", sa.Uuid(), nullable=False),
        sa.Column("origin_subject_label", sa.Text(), nullable=False),
        sa.Column("origin_hours", sa.Integer(), nullable=True),
        sa.Column("origin_credits", sa.Numeric(precision=4, scale=1), nullable=True),
        sa.Column("origin_grade", sa.Numeric(precision=4, scale=2), nullable=True),
        sa.Column("ai_target_subject_id", sa.Uuid(), nullable=True),
        sa.Column("ai_verdict", sa.Text(), nullable=True),
        sa.Column("ai_confidence", sa.REAL(), nullable=True),
        sa.Column("ai_rationale", sa.Text(), nullable=True),
        sa.Column("decision", sa.Text(), server_default=sa.text("'proposed'"), nullable=False),
        sa.Column("final_target_subject_id", sa.Uuid(), nullable=True),
        sa.Column("final_verdict", sa.Text(), nullable=True),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("staff_comment", sa.Text(), nullable=True),
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
            "ai_verdict IS NULL OR ai_verdict IN ('equivalent','partial','not_equivalent')",
            name=op.f("ck_equivalence_item_ai_verdict"),
        ),
        sa.CheckConstraint(
            "decision = 'proposed' OR (decided_by IS NOT NULL AND final_verdict IS NOT NULL)",
            name=op.f("ck_equivalence_item_human_decision"),
        ),
        sa.CheckConstraint(
            "decision IN ('proposed','accepted','modified','rejected')",
            name=op.f("ck_equivalence_item_decision"),
        ),
        sa.CheckConstraint(
            "final_verdict IS NULL OR final_verdict IN ('equivalent','partial','not_equivalent')",
            name=op.f("ck_equivalence_item_final_verdict"),
        ),
        sa.CheckConstraint(
            "ai_confidence BETWEEN 0 AND 1", name=op.f("ck_equivalence_item_ai_confidence")
        ),
        sa.CheckConstraint(
            "origin_grade BETWEEN 0 AND 20", name=op.f("ck_equivalence_item_origin_grade")
        ),
        sa.ForeignKeyConstraint(
            ["ai_target_subject_id"],
            ["subject.id"],
            name=op.f("fk_equivalence_item_ai_target_subject_id"),
        ),
        sa.ForeignKeyConstraint(
            ["decided_by"], ["user_account.id"], name=op.f("fk_equivalence_item_decided_by")
        ),
        sa.ForeignKeyConstraint(
            ["equivalence_request_id"],
            ["equivalence_request.id"],
            name=op.f("fk_equivalence_item_equivalence_request_id"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["final_target_subject_id"],
            ["subject.id"],
            name=op.f("fk_equivalence_item_final_target_subject_id"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_equivalence_item")),
    )
    op.create_index(
        op.f("ix_equivalence_item_equivalence_request_id"),
        "equivalence_item",
        ["equivalence_request_id"],
        unique=False,
    )
    op.create_index(
        "ix_equivalence_item_to_review",
        "equivalence_item",
        ["equivalence_request_id"],
        unique=False,
        postgresql_where=sa.text("decision = 'proposed'"),
    )
    op.create_table(
        "interview",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("appointment_id", sa.Uuid(), nullable=True),
        sa.Column("preregistration_id", sa.Uuid(), nullable=False),
        sa.Column("interviewer_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status", sa.Text(), server_default=sa.text("'awaiting_scheduling'"), nullable=False
        ),
        sa.Column("brief", postgresql.JSONB(astext_type=Text()), nullable=True),
        sa.Column("brief_model", sa.Text(), nullable=True),
        sa.Column("rubric_version", sa.Text(), nullable=True),
        sa.Column("rubric_scores", postgresql.JSONB(astext_type=Text()), nullable=True),
        sa.Column("overall_score", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("outcome", sa.Text(), nullable=True),
        sa.Column("observations", sa.Text(), nullable=True),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
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
            "outcome IS NULL OR outcome IN ('favorable','reserved','unfavorable')",
            name=op.f("ck_interview_outcome"),
        ),
        sa.CheckConstraint(
            "status <> 'result_recorded' OR outcome IS NOT NULL", name=op.f("ck_interview_result")
        ),
        sa.CheckConstraint(
            "status IN ('awaiting_scheduling','scheduled','result_recorded','complement_requested','forwarded','cancelled','no_show')",
            name=op.f("ck_interview_status"),
        ),
        sa.CheckConstraint(
            "(outcome IS NULL) = (decided_by IS NULL)", name=op.f("ck_interview_human_decision")
        ),
        sa.ForeignKeyConstraint(
            ["appointment_id"], ["appointment.id"], name=op.f("fk_interview_appointment_id")
        ),
        sa.ForeignKeyConstraint(
            ["decided_by"], ["user_account.id"], name=op.f("fk_interview_decided_by")
        ),
        sa.ForeignKeyConstraint(
            ["interviewer_id"], ["user_account.id"], name=op.f("fk_interview_interviewer_id")
        ),
        sa.ForeignKeyConstraint(
            ["preregistration_id"],
            ["preregistration.id"],
            name=op.f("fk_interview_preregistration_id"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_interview")),
        sa.UniqueConstraint("appointment_id", name=op.f("uq_interview_appointment_id")),
    )
    op.create_index(
        op.f("ix_interview_preregistration_id"), "interview", ["preregistration_id"], unique=False
    )
    op.create_index(
        op.f("ix_interview_status_interviewer_id"),
        "interview",
        ["status", "interviewer_id"],
        unique=False,
    )
    op.create_table(
        "mcq_attempt_item",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("mcq_attempt_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("mcq_question_id", sa.Uuid(), nullable=False),
        sa.Column("question_snapshot", postgresql.JSONB(astext_type=Text()), nullable=False),
        sa.Column("answer_keys", postgresql.ARRAY(Text()), nullable=True),
        sa.Column("is_correct", sa.Boolean(), nullable=True),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint("position >= 1", name=op.f("ck_mcq_attempt_item_position")),
        sa.ForeignKeyConstraint(
            ["mcq_attempt_id"],
            ["mcq_attempt.id"],
            name=op.f("fk_mcq_attempt_item_mcq_attempt_id"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["mcq_question_id"],
            ["mcq_question.id"],
            name=op.f("fk_mcq_attempt_item_mcq_question_id"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mcq_attempt_item")),
        sa.UniqueConstraint(
            "mcq_attempt_id", "position", name=op.f("uq_mcq_attempt_item_mcq_attempt_id_position")
        ),
    )
    op.create_index(
        op.f("ix_mcq_attempt_item_mcq_question_id"),
        "mcq_attempt_item",
        ["mcq_question_id"],
        unique=False,
    )
    op.create_table(
        "notification",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("link", sa.Text(), nullable=True),
        sa.Column("entity_type", sa.Text(), nullable=True),
        sa.Column("entity_id", sa.Uuid(), nullable=True),
        sa.Column("follow_up_id", sa.Uuid(), nullable=True),
        sa.Column("email_job_id", sa.Uuid(), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
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
            "entity_type IS NULL OR entity_type IN ('preregistration','equivalence_request','equivalence_item','appointment','appointment_slot','interview','recommendation','mcq_attempt','mcq_question','visitor_session','conversation','conversation_attachment','user_account','follow_up','knowledge_gap','candidate_attachment','document_version','institution','programme','speciality','curriculum','admission_condition','fee_schedule','bridge')",
            name=op.f("ck_notification_entity_type"),
        ),
        sa.CheckConstraint(
            "type IN ('appointment_reminder','appointment_confirmed','appointment_cancelled','preregistration_status_changed','qcm_assigned','document_requested','equivalence_decided','recommendation_confirmed','follow_up')",
            name=op.f("ck_notification_type"),
        ),
        sa.ForeignKeyConstraint(
            ["email_job_id"],
            ["job.id"],
            name=op.f("fk_notification_email_job_id"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["follow_up_id"],
            ["follow_up.id"],
            name=op.f("fk_notification_follow_up_id"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user_account.id"],
            name=op.f("fk_notification_user_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notification")),
    )
    op.create_index(
        op.f("ix_notification_email_job_id"), "notification", ["email_job_id"], unique=False
    )
    op.create_index(
        "ix_notification_unread",
        "notification",
        ["user_id", sa.literal_column("created_at DESC")],
        unique=False,
        postgresql_where=sa.text("read_at IS NULL"),
    )
    op.create_table(
        "academic_record",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("candidate_profile_id", sa.Uuid(), nullable=False),
        sa.Column("record_type", sa.Text(), nullable=False),
        sa.Column("bac_section", sa.Text(), nullable=True),
        sa.Column("year", sa.SmallInteger(), nullable=False),
        sa.Column("institution_name", sa.Text(), nullable=True),
        sa.Column("diploma_label", sa.Text(), nullable=True),
        sa.Column("overall_average", sa.Numeric(precision=4, scale=2), nullable=True),
        sa.Column("orientation_score", sa.Numeric(precision=7, scale=3), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("attachment_id", sa.Uuid(), nullable=True),
        sa.Column("verified_by", sa.Uuid(), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
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
            "(record_type = 'bac') = (bac_section IS NOT NULL)",
            name=op.f("ck_academic_record_bac_section_set"),
        ),
        sa.CheckConstraint(
            "bac_section IS NULL OR bac_section IN ('mathematiques','sciences_experimentales','sciences_techniques','sciences_informatique','economie_gestion','lettres','sport')",
            name=op.f("ck_academic_record_bac_section"),
        ),
        sa.CheckConstraint(
            "record_type IN ('bac','university_year','other_diploma')",
            name=op.f("ck_academic_record_record_type"),
        ),
        sa.CheckConstraint(
            "source IN ('declared','extracted_from_document','staff_verified')",
            name=op.f("ck_academic_record_source"),
        ),
        sa.CheckConstraint(
            "orientation_score >= 0", name=op.f("ck_academic_record_orientation_score")
        ),
        sa.CheckConstraint(
            "overall_average BETWEEN 0 AND 20", name=op.f("ck_academic_record_overall_average")
        ),
        sa.CheckConstraint("year BETWEEN 1990 AND 2100", name=op.f("ck_academic_record_year")),
        sa.ForeignKeyConstraint(
            ["attachment_id"],
            ["candidate_attachment.id"],
            name=op.f("fk_academic_record_attachment_id"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_profile_id"],
            ["candidate_profile.id"],
            name=op.f("fk_academic_record_candidate_profile_id"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["verified_by"], ["user_account.id"], name=op.f("fk_academic_record_verified_by")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_academic_record")),
    )
    op.create_index(
        op.f("ix_academic_record_attachment_id"), "academic_record", ["attachment_id"], unique=False
    )
    op.create_index(
        op.f("ix_academic_record_candidate_profile_id"),
        "academic_record",
        ["candidate_profile_id"],
        unique=False,
    )
    op.create_table(
        "academic_record_subject",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("academic_record_id", sa.Uuid(), nullable=False),
        sa.Column("subject_label", sa.Text(), nullable=False),
        sa.Column("subject_key", sa.Text(), nullable=True),
        sa.Column("grade", sa.Numeric(precision=4, scale=2), nullable=True),
        sa.Column("coefficient", sa.Numeric(precision=4, scale=2), nullable=True),
        sa.Column("credits", sa.Numeric(precision=4, scale=1), nullable=True),
        sa.Column("hours", sa.Integer(), nullable=True),
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
            "subject_key IS NULL OR subject_key IN ('mathematiques','physique','sciences_vie_terre','informatique','algorithmique_programmation','sti','technologie','economie','gestion','histoire_geographie','philosophie','pensee_islamique','arabe','francais','anglais','langue_option','education_physique','sciences_biologiques')",
            name=op.f("ck_academic_record_subject_subject_key"),
        ),
        sa.CheckConstraint("coefficient > 0", name=op.f("ck_academic_record_subject_coefficient")),
        sa.CheckConstraint("credits >= 0", name=op.f("ck_academic_record_subject_credits")),
        sa.CheckConstraint("grade BETWEEN 0 AND 20", name=op.f("ck_academic_record_subject_grade")),
        sa.CheckConstraint("hours >= 0", name=op.f("ck_academic_record_subject_hours")),
        sa.ForeignKeyConstraint(
            ["academic_record_id"],
            ["academic_record.id"],
            name=op.f("fk_academic_record_subject_academic_record_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_academic_record_subject")),
    )
    op.create_index(
        op.f("ix_academic_record_subject_academic_record_id"),
        "academic_record_subject",
        ["academic_record_id"],
        unique=False,
    )
    # FK du cycle equivalence_request <-> candidate_attachment (use_alter dans le modèle).
    op.create_foreign_key(
        "fk_equivalence_request_transcript_attachment_id",
        "equivalence_request",
        "candidate_attachment",
        ["transcript_attachment_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # --- SQL brut : triggers, vue, droits -------------------------------------------------------
    _updated_at_triggers(UPDATED_AT_TABLES)
    op.execute(V_PENDING_VALIDATION)
    for t in APPEND_ONLY_TABLES:
        _if_role("smartcampus_app", f"REVOKE UPDATE, DELETE, TRUNCATE ON {t} FROM smartcampus_app")
    # Exception D33 : le job purge (rôle applicatif) efface arguments / result après 90 jours.
    _if_role(
        "smartcampus_app", "GRANT UPDATE (arguments, result) ON agent_action_log TO smartcampus_app"
    )


def downgrade() -> None:

    op.execute("DROP VIEW IF EXISTS v_pending_validation")
    _drop_triggers(UPDATED_AT_TABLES, "updated_at")
    op.drop_constraint(
        "fk_equivalence_request_transcript_attachment_id", "equivalence_request", type_="foreignkey"
    )
    op.drop_index(
        op.f("ix_academic_record_subject_academic_record_id"), table_name="academic_record_subject"
    )
    op.drop_table("academic_record_subject")
    op.drop_index(op.f("ix_academic_record_candidate_profile_id"), table_name="academic_record")
    op.drop_index(op.f("ix_academic_record_attachment_id"), table_name="academic_record")
    op.drop_table("academic_record")
    op.drop_index(
        "ix_notification_unread",
        table_name="notification",
        postgresql_where=sa.text("read_at IS NULL"),
    )
    op.drop_index(op.f("ix_notification_email_job_id"), table_name="notification")
    op.drop_table("notification")
    op.drop_index(op.f("ix_mcq_attempt_item_mcq_question_id"), table_name="mcq_attempt_item")
    op.drop_table("mcq_attempt_item")
    op.drop_index(op.f("ix_interview_status_interviewer_id"), table_name="interview")
    op.drop_index(op.f("ix_interview_preregistration_id"), table_name="interview")
    op.drop_table("interview")
    op.drop_index(
        "ix_equivalence_item_to_review",
        table_name="equivalence_item",
        postgresql_where=sa.text("decision = 'proposed'"),
    )
    op.drop_index(op.f("ix_equivalence_item_equivalence_request_id"), table_name="equivalence_item")
    op.drop_table("equivalence_item")
    op.drop_index(op.f("ix_candidate_attachment_supersedes_id"), table_name="candidate_attachment")
    op.drop_index(
        op.f("ix_candidate_attachment_preregistration_id"), table_name="candidate_attachment"
    )
    op.drop_index(
        op.f("ix_candidate_attachment_equivalence_request_id"), table_name="candidate_attachment"
    )
    op.drop_index(
        op.f("ix_candidate_attachment_candidate_profile_id"), table_name="candidate_attachment"
    )
    op.drop_table("candidate_attachment")
    op.drop_index(
        "uq_mcq_attempt_open",
        table_name="mcq_attempt",
        postgresql_where=sa.text("status IN ('generated','assigned','in_progress')"),
    )
    op.drop_index(op.f("ix_mcq_attempt_preregistration_id"), table_name="mcq_attempt")
    op.drop_table("mcq_attempt")
    op.drop_index(op.f("ix_follow_up_status_scheduled_at"), table_name="follow_up")
    op.drop_index(op.f("ix_follow_up_candidate_profile_id"), table_name="follow_up")
    op.drop_table("follow_up")
    op.drop_index(
        op.f("ix_equivalence_request_transcript_attachment_id"), table_name="equivalence_request"
    )
    op.drop_index(op.f("ix_equivalence_request_status"), table_name="equivalence_request")
    op.drop_index(
        op.f("ix_equivalence_request_preregistration_id"), table_name="equivalence_request"
    )
    op.drop_index(
        op.f("ix_equivalence_request_candidate_profile_id"), table_name="equivalence_request"
    )
    op.drop_table("equivalence_request")
    op.drop_index(
        "uq_appointment_active_type",
        table_name="appointment",
        postgresql_where=sa.text("status IN ('proposed','scheduled','confirmed')"),
    )
    op.drop_index(
        "uq_appointment_active_slot",
        table_name="appointment",
        postgresql_where=sa.text("status IN ('scheduled','confirmed')"),
    )
    op.drop_index(op.f("ix_appointment_slot_id"), table_name="appointment")
    op.drop_index(op.f("ix_appointment_candidate_profile_id"), table_name="appointment")
    op.drop_table("appointment")
    op.drop_index(
        "uq_preregistration_active",
        table_name="preregistration",
        postgresql_where=sa.text("status NOT IN ('withdrawn','abandoned','rejected')"),
    )
    op.drop_index(op.f("ix_preregistration_status_programme_id"), table_name="preregistration")
    op.drop_index(op.f("ix_preregistration_candidate_profile_id"), table_name="preregistration")
    op.drop_table("preregistration")
    op.drop_index(op.f("ix_message_feedback_rating_created_at"), table_name="message_feedback")
    op.drop_index(
        op.f("ix_message_feedback_author_visitor_session_id"), table_name="message_feedback"
    )
    op.drop_index(op.f("ix_message_feedback_author_user_id"), table_name="message_feedback")
    op.drop_table("message_feedback")
    op.drop_index(op.f("ix_knowledge_gap_question_message_id"), table_name="knowledge_gap_question")
    op.drop_index(
        op.f("ix_knowledge_gap_question_knowledge_gap_id"), table_name="knowledge_gap_question"
    )
    op.drop_index(
        "ix_knowledge_gap_question_embedding",
        table_name="knowledge_gap_question",
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.drop_table("knowledge_gap_question")
    op.drop_index(op.f("ix_agent_action_log_visitor_session_id"), table_name="agent_action_log")
    op.drop_index(op.f("ix_agent_action_log_tool_name_occurred_at"), table_name="agent_action_log")
    op.drop_index(op.f("ix_agent_action_log_message_id"), table_name="agent_action_log")
    op.drop_index(
        "ix_agent_action_log_errors",
        table_name="agent_action_log",
        postgresql_where=sa.text("status <> 'succeeded'"),
    )
    op.drop_index(
        op.f("ix_agent_action_log_conversation_id_occurred_at"), table_name="agent_action_log"
    )
    op.drop_table("agent_action_log")
    op.drop_index(op.f("ix_recommendation_item_speciality_id"), table_name="recommendation_item")
    op.drop_index(op.f("ix_recommendation_item_programme_id"), table_name="recommendation_item")
    op.drop_table("recommendation_item")
    op.drop_index(
        op.f("ix_message_knowledge_gap_id"),
        table_name="message",
        postgresql_where=sa.text("knowledge_gap_id IS NOT NULL"),
    )
    op.drop_index(
        "ix_message_audio_purge",
        table_name="message",
        postgresql_where=sa.text("audio_storage_path IS NOT NULL"),
    )
    op.drop_table("message")
    op.drop_index(
        "uq_conversation_attachment_attached",
        table_name="conversation_attachment",
        postgresql_where=sa.text("status = 'attached'"),
    )
    op.drop_index(op.f("ix_conversation_attachment_user_id"), table_name="conversation_attachment")
    op.drop_index(
        op.f("ix_conversation_attachment_consent_id"), table_name="conversation_attachment"
    )
    op.drop_table("conversation_attachment")
    op.drop_index(op.f("ix_recommendation_status"), table_name="recommendation")
    op.drop_index(op.f("ix_recommendation_conversation_id"), table_name="recommendation")
    op.drop_index(op.f("ix_recommendation_candidate_profile_id"), table_name="recommendation")
    op.drop_table("recommendation")
    op.drop_index(
        "ix_mcq_question_validated",
        table_name="mcq_question",
        postgresql_where=sa.text("status = 'validated'"),
    )
    op.drop_table("mcq_question")
    op.drop_index(op.f("ix_knowledge_gap_status"), table_name="knowledge_gap")
    op.drop_index(op.f("ix_knowledge_gap_institution_id"), table_name="knowledge_gap")
    op.drop_table("knowledge_gap")
    op.drop_index(op.f("ix_consent_visitor_session_id"), table_name="consent")
    op.drop_index(op.f("ix_consent_user_id_consent_type"), table_name="consent")
    op.drop_index(op.f("ix_consent_conversation_id"), table_name="consent")
    op.drop_table("consent")
    op.drop_index("uq_idempotency_key_caller_key", table_name="idempotency_key")
    op.drop_index(op.f("ix_idempotency_key_visitor_session_id"), table_name="idempotency_key")
    op.drop_index(op.f("ix_idempotency_key_user_id"), table_name="idempotency_key")
    op.drop_index(op.f("ix_idempotency_key_expires_at"), table_name="idempotency_key")
    op.drop_table("idempotency_key")
    op.drop_index(op.f("ix_conversation_visitor_session_id"), table_name="conversation")
    op.drop_index("ix_conversation_user_last_message", table_name="conversation")
    op.drop_index(op.f("ix_conversation_origin_visitor_session_id"), table_name="conversation")
    op.drop_table("conversation")
    op.drop_index(
        "ix_appointment_slot_open",
        table_name="appointment_slot",
        postgresql_where=sa.text("status = 'open'"),
    )
    op.drop_table("appointment_slot")
    op.drop_index(op.f("ix_visitor_session_status_idle_expires_at"), table_name="visitor_session")
    op.drop_index(op.f("ix_visitor_session_attached_user_id"), table_name="visitor_session")
    op.drop_table("visitor_session")
    op.drop_index(
        op.f("ix_status_history_entity_type_entity_id_changed_at"), table_name="status_history"
    )
    op.drop_index(op.f("ix_status_history_actor_user_id"), table_name="status_history")
    op.drop_table("status_history")
    op.drop_table("candidate_profile")
