"""Migrations Alembic (SA-17) : base vide → head, head → base → head, aucune dérive."""

from __future__ import annotations

import psycopg
import pytest

from app.models import Base
from tests.models.conftest import run_alembic

pytestmark = pytest.mark.db

HEAD = "0006_refresh_token"  # SA-28 : jetons de renouvellement (23/11)
VIEWS = {"v_searchable_chunk", "v_document_index_state", "v_pending_validation"}


def _objects(url: str) -> tuple[set[str], set[str], set[str]]:
    with psycopg.connect(url) as conn:
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT table_name FROM information_schema.tables"
                " WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
            )
        }
        views = {
            r[0]
            for r in conn.execute(
                "SELECT table_name FROM information_schema.views WHERE table_schema = 'public'"
            )
        }
        functions = {
            r[0]
            for r in conn.execute(
                "SELECT p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace"
                " WHERE n.nspname = 'public' AND p.prolang = (SELECT oid FROM pg_language"
                " WHERE lanname = 'plpgsql')"
            )
        }
    return tables, views, functions


def test_upgrade_head_sur_base_vide(migrated: str) -> None:
    tables, views, functions = _objects(migrated)
    # Seulement les tables d'app.models (test_db_base.py ajoute des tables jetables zz_*).
    expected = {
        mp.local_table.name
        for mp in Base.registry.mappers
        if mp.class_.__module__.startswith("app.models.")
    }
    assert len(expected) == 54  # + catalogue_revision (SA-20, 0005), refresh_token (SA-28, 0006)
    assert tables == expected | {"alembic_version"}
    assert views == VIEWS
    assert functions == {
        "set_updated_at",
        "audit_catalogue",
        "guard_published_version",
        "guard_document_version_content",
        "check_vector_sync_job",
    }
    current = run_alembic("current")
    assert HEAD in current.stdout


def test_aucune_derive_modeles_migrations(migrated: str) -> None:
    """`alembic check` : les modèles et les migrations décrivent le même schéma."""
    result = run_alembic("check")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "No new upgrade operations detected" in result.stdout + result.stderr


def test_downgrade_base_puis_upgrade_head(migrated: str) -> None:
    down = run_alembic("downgrade", "base")
    assert down.returncode == 0, down.stderr
    tables, views, functions = _objects(migrated)
    assert tables == {"alembic_version"}
    assert views == set()
    assert functions == set()
    up = run_alembic("upgrade", "head")
    assert up.returncode == 0, up.stderr
    tables, views, _ = _objects(migrated)
    assert len(tables) == 55 and views == VIEWS


def test_sql_hors_ligne_genere(migrated: str) -> None:
    """`alembic upgrade head --sql` produit un script relisible (revue, livraison)."""
    result = run_alembic("upgrade", "head", "--sql")
    assert result.returncode == 0, result.stderr
    assert "CREATE VIEW v_searchable_chunk" in result.stdout
    assert "EXCLUDE USING gist" in result.stdout
