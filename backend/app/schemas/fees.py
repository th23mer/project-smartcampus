"""Schémas des frais de scolarité et des modalités de paiement (SA-21).

Tables : `fee_schedule` (grille par année universitaire, D-A), `payment_plan`,
`payment_installment` (SA-12 §4). Montants en chaîne décimale TND (SA-5 §1.1) ;
`annual_total` vient de la **colonne générée** (jamais recalculé, ni par le code ni par le LLM).
Noms d'API alignés sur SA-5 §5.14 : `tuition_fee` ↔ colonne `annual_tuition_fee`.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.catalogue_common import (
    AcademicYear,
    AmountIn,
    Money,
    MoneyIn,
    PublicationInfo,
    SourceRef,
    ValidityPeriod,
)

StudentCategory = Literal["tunisian", "foreign"]


# --- Entrées staff -------------------------------------------------------------------------------


class InstallmentIn(BaseModel):
    """Échéance d'un plan : date limite et/ou libellé relatif (« à l'inscription »)."""

    model_config = ConfigDict(extra="forbid")

    installment_no: int = Field(ge=1, le=12)
    due_date: date | None = None
    due_label_fr: str | None = Field(default=None, max_length=200)
    amount: AmountIn

    @model_validator(mode="after")
    def _due(self) -> InstallmentIn:
        if self.due_date is None and not self.due_label_fr:
            raise ValueError("due_date ou due_label_fr est obligatoire")
        if self.amount <= 0:
            raise ValueError("le montant d'une échéance doit être positif")
        return self


def _check_installments(items: list[InstallmentIn] | None) -> None:
    if items is None:
        return
    numbers = [i.installment_no for i in items]
    if len(numbers) != len(set(numbers)):
        raise ValueError("installment_no doit être unique dans un plan")


class PaymentPlanCreate(BaseModel):
    """Création d'un plan de paiement dans une grille **brouillon**."""

    model_config = ConfigDict(extra="forbid")

    fee_schedule_id: uuid.UUID
    code: str = Field(pattern=r"^[A-Z0-9_-]{2,32}$", examples=["TRANCHES-3"])
    label_fr: str = Field(min_length=2, max_length=200, examples=["Trois tranches"])
    installment_count: int = Field(ge=1, le=12)
    discount_rate: Decimal = Field(default=Decimal("0"), ge=0, le=100, decimal_places=2)
    is_default: bool = False
    installments: list[InstallmentIn] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check(self) -> PaymentPlanCreate:
        _check_installments(self.installments)
        return self


class PaymentPlanUpdate(BaseModel):
    """Modification partielle ; `installments` fourni = remplace toute la liste."""

    model_config = ConfigDict(extra="forbid")

    code: str | None = Field(default=None, pattern=r"^[A-Z0-9_-]{2,32}$")
    label_fr: str | None = Field(default=None, min_length=2, max_length=200)
    installment_count: int | None = Field(default=None, ge=1, le=12)
    discount_rate: Decimal | None = Field(default=None, ge=0, le=100, decimal_places=2)
    is_default: bool | None = None
    installments: list[InstallmentIn] | None = None

    @model_validator(mode="after")
    def _check(self) -> PaymentPlanUpdate:
        _check_installments(self.installments)
        return self


def _same_currency(*amounts: MoneyIn | None) -> str | None:
    currencies = {m.currency for m in amounts if m is not None}
    if len(currencies) > 1:
        raise ValueError("tous les montants d'une grille doivent être dans la même devise")
    return currencies.pop() if currencies else None


class FeeScheduleCreate(ValidityPeriod):
    """Création d'une grille de frais (brouillon) : une grille officielle par année (D-A)."""

    model_config = ConfigDict(extra="forbid")

    programme_id: uuid.UUID
    speciality_id: uuid.UUID | None = Field(default=None, description="NULL = toutes.")
    study_year: int | None = Field(default=None, ge=1, le=6, description="NULL = toutes.")
    student_category: StudentCategory = "tunisian"
    academic_year: AcademicYear
    registration_fee: MoneyIn
    tuition_fee: MoneyIn
    other_fees: MoneyIn | None = None
    other_fees_label_fr: str | None = Field(default=None, max_length=500)
    notes_fr: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def _check(self) -> FeeScheduleCreate:
        _same_currency(self.registration_fee, self.tuition_fee, self.other_fees)
        if self.other_fees and self.other_fees.amount > 0 and not self.other_fees_label_fr:
            raise ValueError("other_fees_label_fr est obligatoire quand other_fees > 0")
        return self


class FeeScheduleUpdate(BaseModel):
    """Modification partielle d'une grille **brouillon** (If-Match obligatoire).

    La formation ne change pas (périmètre) : créer une autre grille si besoin.
    """

    model_config = ConfigDict(extra="forbid")

    speciality_id: uuid.UUID | None = None
    study_year: int | None = Field(default=None, ge=1, le=6)
    student_category: StudentCategory | None = None
    academic_year: AcademicYear | None = None
    registration_fee: MoneyIn | None = None
    tuition_fee: MoneyIn | None = None
    other_fees: MoneyIn | None = None
    other_fees_label_fr: str | None = Field(default=None, max_length=500)
    notes_fr: str | None = Field(default=None, max_length=4000)
    valid_from: date | None = None
    valid_to: date | None = None

    @model_validator(mode="after")
    def _check(self) -> FeeScheduleUpdate:
        _same_currency(self.registration_fee, self.tuition_fee, self.other_fees)
        return self


# --- Sorties -----------------------------------------------------------------------------------


class InstallmentOut(BaseModel):
    id: uuid.UUID
    installment_no: int
    due_date: date | None
    due_label_fr: str | None
    amount: Money


class PaymentPlanOut(BaseModel):
    id: uuid.UUID
    fee_schedule_id: uuid.UUID
    code: str
    label_fr: str
    installment_count: int
    discount_rate: str = Field(description='Remise en %, chaîne décimale (ex. "5.00").')
    is_default: bool
    installments: list[InstallmentOut]

    @classmethod
    def from_row(cls, plan: Any, installments: list[Any], currency: str) -> PaymentPlanOut:
        return cls(
            id=plan.id,
            fee_schedule_id=plan.fee_schedule_id,
            code=plan.code,
            label_fr=plan.label_fr,
            installment_count=plan.installment_count,
            discount_rate=f"{Decimal(plan.discount_rate):.2f}",
            is_default=plan.is_default,
            installments=[
                InstallmentOut(
                    id=i.id,
                    installment_no=i.installment_no,
                    due_date=i.due_date,
                    due_label_fr=i.due_label_fr,
                    amount=Money.of(i.amount, currency),
                )
                for i in sorted(installments, key=lambda x: x.installment_no)
            ],
        )


class FeeAmounts(BaseModel):
    """Montants d'une grille (le total vient de la colonne générée `annual_total`)."""

    registration_fee: Money
    tuition_fee: Money
    other_fees: Money
    other_fees_label_fr: str | None
    annual_total: Money = Field(description="Colonne générée : inscription + scolarité + autres.")


class FeeScheduleStaffOut(PublicationInfo, FeeAmounts):
    """Ligne complète pour le staff (tous statuts), avec ses plans de paiement."""

    id: uuid.UUID
    programme_id: uuid.UUID
    speciality_id: uuid.UUID | None
    study_year: int | None
    student_category: str
    academic_year: str
    currency: str
    notes_fr: str | None
    payment_plans: list[PaymentPlanOut]
    etag: str


class FeeScheduleOfficial(FeeAmounts):
    """Grille officielle (publiée et valide) vue par le public et l'agent."""

    id: uuid.UUID
    programme_id: uuid.UUID
    speciality_id: uuid.UUID | None
    study_year: int | None = Field(description="Année d'études ; null = toutes les années.")
    student_category: str
    academic_year: str
    scope: Literal["programme", "speciality"] = Field(
        description="Grille propre à la spécialité ou valable pour toute la formation."
    )
    notes_fr: str | None
    payment_plans: list[PaymentPlanOut]
    source: SourceRef


class FeesResponse(BaseModel):
    """Réponse de `GET /catalogue/programmes/{id}/fees` et de l'outil `get_fees`."""

    programme_id: uuid.UUID
    speciality_id: uuid.UUID | None
    academic_year: str
    as_of: date
    fee_schedules: list[FeeScheduleOfficial] = Field(
        description=(
            "Une grille par (année d'études, catégorie) : la plus spécifique l'emporte "
            "(spécialité > formation ; année d'études précise > toutes). Liste vide si aucune "
            "grille officielle pour cette année."
        )
    )
    available_academic_years: list[str] = Field(
        description="Années universitaires officielles disponibles à la date `as_of`."
    )
