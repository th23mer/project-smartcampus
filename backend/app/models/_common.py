"""Briques communes des modèles E2 (conventions SA-12 §0).

- Types annotés (`Text`, `timestamptz`, `uuid`) pour écrire `Mapped[...]` sans répéter le type SQL.
- Mixins : clé primaire uuid `gen_random_uuid()`, horodatage `created_at` / `updated_at`
  (maintenu par le trigger `set_updated_at()`, posé dans les migrations), bloc de publication
  à double validation (D-B).
- Fabriques de contraintes : CHECK d'énumération, CHECK de publication (`ck_<t>_validity`,
  `ck_<t>_submitted`, `ck_<t>_published`, `ck_<t>_four_eyes`), exclusion GiST « une seule
  version publiée valide à une date » (`ex_<t>_<règle>`).

Les CHECK et EXCLUDE reçoivent la **règle seule** (`name="four_eyes"`) : la convention de
nommage de `Base` ajoute le préfixe `ck_<table>_` / `ex_<table>_` (SA-7 D1).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import date, datetime
from typing import Annotated

from sqlalchemy import (
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import DATERANGE, ExcludeConstraint, Range
from sqlalchemy.orm import Mapped, declared_attr, mapped_column

#: UUID « nul » utilisé dans les clés d'exclusion à la place de NULL (NULL = NULL n'est pas vrai).
NIL_UUID = "00000000-0000-0000-0000-000000000000"

# --- Types annotés ------------------------------------------------------------------------------
Str = Annotated[str, mapped_column(Text)]
StrNull = Annotated[str | None, mapped_column(Text)]
TZ = Annotated[datetime, mapped_column(DateTime(timezone=True))]
TZNull = Annotated[datetime | None, mapped_column(DateTime(timezone=True))]
DateNull = Annotated[date | None, mapped_column(Date)]


def fk(
    target: str, *, nullable: bool = True, ondelete: str | None = None, **kw
) -> Mapped[uuid.UUID]:
    """Colonne uuid clé étrangère (nom `fk_<table>_<colonne>` donné par la convention)."""
    return mapped_column(ForeignKey(target, ondelete=ondelete), nullable=nullable, **kw)


def sql_list(values: Iterable[str]) -> str:
    """Rend `('a','b')` pour un `IN` SQL (valeurs de référentiel, jamais de saisie utilisateur)."""
    return "(" + ",".join(f"'{v}'" for v in values) + ")"


def enum_check(column: str, values: Iterable[str], name: str | None = None) -> CheckConstraint:
    """`CHECK (col IN (...))`, nommé `ck_<table>_<col>` par défaut (convention D8)."""
    return CheckConstraint(f"{column} IN {sql_list(values)}", name=name or column)


def enum_check_null(column: str, values: Iterable[str], name: str | None = None) -> CheckConstraint:
    """Variante pour une colonne facultative (NULL accepté)."""
    return CheckConstraint(
        f"{column} IS NULL OR {column} IN {sql_list(values)}", name=name or column
    )


# --- Mixins -------------------------------------------------------------------------------------
class UUIDPrimaryKey:
    """Clé primaire uuid générée par PostgreSQL."""

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()"), sort_order=-100
    )


class CreatedAt:
    """Horodatage de création seul (journaux append-only)."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), sort_order=100
    )


class Timestamps(CreatedAt):
    """`created_at` + `updated_at` (ce dernier maintenu par le trigger `set_updated_at`)."""

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), sort_order=101
    )


class PublicationBlock:
    """Bloc de publication à double validation (SA-12 §0, D-B, D-H).

    Cycle `draft → pending_review → published → archived` (rejet `pending_review → draft`).
    `valid_to` est **exclu** (D3) ; `validity` est la `daterange` générée `[valid_from, valid_to)`.
    Les contraintes associées sont produites par `publication_constraints()`.
    """

    publication_status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'draft'"), sort_order=50
    )
    valid_from: Mapped[date | None] = mapped_column(Date, sort_order=51)
    valid_to: Mapped[date | None] = mapped_column(Date, sort_order=52)
    validity: Mapped[Range[date] | None] = mapped_column(
        DATERANGE,
        Computed("daterange(valid_from, valid_to, '[)')", persisted=True),
        sort_order=53,
    )

    @declared_attr
    def created_by(cls) -> Mapped[uuid.UUID]:  # noqa: N805
        """Staff auteur de la ligne."""
        return mapped_column(ForeignKey("user_account.id"), nullable=False, sort_order=54)

    @declared_attr
    def submitted_by(cls) -> Mapped[uuid.UUID | None]:  # noqa: N805
        """Staff qui soumet à relecture (draft → pending_review)."""
        return mapped_column(ForeignKey("user_account.id"), sort_order=55)

    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), sort_order=56)

    @declared_attr
    def published_by(cls) -> Mapped[uuid.UUID | None]:  # noqa: N805
        """AUTRE staff qui publie (pending_review → published)."""
        return mapped_column(ForeignKey("user_account.id"), sort_order=57)

    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), sort_order=58)


def publication_constraints() -> tuple[CheckConstraint, ...]:
    """Les quatre CHECK du bloc de publication (noms `ck_<t>_<règle>`, SA-12 §0)."""
    return (
        enum_check("publication_status", ("draft", "pending_review", "published", "archived")),
        CheckConstraint(
            "valid_to IS NULL OR valid_from IS NULL OR valid_to > valid_from", name="validity"
        ),
        CheckConstraint(
            "publication_status NOT IN ('pending_review','published') OR "
            "(valid_from IS NOT NULL AND submitted_by IS NOT NULL AND submitted_at IS NOT NULL)",
            name="submitted",
        ),
        CheckConstraint(
            "publication_status <> 'published' OR "
            "(published_by IS NOT NULL AND published_at IS NOT NULL)",
            name="published",
        ),
        CheckConstraint("published_by IS NULL OR published_by <> submitted_by", name="four_eyes"),
    )


def coalesce_uuid(column: str):
    """Expression `COALESCE(col, uuid nul)` pour une clé d'exclusion avec colonne facultative."""
    return text(f"COALESCE({column}, '{NIL_UUID}'::uuid)")


def one_published_exclusion(*keys, name: str = "one_published") -> ExcludeConstraint:
    """Exclusion « une seule version publiée valide à une date » (SA-12 §0, D2).

    `EXCLUDE USING gist (<clés> WITH =, validity WITH &&) WHERE (publication_status = 'published')`.

    `keys` : noms de colonnes ou expressions (`coalesce_uuid(...)`), comparés par égalité
    (extension `btree_gist`).
    """
    elements = [(k, "=") for k in keys] + [("validity", "&&")]
    return ExcludeConstraint(
        *elements,
        name=name,
        using="gist",
        where=text("publication_status = 'published'"),
    )
