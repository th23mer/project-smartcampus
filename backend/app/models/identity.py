"""Identité, rôles et consentements (SA-13 §4.A).

`user_account` est la cible de toutes les colonnes « auteur » du schéma (created_by,
submitted_by, published_by, decided_by…). Les visiteurs n'ont pas de compte (voir
`conversation.VisitorSession`).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Text, func, text
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models import enums
from app.models._common import (
    CreatedAt,
    Str,
    StrNull,
    Timestamps,
    TZNull,
    UUIDPrimaryKey,
    enum_check,
    fk,
)


class UserAccount(UUIDPrimaryKey, Timestamps, Base):
    """Compte authentifié (candidat ou staff). E-mail insensible à la casse (`citext`)."""

    __tablename__ = "user_account"

    email: Mapped[str] = mapped_column(CITEXT, unique=True)
    password_hash: Mapped[Str]
    full_name: Mapped[Str]
    phone: Mapped[StrNull]
    account_type: Mapped[Str]
    preferred_language: Mapped[str] = mapped_column(Text, server_default=text("'fr'"))
    account_status: Mapped[str] = mapped_column(Text, server_default=text("'pending_verification'"))
    email_verified_at: Mapped[TZNull]
    last_login_at: Mapped[TZNull]
    anonymized_at: Mapped[TZNull]

    __table_args__ = (
        enum_check("account_type", enums.ACCOUNT_TYPE),
        enum_check("preferred_language", enums.LANG_CODE),
        enum_check("account_status", enums.ACCOUNT_STATUS),
    )


class Role(UUIDPrimaryKey, Timestamps, Base):
    """Référentiel des rôles : `candidate` + sous-rôles staff de SA-3 (périmètre : D20)."""

    __tablename__ = "role"

    code: Mapped[str] = mapped_column(Text, unique=True)
    label: Mapped[Str]
    is_staff: Mapped[bool] = mapped_column(Boolean)
    institution_id: Mapped[uuid.UUID | None] = fk("institution.id")

    __table_args__ = (Index(None, "institution_id"),)


class UserRole(Timestamps, Base):
    """Attribution d'un rôle à un compte (n-n), conservée après révocation pour l'audit."""

    __tablename__ = "user_role"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user_account.id"), primary_key=True)
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("role.id"), primary_key=True)
    granted_by: Mapped[uuid.UUID | None] = fk("user_account.id")
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    revoked_at: Mapped[TZNull]

    __table_args__ = (
        Index("ix_user_role_role_active", "role_id", postgresql_where=text("revoked_at IS NULL")),
    )


class Consent(UUIDPrimaryKey, CreatedAt, Base):
    """Journal append-only des consentements (accord ou retrait), jamais déduit par le LLM.

    Pas de `updated_at` (journal) ; le rôle applicatif n'a ni UPDATE ni DELETE sur cette table.
    """

    __tablename__ = "consent"

    user_id: Mapped[uuid.UUID | None] = fk("user_account.id")
    visitor_session_id: Mapped[uuid.UUID | None] = fk("visitor_session.id", ondelete="SET NULL")
    consent_type: Mapped[Str]
    granted: Mapped[bool] = mapped_column(Boolean)
    policy_version: Mapped[Str]
    conversation_id: Mapped[uuid.UUID | None] = fk("conversation.id", ondelete="SET NULL")
    channel: Mapped[Str]
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        enum_check("consent_type", enums.CONSENT_TYPE),
        enum_check("channel", enums.CONSENT_CHANNEL),
        CheckConstraint("num_nonnulls(user_id, visitor_session_id) >= 1", name="holder"),
        Index(None, "user_id", "consent_type", text("recorded_at DESC")),
        Index(None, "visitor_session_id"),
        Index(None, "conversation_id"),
    )
