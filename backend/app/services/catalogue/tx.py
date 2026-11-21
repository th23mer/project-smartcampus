"""Transactions staff du catalogue et traduction des erreurs PostgreSQL (SA-21, noyau partagé).

Usage dans un service d'écriture (SA-20, SA-21) :

    async with staff_transaction(session, user):
        row = FeeSchedule(...)
        session.add(row)
        await session.flush()          # une violation de contrainte devient une AppError
    # ici la transaction est validée (commit)

`staff_transaction` :
1. vérifie que l'utilisateur a un compte staff (`user_account`), cible des FK d'auteur ;
2. pose `app.current_user_id` pour la **seule** transaction courante
   (`set_config(..., true)` = `SET LOCAL`), lu par le trigger `audit_catalogue()` (SA-12 C5) ;
3. valide à la sortie, annule sur exception ;
4. traduit les erreurs PostgreSQL connues en `AppError` au format SA-5 (`translate_db_error`).

Correspondance des contraintes (noms SA-12 §0) :

| Erreur PostgreSQL | Code SA-5 |
|---|---|
| `ex_<t>_*` (exclusion, 23P01) | `VALIDITY_OVERLAP` 409 |
| `gd_<t>_frozen` (garde des versions publiées) | `INVALID_STATUS_TRANSITION` 409 (*) |
| `ck_<t>_four_eyes` | `FOUR_EYES_REQUIRED` 403 |
| autre CHECK (23514), NOT NULL (23502), donnée invalide (22xxx) | `VALIDATION_ERROR` 422 |
| FK à l'insertion (23503, cible absente) | `VALIDATION_ERROR` 422 |
| FK à la suppression (23503, ligne encore référencée) | `CONFLICT` 409 |
| unicité (23505) | `CONFLICT` 409 |

(*) avec `details.reason = published_version_frozen`.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ErrorCode
from app.core.security import CurrentUser
from app.models import UserAccount


@dataclass(frozen=True)
class PgErrorInfo:
    """Informations utiles extraites d'une erreur du pilote (asyncpg ou psycopg)."""

    sqlstate: str | None
    constraint: str | None
    table: str | None
    column: str | None
    message: str
    #: Détail PostgreSQL (ex. « Key (id)=(…) is still referenced from table "x". »).
    detail: str = ""


def pg_error_info(exc: BaseException) -> PgErrorInfo:
    """Extrait SQLSTATE, contrainte, table et colonne d'une `DBAPIError` SQLAlchemy.

    asyncpg : l'exception d'origine est la cause de `exc.orig` (attributs `sqlstate`,
    `constraint_name`…). psycopg : `exc.orig.diag`.
    """
    candidates: list[Any] = []
    orig = getattr(exc, "orig", None)
    for obj in (orig, getattr(orig, "__cause__", None), exc):
        if obj is not None:
            candidates.append(obj)
    sqlstate = constraint = table = column = None
    message = detail = ""
    for obj in candidates:
        diag = getattr(obj, "diag", None)
        sqlstate = sqlstate or getattr(obj, "sqlstate", None) or getattr(obj, "pgcode", None)
        constraint = constraint or getattr(obj, "constraint_name", None)
        table = table or getattr(obj, "table_name", None)
        column = column or getattr(obj, "column_name", None)
        if diag is not None:
            sqlstate = sqlstate or getattr(diag, "sqlstate", None)
            constraint = constraint or getattr(diag, "constraint_name", None)
            table = table or getattr(diag, "table_name", None)
            column = column or getattr(diag, "column_name", None)
        message = message or str(getattr(obj, "message", "") or "")
        detail = detail or str(
            getattr(obj, "detail", None) or getattr(diag, "message_detail", None) or ""
        )
    if not message:
        message = str(orig or exc)
    return PgErrorInfo(
        sqlstate=str(sqlstate) if sqlstate else None,
        constraint=constraint,
        table=table,
        column=column,
        message=message,
        detail=detail,
    )


def translate_db_error(exc: BaseException) -> AppError | None:
    """Traduit une erreur PostgreSQL connue en `AppError` ; `None` si elle n'est pas prévue
    (elle remontera alors en 500 INTERNAL_ERROR, trace dans les journaux seulement)."""
    info = pg_error_info(exc)
    state = info.sqlstate or ""
    name = info.constraint or ""
    base: dict[str, Any] = {"constraint": name or None, "table": info.table}

    if name.startswith("gd_"):
        return AppError(
            ErrorCode.INVALID_STATUS_TRANSITION,
            message="Version publiée figée : créez une nouvelle version pour la modifier.",
            details={**base, "reason": "published_version_frozen"},
        )
    if state == "23P01" or name.startswith("ex_"):
        return AppError(ErrorCode.VALIDITY_OVERLAP, details=base)
    if name.endswith("_four_eyes"):
        return AppError(ErrorCode.FOUR_EYES_REQUIRED, details=base)
    if state == "23514":  # check_violation
        return AppError(
            ErrorCode.VALIDATION_ERROR,
            details=[{"field": _field_of(name, info.table), "issue": name or "check_violation"}],
        )
    if state == "23502":  # not_null_violation
        return AppError(
            ErrorCode.VALIDATION_ERROR, details=[{"field": info.column, "issue": "required"}]
        )
    if state == "23503":  # foreign_key_violation
        # Suppression d'une ligne encore référencée : « update or delete on table … » (le
        # « still referenced » est dans le détail avec asyncpg, pas dans le message).
        text_ = f"{info.message} {info.detail}"
        if any(
            marker in text_
            for marker in ("still referenced", "encore référencée", "update or delete on table")
        ):
            return AppError(
                ErrorCode.CONFLICT,
                message="Cette ligne est encore utilisée par d'autres données.",
                details={**base, "reason": "still_referenced"},
            )
        return AppError(
            ErrorCode.VALIDATION_ERROR,
            details=[
                {"field": _field_of(name, info.table), "issue": "not_found", "location": "body"}
            ],
        )
    if state == "23505":  # unique_violation
        return AppError(
            ErrorCode.CONFLICT,
            message="Une ligne avec ces valeurs existe déjà.",
            details={**base, "reason": "duplicate"},
        )
    if state.startswith("22"):  # data_exception (format de date, débordement numérique…)
        return AppError(ErrorCode.VALIDATION_ERROR, details=[{"field": None, "issue": state}])
    return None


def _field_of(constraint: str, table: str | None) -> str | None:
    """`ck_fee_schedule_other_label` → `other_label` ; `fk_payment_plan_fee_schedule_id` →
    `fee_schedule_id` (indication pour le front, pas un contrat)."""
    if not constraint:
        return None
    if constraint in _COMPOSITE_FK_FIELDS:
        return _COMPOSITE_FK_FIELDS[constraint]
    for prefix in ("ck_", "fk_", "uq_", "ex_"):
        if constraint.startswith(prefix):
            rest = constraint[len(prefix) :]
            if table and rest.startswith(table + "_"):
                rest = rest[len(table) + 1 :]
            if prefix == "fk_" and rest.endswith("speciality"):
                # FK composites (spécialité, formation) nommées sans `_id` (SA-17) : on renvoie
                # le champ de la requête (`speciality_id`, `source_speciality_id`…). SA-22.
                return rest + "_id"
            return rest
    return constraint


#: FK composites dont le nom ne dit pas la colonne de la requête (SA-22).
_COMPOSITE_FK_FIELDS: dict[str, str] = {"fk_prerequisite_target": "curriculum_subject_id"}


async def set_current_user(session: AsyncSession, user_id: uuid.UUID | None) -> None:
    """`SET LOCAL app.current_user_id` (auteur du journal d'audit, transaction courante)."""
    await session.execute(
        text("SELECT set_config('app.current_user_id', :uid, true)"),
        {"uid": str(user_id) if user_id else ""},
    )


async def ensure_staff_account(session: AsyncSession, user: CurrentUser) -> None:
    """Le staff doit exister dans `user_account` (cible de created_by, submitted_by…).

    Sinon 403 FORBIDDEN : l'auth simulée accepte n'importe quel UUID, la base non.
    """
    account_type = await session.scalar(
        select(UserAccount.account_type).where(UserAccount.id == user.id)
    )
    if account_type != "staff":
        raise AppError(
            ErrorCode.FORBIDDEN,
            message="Compte staff inconnu : action impossible.",
            details={"reason": "unknown_staff_account"},
        )


@asynccontextmanager
async def staff_transaction(
    session: AsyncSession, user: CurrentUser, *, check_account: bool = True
) -> AsyncIterator[AsyncSession]:
    """Transaction d'écriture staff : auteur posé, commit à la sortie, erreurs traduites."""
    try:
        if check_account:
            await ensure_staff_account(session, user)
        await set_current_user(session, user.id)
        yield session
        await session.commit()
    except AppError:
        await session.rollback()
        raise
    except DBAPIError as exc:
        await session.rollback()
        translated = translate_db_error(exc)
        if translated is None:
            raise
        raise translated from exc
    except BaseException:
        await session.rollback()
        raise


async def flush_or_translate(session: AsyncSession) -> None:
    """`session.flush()` en traduisant immédiatement l'erreur (utile pour enchaîner un
    contrôle après l'écriture). Hors `staff_transaction`, l'appelant gère le rollback."""
    try:
        await session.flush()
    except DBAPIError as exc:
        translated = translate_db_error(exc)
        if translated is None:
            raise
        raise translated from exc


__all__ = [
    "PgErrorInfo",
    "ensure_staff_account",
    "flush_or_translate",
    "pg_error_info",
    "set_current_user",
    "staff_transaction",
    "translate_db_error",
]
