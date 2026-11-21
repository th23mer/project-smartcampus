"""Listes de valeurs (énumérations) du schéma E2 (SA-3, SA-5, SA-12, SA-13, SA-14).

Convention SA-12 §0 (D8) : en base, une énumération est une colonne `text` contrôlée par
`CHECK (col IN (...))`, jamais un type `ENUM` PostgreSQL. Ces tuples sont la **source unique**
des valeurs côté Python : les modèles construisent leurs CHECK à partir d'eux et les services
(E3, E4) peuvent les importer pour valider ou afficher.

Ajouter une valeur = modifier le tuple **et** écrire une migration qui remplace le CHECK
(Alembic ne détecte pas les changements de CHECK).
"""

from __future__ import annotations

# --- Publication des données officielles (SA-12 §0, D-B) -------------------------------------
PUBLICATION_STATUS = ("draft", "pending_review", "published", "archived")

# --- Référentiel du bac (C1 : clés françaises, exception assumée) -----------------------------
BAC_SECTION = (
    "mathematiques",
    "sciences_experimentales",
    "sciences_techniques",
    "sciences_informatique",
    "economie_gestion",
    "lettres",
    "sport",
)
BAC_SUBJECT_KEY = (
    "mathematiques",
    "physique",
    "sciences_vie_terre",
    "informatique",
    "algorithmique_programmation",
    "sti",
    "technologie",
    "economie",
    "gestion",
    "histoire_geographie",
    "philosophie",
    "pensee_islamique",
    "arabe",
    "francais",
    "anglais",
    "langue_option",
    "education_physique",
    "sciences_biologiques",
)

# --- Catalogue (SA-12) ------------------------------------------------------------------------
PROGRAMME_TYPE = ("preparatory", "licence", "engineering", "master", "other")
APPLICANT_CATEGORY = ("new_bachelor", "higher_education_graduate", "transfer_student")
REQUIRED_DIPLOMA = ("baccalaureate", "preparatory_cycle", "licence", "other_higher_education")
AVERAGE_BASIS = ("bac_average", "last_year_average", "cycle_average")
STUDENT_CATEGORY = ("tunisian", "foreign")
ACCESS_MODE = ("automatic", "on_application", "competitive_exam")
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
#: Révisions des entités stables publiées (SA-20 D1, validée 17/11).
REVISABLE_ENTITY_TYPE = ("institution", "programme", "speciality")
REVISION_STATUS = ("draft", "pending_review", "published", "rejected")
CATALOGUE_AUDIT_ACTION = ("insert", "update", "delete", "submit", "publish", "reject", "archive")

# --- Identité, conversations, dossiers (SA-13 §5) ---------------------------------------------
ACCOUNT_TYPE = ("candidate", "staff")
ACCOUNT_STATUS = ("pending_verification", "active", "disabled")
LANG_CODE = ("fr", "aeb_arab", "aeb_latn", "ar", "en", "mixed", "unknown")  # SA-5 (C2)
CONSENT_TYPE = (
    "terms_accepted",
    "data_processing",
    "contact_by_email",
    "conversation_link",
    "raw_conversation_access",
    "parent_share",
)
CONSENT_CHANNEL = ("web_form", "chat_button", "staff_on_behalf")
VISITOR_SESSION_STATUS = ("active", "attached", "expired", "purged")
CONVERSATION_STATUS = ("open", "closed", "archived")
CONVERSATION_ATTACHMENT_STATUS = (
    "offered",
    "consented",
    "declined",
    "ownership_failed",
    "attached",
    "expired",
)
CHANNEL = ("text", "audio", "mixed")
MESSAGE_ROLE = ("user", "assistant", "tool")
GROUNDING = ("grounded", "partial", "no_official_source", "not_applicable")
FINISH_REASON = (
    "completed",
    "clarification_requested",
    "fallback_human",
    "fallback_deterministic",
    "length",
    "refused",
)
CANDIDATE_TYPE = ("new_bachelor", "transfer", "other")
PROFILE_STATUS = ("ai_draft", "confirmed")
RECORD_TYPE = ("bac", "university_year", "other_diploma")
DATA_SOURCE = ("declared", "extracted_from_document", "staff_verified")
ORIENTATION_RECOMMENDATION_STATUS = (
    "draft",
    "proposed",
    "pending_validation",
    "confirmed",
    "adjusted",
    "superseded",
)
RECOMMENDATION_ITEM_DECISION = ("pending", "kept", "removed", "added_by_staff")
PREREGISTRATION_STATUS = (
    "draft",
    "submitted",
    "incomplete",
    "under_review",
    "interview_stage",
    "decision_pending",
    "waitlisted",
    "admitted",
    "enrolled",
    "rejected",
    "withdrawn",
    "abandoned",
)
MCQ_QUESTION_STATUS = ("draft", "validated", "retired")
MCQ_QUESTION_ORIGIN = ("staff", "ai_generated")
QCM_STATUS = (
    "generated",
    "assigned",
    "in_progress",
    "submitted",
    "graded",
    "expired",
    "cancelled",
)
EQUIVALENCE_STATUS = (
    "draft",
    "submitted",
    "incomplete",
    "analysis_in_progress",
    "analysis_ready",
    "under_review",
    "approved",
    "partially_approved",
    "rejected",
    "withdrawn",
)
EQUIVALENCE_LINE_DECISION = ("proposed", "accepted", "modified", "rejected")
EQUIVALENCE_VERDICT = ("equivalent", "partial", "not_equivalent")
APPOINTMENT_TYPE = ("interview", "enrolment", "advisory")
APPOINTMENT_MODE = ("onsite", "online")
SLOT_STATUS = ("open", "closed", "cancelled")
APPOINTMENT_STATUS = ("proposed", "scheduled", "confirmed", "completed", "cancelled", "no_show")
BOOKED_VIA = ("candidate_ui", "agent_tool", "staff")
INTERVIEW_STATUS = (
    "awaiting_scheduling",
    "scheduled",
    "result_recorded",
    "complement_requested",
    "forwarded",
    "cancelled",
    "no_show",
)
INTERVIEW_OUTCOME = ("favorable", "reserved", "unfavorable")
ACTOR_TYPE = ("visitor", "candidate", "staff", "ai_agent", "system")
STATUS_ENTITY_TYPE = (
    "preregistration",
    "equivalence_request",
    "equivalence_item",
    "appointment",
    "appointment_slot",
    "interview",
    "recommendation",
    "mcq_attempt",
    "mcq_question",
    "visitor_session",
    "conversation",
    "conversation_attachment",
    "user_account",
    "follow_up",
    "knowledge_gap",
    "candidate_attachment",
    "document_version",
    "institution",
    "programme",
    "speciality",
    "curriculum",
    "admission_condition",
    "fee_schedule",
    "bridge",
)
FOLLOW_UP_REASON = (
    "inactivity",
    "missing_document",
    "appointment_unconfirmed",
    "qcm_not_started",
    "appointment_reminder",
)
FOLLOW_UP_CHANNEL = ("email", "in_app")
FOLLOW_UP_STATUS = ("planned", "sent", "cancelled", "failed", "escalated")
NOTIFICATION_TYPE = (
    "appointment_reminder",
    "appointment_confirmed",
    "appointment_cancelled",
    "preregistration_status_changed",
    "qcm_assigned",
    "document_requested",
    "equivalence_decided",
    "recommendation_confirmed",
    "follow_up",
)
IDEMPOTENCY_STATE = ("in_progress", "completed")
AGENT_STEP_TYPE = ("llm_call", "tool_call", "retrieval", "stt", "guardrail", "output_check")
AGENT_TOOL_KIND = ("deterministic", "retrieval", "ai")
AGENT_STEP_STATUS = ("succeeded", "failed", "timeout", "refused")
KNOWLEDGE_GAP_STATUS = ("open", "in_progress", "resolved", "dismissed")
FEEDBACK_RATING = ("up", "down")
FEEDBACK_REASON = (
    "incorrect_information",
    "outdated_information",
    "not_understood",
    "wrong_language",
    "incomplete",
    "other",
)

# --- Documents, jobs, pièces (SA-14) ----------------------------------------------------------
EMBEDDING_DISTANCE = ("cosine", "l2", "inner_product")
DOCUMENT_TYPE = ("official_guide", "regulation", "brochure", "faq")
DOCUMENT_MIME_TYPE = (
    "application/pdf",
    "text/html",
    "text/markdown",
    "text/plain",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
)
INDEX_STATUS = ("not_indexed", "indexing", "indexed", "failed", "removed")
JOB_TYPE = ("vector_sync", "email", "follow_up", "equivalence_analysis", "purge")
JOB_STATUS = ("queued", "running", "retry_wait", "succeeded", "skipped", "failed", "cancelled")
SYNC_OPERATION = ("upsert", "delete")
SYNC_TRIGGER = ("version_created", "archived", "expired", "model_changed", "manual_retry")
ATTACHMENT_TYPE = (
    "id_document",
    "bac_transcript",
    "diploma",
    "grade_transcript",
    "syllabus",
    "photo",
    "other",
)
ATTACHMENT_MIME_TYPE = (*DOCUMENT_MIME_TYPE, "image/jpeg", "image/png")
CANDIDATE_DOCUMENT_REVIEW_STATUS = ("pending", "accepted", "rejected")
