"""Schémas partagés du catalogue (SA-21, utilisés aussi par SA-20).

- statut et bloc de publication à double validation (SA-12 §0, D-B) ;
- période de validité `[valid_from, valid_to)` (valid_to **exclu**, SA-12 D3) ;
- corps des actions `/reject`, `/archive`, `/publish`, `/new-version` (SA-5 §5.14) ;
- carte source officielle (SA-5 §5.13 : `source`) ;
- montants `{"amount": "6500.000", "currency": "TND"}` en chaîne décimale (SA-5 §1.1) ;
- année universitaire `AAAA-AAAA` (deux années consécutives).
"""

from __future__ import annotations

import re
import uuid
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from app.models import enums

#: Statuts du cycle de publication (draft → pending_review → published → archived).
PublicationStatus = Literal["draft", "pending_review", "published", "archived"]
PUBLICATION_STATUSES: tuple[str, ...] = enums.PUBLICATION_STATUS

ACADEMIC_YEAR_RE = re.compile(r"^(\d{4})-(\d{4})$")


def _check_academic_year(value: str) -> str:
    match = ACADEMIC_YEAR_RE.match(value)
    if not match or int(match.group(2)) != int(match.group(1)) + 1:
        raise ValueError("année universitaire attendue au format AAAA-AAAA (ex. 2026-2027)")
    return value


#: Année universitaire, ex. `2026-2027` (la seconde année suit la première).
AcademicYear = Annotated[
    str,
    Field(examples=["2026-2027"], description="Année universitaire AAAA-AAAA."),
    AfterValidator(_check_academic_year),
]

# --- Montants ------------------------------------------------------------------------------------

MILLIME = Decimal("0.001")


def format_amount(value: Decimal | int | str) -> str:
    """Montant en chaîne décimale à 3 décimales (millimes), jamais en flottant."""
    return str(Decimal(value).quantize(MILLIME, rounding=ROUND_HALF_UP))


def _reject_float(value: Any) -> Any:
    if isinstance(value, float):
        raise ValueError('montant attendu en chaîne décimale (ex. "300.000"), pas en flottant')
    return value


#: Montant saisi : chaîne décimale ≥ 0, au plus 3 décimales.
AmountIn = Annotated[
    Decimal,
    BeforeValidator(_reject_float),
    Field(ge=0, max_digits=12, decimal_places=3, examples=["300.000"]),
]


class Money(BaseModel):
    """Montant rendu par l'API : `{"amount": "6500.000", "currency": "TND"}`."""

    amount: str = Field(examples=["6500.000"], description="Chaîne décimale, 3 décimales.")
    currency: str = Field(examples=["TND"], description="Devise ISO 4217.")

    @classmethod
    def of(cls, value: Decimal | int | str, currency: str = "TND") -> Money:
        return cls(amount=format_amount(value), currency=currency)


class MoneyIn(BaseModel):
    """Montant saisi par le staff."""

    model_config = ConfigDict(extra="forbid")

    amount: AmountIn
    currency: str = Field(default="TND", pattern=r"^[A-Z]{3}$")


# --- Période de validité et bloc de publication -----------------------------------------------


class ValidityPeriod(BaseModel):
    """Période `[valid_from, valid_to)` ; `valid_to` exclu, `None` = sans fin."""

    valid_from: date | None = Field(default=None, description="Début de validité (inclus).")
    valid_to: date | None = Field(default=None, description="Fin de validité (exclue).")

    @model_validator(mode="after")
    def _check_order(self) -> ValidityPeriod:
        if self.valid_from and self.valid_to and self.valid_to <= self.valid_from:
            raise ValueError("valid_to doit être postérieure à valid_from")
        return self


class PublicationInfo(BaseModel):
    """Bloc de publication commun à toutes les lignes publiables (lecture staff)."""

    model_config = ConfigDict(from_attributes=True)

    publication_status: PublicationStatus
    valid_from: date | None
    valid_to: date | None
    created_by: uuid.UUID
    submitted_by: uuid.UUID | None
    submitted_at: datetime | None
    published_by: uuid.UUID | None
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime


# --- Actions de publication -------------------------------------------------------------------


class PublishRequest(BaseModel):
    """Corps facultatif de `/publish`."""

    model_config = ConfigDict(extra="forbid")

    replace_current: bool = Field(
        default=False,
        description=(
            "Remplacement de version (SA-12 §3) : dans la même transaction, la version publiée "
            "qui chevauche est raccourcie (valid_to = valid_from de la nouvelle) ou archivée si "
            "elle commence au même jour ou après. Sans ce drapeau, un chevauchement renvoie "
            "409 VALIDITY_OVERLAP."
        ),
    )


class ReasonRequest(BaseModel):
    """Motif obligatoire (`/reject`)."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=3, max_length=2000, examples=["Montant à vérifier."])


class OptionalReasonRequest(BaseModel):
    """Motif facultatif (`/archive`)."""

    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=2000, examples=["Grille remplacée"])


class NewVersionRequest(BaseModel):
    """Corps de `/new-version` : surcharges facultatives de la copie en brouillon."""

    model_config = ConfigDict(extra="forbid")

    valid_from: date | None = None
    valid_to: date | None = None
    academic_year: AcademicYear | None = Field(
        default=None, description="Pour les frais et conditions : année de la nouvelle version."
    )


# --- Carte source officielle (SA-5 §5.13, F1) ------------------------------------------------


class SourceRef(BaseModel):
    """Référence à la donnée officielle citée (carte source de l'agent et du front)."""

    entity_type: str = Field(examples=["fee_schedule"])
    entity_id: uuid.UUID
    version: int | None = Field(
        default=None,
        description=(
            "Rang de publication dans la même clé métier (1 = première version publiée). "
            "Calculé, pas stocké."
        ),
    )
    published_at: datetime | None
    valid_from: date | None
    valid_to: date | None = Field(description="Fin de validité, exclue ; null = sans fin.")


__all__ = [
    "PUBLICATION_STATUSES",
    "AcademicYear",
    "AmountIn",
    "Money",
    "MoneyIn",
    "NewVersionRequest",
    "OptionalReasonRequest",
    "PublicationInfo",
    "PublicationStatus",
    "PublishRequest",
    "ReasonRequest",
    "SourceRef",
    "ValidityPeriod",
    "format_amount",
]
