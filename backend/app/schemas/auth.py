"""Schémas de l'authentification et du rattachement (SA-28, SA-29 ; SA-5 §5.2)."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

from app.core.passwords import PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_email(value: str) -> str:
    """E-mail en minuscules, sans espaces ; forme `x@y.z` exigée (254 caractères au plus)."""
    email = value.strip().lower()
    if len(email) > 254 or not _EMAIL_RE.fullmatch(email):
        raise ValueError("Adresse e-mail invalide.")
    return email


AccountType = Literal["candidate", "staff"]
AccountStatus = Literal["pending_verification", "active", "disabled"]
ConversationAttachmentStatus = Literal[
    "offered", "consented", "declined", "ownership_failed", "attached", "expired"
]
VisitorSessionStatus = Literal["active", "attached", "expired", "purged"]


class RegisterConsents(BaseModel):
    """Consentements obligatoires à l'inscription (journal `consent`, SA-13)."""

    model_config = ConfigDict(extra="forbid")

    terms_accepted: StrictBool
    data_processing: StrictBool


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(max_length=254, examples=["amine.candidat@example.com"])
    password: str = Field(
        min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH, repr=False
    )
    full_name: str = Field(min_length=1, max_length=200)
    phone: str | None = Field(default=None, max_length=40)
    consents: RegisterConsents

    @field_validator("email")
    @classmethod
    def _email(cls, value: str) -> str:
        return normalize_email(value)

    @field_validator("full_name")
    @classmethod
    def _full_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Le nom complet est obligatoire.")
        return value.strip()


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(max_length=254)
    password: str = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH, repr=False)


class User(BaseModel):
    id: uuid.UUID
    account_type: AccountType
    email: str
    full_name: str
    account_status: AccountStatus
    roles: list[str]
    candidate_id: uuid.UUID | None = None
    created_at: datetime


class AttachOffer(BaseModel):
    """Proposition de rattachement : présente si le navigateur porte un cookie visiteur actif
    dont la session contient au moins une conversation (SA-29)."""

    visitor_session_id: uuid.UUID
    conversation_count: int
    message_count: int
    offer_expires_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["Bearer"] = "Bearer"
    expires_in: int


class AuthResponse(TokenResponse):
    user: User
    attach_offer: AttachOffer | None = None


class AttachRequest(BaseModel):
    """Consentement explicite : booléen JSON strict (`"true"` ou `1` sont refusés)."""

    model_config = ConfigDict(extra="forbid")

    visitor_session_id: uuid.UUID
    consent: StrictBool


class AttachResponse(BaseModel):
    attachment_status: ConversationAttachmentStatus
    visitor_session_status: VisitorSessionStatus | None = None
    conversation_ids: list[uuid.UUID] = Field(default_factory=list)
