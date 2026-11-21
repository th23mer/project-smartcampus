"""Modèles SQLAlchemy du schéma E2 (SA-17) : SA-12 (catalogue), SA-13 (utilisateurs,
candidatures), SA-14 (documents, jobs).

Chaque modèle hérite de `app.core.db.Base`. Ce module importe **tous** les modules de modèles
pour qu'Alembic (`alembic/env.py`) voie l'ensemble des tables dans `Base.metadata`.

Objets volontairement hors modèles (posés en SQL brut par les migrations) : fonctions et
triggers (`set_updated_at`, `audit_catalogue`, gardes des versions publiées, contrôle différé
`job` ↔ `sync_job`), vues (`v_searchable_chunk`, `v_document_index_state`,
`v_pending_validation`) et droits (GRANT / REVOKE des rôles SA-16).
"""

from app.core.db import Base
from app.models import enums
from app.models.audit import AgentActionLog, IdempotencyKey, StatusHistory
from app.models.candidate import (
    AcademicRecord,
    AcademicRecordSubject,
    CandidateProfile,
    Recommendation,
    RecommendationItem,
)
from app.models.catalogue import (
    AdmissionCondition,
    AdmissionSubjectRequirement,
    Bridge,
    CatalogueAuditLog,
    CatalogueRevision,
    Curriculum,
    CurriculumSubject,
    FeeSchedule,
    Institution,
    PaymentInstallment,
    PaymentPlan,
    Prerequisite,
    Programme,
    Speciality,
    Subject,
)
from app.models.conversation import (
    Conversation,
    ConversationAttachment,
    Message,
    MessageFeedback,
    VisitorSession,
)
from app.models.documents import (
    EMBEDDING_DIM,
    CandidateAttachment,
    Document,
    DocumentChunk,
    DocumentProgramme,
    DocumentVersion,
    EmbeddingModel,
)
from app.models.identity import Consent, Role, UserAccount, UserRole
from app.models.jobs import Job, SyncJob
from app.models.knowledge import KnowledgeGap, KnowledgeGapQuestion
from app.models.process import (
    Appointment,
    AppointmentSlot,
    EquivalenceItem,
    EquivalenceRequest,
    FollowUp,
    Interview,
    McqAttempt,
    McqAttemptItem,
    McqQuestion,
    Notification,
    Preregistration,
)

__all__ = [
    "EMBEDDING_DIM",
    "AcademicRecord",
    "AcademicRecordSubject",
    "AdmissionCondition",
    "AdmissionSubjectRequirement",
    "AgentActionLog",
    "Appointment",
    "AppointmentSlot",
    "Base",
    "Bridge",
    "CandidateAttachment",
    "CandidateProfile",
    "CatalogueAuditLog",
    "CatalogueRevision",
    "Consent",
    "Conversation",
    "ConversationAttachment",
    "Curriculum",
    "CurriculumSubject",
    "Document",
    "DocumentChunk",
    "DocumentProgramme",
    "DocumentVersion",
    "EmbeddingModel",
    "EquivalenceItem",
    "EquivalenceRequest",
    "FeeSchedule",
    "FollowUp",
    "IdempotencyKey",
    "Institution",
    "Interview",
    "Job",
    "KnowledgeGap",
    "KnowledgeGapQuestion",
    "McqAttempt",
    "McqAttemptItem",
    "McqQuestion",
    "Message",
    "MessageFeedback",
    "Notification",
    "PaymentInstallment",
    "PaymentPlan",
    "Preregistration",
    "Prerequisite",
    "Programme",
    "Recommendation",
    "RecommendationItem",
    "Role",
    "Speciality",
    "StatusHistory",
    "Subject",
    "SyncJob",
    "UserAccount",
    "UserRole",
    "VisitorSession",
    "enums",
]
