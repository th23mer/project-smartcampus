"""Fixtures des tests de schéma (SA-17) : base `db-test` réelle, migrations Alembic.

Variables lues (fichier `.env` racine, SA-16) :
- `TEST_MIGRATION_DATABASE_URL` : rôle propriétaire (Alembic) ;
- `TEST_DATABASE_URL` : rôle applicatif `smartcampus_app` (les tests de contraintes tournent
  avec ce rôle, comme le backend) ;
- `TEST_RAG_READER_DATABASE_URL` : rôle lecture seule de l'outil RAG.

Sans ces variables, les tests sont sautés. Lancement :
    set -a; . ../.env; set +a; ~/.local/bin/uv run pytest tests/models
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest

BACKEND_DIR = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.db


def _env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        pytest.skip(f"{name} non définie (base de test SA-16 requise)")
    return value


def plain_url(url: str) -> str:
    """URL SQLAlchemy (`postgresql+asyncpg://`, `postgresql+psycopg://`) → URL libpq."""
    scheme, rest = url.split("://", 1)
    return "postgresql://" + rest if scheme.startswith("postgresql") else url


def run_alembic(*args: str) -> subprocess.CompletedProcess[str]:
    """Lance `alembic <args>` sur la base de test (sous-processus : réglages isolés)."""
    env = dict(os.environ)
    env["MIGRATION_DATABASE_URL"] = _env("TEST_MIGRATION_DATABASE_URL")
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture(scope="session")
def owner_url() -> str:
    return plain_url(_env("TEST_MIGRATION_DATABASE_URL"))


@pytest.fixture(scope="session")
def app_url() -> str:
    return plain_url(_env("TEST_DATABASE_URL"))


@pytest.fixture(scope="session")
def rag_url() -> str:
    return plain_url(_env("TEST_RAG_READER_DATABASE_URL"))


@pytest.fixture(scope="session")
def migrated(test_db_schema: str, owner_url: str) -> str:
    """Base vide puis `upgrade head` une fois par session (db-test est jetable, SA-16) :
    fixture de session commune `test_db_schema` (SA-22)."""
    return owner_url


@pytest.fixture
def db(migrated: str, app_url: str) -> Iterator[psycopg.Connection]:
    """Connexion du rôle applicatif dans une transaction annulée à la fin du test."""
    with psycopg.connect(app_url) as conn:
        conn.execute("SELECT 1")  # ouvre la transaction implicite : savepoints ensuite
        try:
            yield conn
        finally:
            conn.rollback()


@pytest.fixture
def owner_db(migrated: str) -> Iterator[psycopg.Connection]:
    """Connexion du rôle propriétaire (transaction annulée à la fin du test)."""
    with psycopg.connect(migrated) as conn:
        conn.execute("SELECT 1")
        try:
            yield conn
        finally:
            conn.rollback()


def expect_error(
    conn: psycopg.Connection,
    sql: str,
    params: Any = None,
    *,
    exc: type[Exception],
    constraint: str | None = None,
) -> psycopg.Error:
    """Exécute `sql` dans un savepoint et vérifie l'erreur (type et nom de contrainte)."""
    with pytest.raises(exc) as info, conn.transaction():
        conn.execute(sql, params)
    err = info.value
    if constraint is not None:
        assert err.diag.constraint_name == constraint, err.diag.message_primary
    return err


def ok(conn: psycopg.Connection, sql: str, params: Any = None) -> list[tuple]:
    """Exécute `sql` dans un savepoint (doit réussir) et renvoie les lignes éventuelles."""
    with conn.transaction():
        cur = conn.execute(sql, params)
        return cur.fetchall() if cur.description else []


def vec(seed: int, dim: int = 1024) -> str:
    """Vecteur littéral pgvector déterministe (données synthétiques)."""
    values = [0.0] * dim
    values[seed % dim] = 1.0
    values[(seed * 7 + 3) % dim] += 0.5
    return "[" + ",".join(f"{v:g}" for v in values) + "]"


class Seed:
    """Jeu de données synthétique minimal, inséré dans la transaction du test."""

    def __init__(self, conn: psycopg.Connection) -> None:
        self.conn = conn
        tag = uuid.uuid4().hex[:6].upper()
        self.tag = tag
        # R rédige et soumet, U relit et publie (double validation, D-B).
        self.r = self.user(f"redacteur-{tag}@demo.local")
        self.u = self.user(f"relecteur-{tag}@demo.local")
        self.institution = self.one(
            "INSERT INTO institution (code, name_fr, city, publication_status, valid_from,"
            " created_by, submitted_by, submitted_at, published_by, published_at)"
            " VALUES (%s, 'Institut de démo', 'Sfax', 'published', '2020-09-01',"
            " %s, %s, now(), %s, now()) RETURNING id",
            (f"I{tag}", self.r, self.r, self.u),
        )
        self.programme = self.programme_row(f"LIC-{tag}")
        self.speciality = self.one(
            "INSERT INTO speciality (programme_id, code, name_fr, created_by)"
            " VALUES (%s, 'GL', 'Génie logiciel', %s) RETURNING id",
            (self.programme, self.r),
        )

    def one(self, sql: str, params: Any = None) -> Any:
        return self.conn.execute(sql, params).fetchone()[0]

    def user(self, email: str, account_type: str = "staff") -> uuid.UUID:
        return self.one(
            "INSERT INTO user_account (email, password_hash, full_name, account_type)"
            " VALUES (%s, 'x', 'Compte fictif', %s) RETURNING id",
            (email, account_type),
        )

    def programme_row(self, code: str) -> uuid.UUID:
        return self.one(
            "INSERT INTO programme (institution_id, code, name_fr, programme_type,"
            " duration_years, created_by) VALUES (%s, %s, 'Licence démo', 'licence', 3, %s)"
            " RETURNING id",
            (self.institution, code, self.r),
        )

    def fee(self, academic_year: str, status: str = "draft", **kw: Any) -> uuid.UUID:
        """Grille de frais ; `status='published'` = soumise par R, publiée par U."""
        cols = {
            "programme_id": self.programme,
            "academic_year": academic_year,
            "registration_fee": 300,
            "annual_tuition_fee": 6900,
            "publication_status": status,
            "valid_from": "2026-03-01",
            "created_by": self.r,
        }
        if status in ("pending_review", "published", "archived"):
            cols |= {"submitted_by": self.r, "submitted_at": "2026-02-01"}
        if status in ("published", "archived"):
            cols |= {"published_by": self.u, "published_at": "2026-02-02"}
        cols |= kw
        names = ", ".join(cols)
        marks = ", ".join(["%s"] * len(cols))
        return self.one(
            f"INSERT INTO fee_schedule ({names}) VALUES ({marks}) RETURNING id",
            tuple(cols.values()),
        )

    def candidate(self) -> uuid.UUID:
        user = self.user(f"candidat-{uuid.uuid4().hex[:8]}@demo.local", "candidate")
        return self.one(
            "INSERT INTO candidate_profile (user_id, candidate_type) VALUES (%s, 'new_bachelor')"
            " RETURNING id",
            (user,),
        )


@pytest.fixture
def seed(db: psycopg.Connection) -> Seed:
    return Seed(db)


@pytest.fixture
def make_seed() -> Callable[[psycopg.Connection], Seed]:
    return Seed
