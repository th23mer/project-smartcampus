"""Tests du seed de démonstration (SA-18) sur la base de test `db-test`.

La session repart d'une base vide (`alembic downgrade base && upgrade head`), lance le seed
DEUX fois en sous-processus (comme `make seed`), vérifie l'idempotence puis les requêtes
« publié et valide à la date D ». À la fin, la base de test est remise à vide (les lignes
publiées du seed ne peuvent pas être supprimées autrement).

Une seule session pytest à la fois sur db-test (verrou flock, voir le brief de la vague 2) :
    set -a; . ../.env; set +a
    flock <scratchpad>/db-test.lock ~/.local/bin/uv run pytest tests/test_seed.py
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest

from tests.conftest import db_test_env, run_python, table_counts

pytestmark = pytest.mark.db

BACKEND_DIR = Path(__file__).resolve().parents[1]
SEED = BACKEND_DIR / "scripts" / "seed.py"
#: Date de référence de la démo (les données sont construites autour du 17/11/2026).
DEMO_DATE = "2026-11-17"
ADMIN_ID = "5eed0000-0000-4000-8000-000000000006"

PUBLISHABLE = (
    "institution",
    "programme",
    "speciality",
    "curriculum",
    "admission_condition",
    "fee_schedule",
    "bridge",
)


# Aides partagées (tests/conftest.py, SA-22).
_env = db_test_env
_run = run_python
_counts = table_counts


@pytest.fixture(scope="module")
def seeded(demo_seed: dict) -> dict:
    """Base vide → seed n°1 → seed n°2 (fixture de session `demo_seed`, partagée avec le
    scénario de bout en bout SA-22) ; comptes et sorties des deux passes."""
    return demo_seed


@pytest.fixture
def db(seeded: dict) -> Iterator[psycopg.Connection]:
    with psycopg.connect(seeded["url"]) as conn:
        yield conn
        conn.rollback()


def _scalar(conn: psycopg.Connection, sql: str, params: object = None):
    return conn.execute(sql, params).fetchone()[0]


# --- Idempotence ---------------------------------------------------------------------------------
def test_seed_deux_fois_memes_comptes(seeded: dict) -> None:
    assert seeded["counts_1"] == seeded["counts_2"]
    assert "0 ligne(s) créée(s)" in seeded["second"]
    assert "0 déjà présente(s)" in seeded["first"]


def test_volumes_attendus(seeded: dict) -> None:
    c = seeded["counts_2"]
    assert c["institution"] == 2
    assert c["programme"] == 11  # 4 Licences + 1 brouillon, 2 Prépas, ING, 3 ISB
    assert c["speciality"] == 11
    assert c["user_account"] == 9  # 6 staff + 3 candidats
    assert c["role"] == 6
    assert c["candidate_profile"] == 3
    assert c["embedding_model"] == 1
    assert c["curriculum_subject"] > 150
    assert c["catalogue_audit_log"] > 0
    # Aucune table hors périmètre n'est remplie (conversations, dossiers, jobs…).
    for table in ("conversation", "preregistration", "job", "document", "message"):
        assert c[table] == 0


# --- Publié et valide à la date D ---------------------------------------------------------------
def _official_fees(conn: psycopg.Connection, year: str) -> int:
    return _scalar(
        conn,
        "SELECT count(*) FROM fee_schedule f JOIN programme p ON p.id = f.programme_id"
        " WHERE f.academic_year = %s AND f.publication_status = 'published'"
        " AND f.validity @> %s::date AND p.publication_status = 'published'"
        " AND p.validity @> %s::date",
        (year, DEMO_DATE, DEMO_DATE),
    )


def test_frais_2026_2027_visibles(db: psycopg.Connection) -> None:
    assert _official_fees(db, "2026-2027") == 12
    row = db.execute(
        "SELECT f.registration_fee, f.annual_tuition_fee, f.other_fees, f.annual_total"
        " FROM fee_schedule f JOIN programme p ON p.id = f.programme_id"
        " WHERE p.code = 'LIC-INFO' AND f.speciality_id IS NULL AND f.academic_year = '2026-2027'"
        " AND f.publication_status = 'published' AND f.validity @> %s::date",
        (DEMO_DATE,),
    ).fetchall()
    assert row == [(Decimal("300.000"), Decimal("6200.000"), Decimal("150.000"), Decimal("6650"))]


def test_frais_2027_2028_non_publies(db: psycopg.Connection) -> None:
    assert _official_fees(db, "2027-2028") == 0
    statuses = dict(
        db.execute(
            "SELECT publication_status, count(*) FROM fee_schedule"
            " WHERE academic_year = '2027-2028' GROUP BY 1"
        ).fetchall()
    )
    assert statuses == {"pending_review": 11, "draft": 1}
    # Soumises (submitted_by renseigné) mais pas encore publiées : en attente des quatre yeux.
    assert (
        _scalar(
            db,
            "SELECT count(*) FROM fee_schedule WHERE academic_year = '2027-2028'"
            " AND publication_status = 'pending_review'"
            " AND submitted_by IS NOT NULL AND published_by IS NULL",
        )
        == 11
    )


def test_version_expiree_et_archivee_invisibles(db: psycopg.Connection) -> None:
    # Les grilles 2025-2026 ont été publiées puis ont expiré le 01/09/2026.
    assert (
        _scalar(
            db,
            "SELECT count(*) FROM fee_schedule WHERE academic_year = '2025-2026'"
            " AND publication_status = 'published' AND upper(validity) = '2026-09-01'",
        )
        == 2
    )
    assert _official_fees(db, "2025-2026") == 0
    assert _official_fees(db, "2024-2025") == 0  # archivée
    # Cursus LIC-INFO/GL : la v2022 a expiré, seule la v2026 est officielle.
    labels = [
        r[0]
        for r in db.execute(
            "SELECT c.version_label FROM curriculum c JOIN programme p ON p.id = c.programme_id"
            " JOIN speciality s ON s.id = c.speciality_id"
            " WHERE p.code = 'LIC-INFO' AND s.code = 'GL' AND c.publication_status = 'published'"
            " AND c.validity @> %s::date",
            (DEMO_DATE,),
        )
    ]
    assert labels == ["v2026"]
    # Conditions LIC-INFO 2025-2026 expirées.
    assert (
        _scalar(
            db,
            "SELECT count(*) FROM admission_condition ac JOIN programme p ON p.id = ac.programme_id"
            " WHERE p.code = 'LIC-INFO' AND ac.academic_year = '2025-2026'"
            " AND ac.publication_status = 'published' AND ac.validity @> %s::date",
            (DEMO_DATE,),
        )
        == 0
    )


def test_brouillons_et_relecture_invisibles(db: psycopg.Connection) -> None:
    visible_programmes = {
        r[0]
        for r in db.execute(
            "SELECT code FROM programme WHERE publication_status = 'published'"
            " AND validity @> %s::date",
            (DEMO_DATE,),
        )
    }
    assert "LIC-IA" not in visible_programmes
    assert len(visible_programmes) == 10
    assert (
        _scalar(
            db,
            "SELECT publication_status FROM speciality WHERE code = 'IADS'",
        )
        == "pending_review"
    )
    # Conditions de la rentrée 2027-2028 : LIC-GC en relecture, LIC-MECA en brouillon.
    rows = dict(
        db.execute(
            "SELECT p.code, ac.publication_status FROM admission_condition ac"
            " JOIN programme p ON p.id = ac.programme_id"
            " WHERE ac.academic_year = '2027-2028' AND p.code IN ('LIC-GC', 'LIC-MECA')"
        ).fetchall()
    )
    assert rows == {"LIC-GC": "pending_review", "LIC-MECA": "draft"}


# --- Quatre yeux, audit, rôles ------------------------------------------------------------------
@pytest.mark.parametrize("table", PUBLISHABLE)
def test_quatre_yeux_respectes(db: psycopg.Connection, table: str) -> None:
    published, same, by_admin = db.execute(
        f"SELECT count(*) FILTER (WHERE published_by IS NOT NULL),"
        f" count(*) FILTER (WHERE published_by = submitted_by),"
        f" count(*) FILTER (WHERE published_by = %s::uuid) FROM {table}",
        (ADMIN_ID,),
    ).fetchone()
    assert published > 0
    assert same == 0
    assert by_admin == 0  # D-H : l'admin ne publie jamais


def test_audit_avec_auteur(db: psycopg.Connection) -> None:
    actions = dict(
        db.execute(
            "SELECT action, count(*) FILTER (WHERE actor_id IS NULL) FROM catalogue_audit_log"
            " GROUP BY 1"
        ).fetchall()
    )
    assert {"insert", "submit", "publish", "archive"} <= set(actions)
    assert all(missing == 0 for missing in actions.values())
    history = _scalar(
        db,
        "SELECT count(*) FROM status_history WHERE to_status = 'published'"
        " AND requires_human AND actor_type = 'staff'",
    )
    assert history > 0


def test_comptes_et_roles_fixes(db: psycopg.Connection) -> None:
    rows = db.execute(
        "SELECT u.id::text, r.code FROM user_account u JOIN user_role ur ON ur.user_id = u.id"
        " JOIN role r ON r.id = ur.role_id ORDER BY u.id"
    ).fetchall()
    assert ("5eed0000-0000-4000-8000-000000000001", "iit_academic_lead") in rows
    assert ("5eed0000-0000-4000-8000-000000000002", "iit_academic_lead") in rows
    assert ("5eed0000-0000-4000-8000-000000000005", "direction") in rows
    assert ("5eed0000-0000-4000-8000-000000000101", "candidate") in rows
    emails = [r[0] for r in db.execute("SELECT email FROM user_account")]
    assert all(e.endswith("@example.tn") for e in emails)
    perimeter = _scalar(
        db,
        "SELECT i.code FROM role r JOIN institution i ON i.id = r.institution_id"
        " WHERE r.code = 'isb_academic_lead'",
    )
    assert perimeter == "ISB"


def test_modele_embedding_actif(db: psycopg.Connection) -> None:
    rows = db.execute("SELECT dimension, distance FROM embedding_model WHERE is_active").fetchall()
    assert rows == [(1024, "cosine")]


# --- Données utiles aux démos ---------------------------------------------------------------------
def test_echeanciers_exacts(db: psycopg.Connection) -> None:
    """La somme des tranches = total annuel (remise déduite pour le paiement comptant)."""
    bad = db.execute(
        "SELECT f.id, pp.code FROM payment_plan pp JOIN fee_schedule f ON f.id = pp.fee_schedule_id"
        " JOIN payment_installment pi ON pi.payment_plan_id = pp.id"
        " GROUP BY f.id, pp.code, pp.discount_rate, f.annual_total, pp.installment_count"
        " HAVING sum(pi.amount) <> round(f.annual_total * (100 - pp.discount_rate) / 100, 3)"
        " OR count(*) <> pp.installment_count"
    ).fetchall()
    assert bad == []


def test_preselection_eligibilite(db: psycopg.Connection) -> None:
    """Pré-filtre Q5 de SA-12 (rentrée 2027-2028) : un verdict différent par candidat."""
    rows = db.execute(
        """
        WITH c AS (
          SELECT u.email, r.bac_section, r.overall_average,
                 (SELECT jsonb_object_agg(s.subject_key, s.grade) FROM academic_record_subject s
                   WHERE s.academic_record_id = r.id AND s.subject_key IS NOT NULL) AS notes
          FROM user_account u
          JOIN candidate_profile cp ON cp.user_id = u.id
          JOIN academic_record r ON r.candidate_profile_id = cp.id AND r.record_type = 'bac')
        SELECT c.email, p.code
        FROM c CROSS JOIN admission_condition ac JOIN programme p ON p.id = ac.programme_id
        WHERE ac.applicant_category = 'new_bachelor' AND ac.entry_level = 1
          AND ac.academic_year = '2027-2028'
          AND ac.publication_status = 'published' AND ac.validity @> %s::date
          AND (ac.accepted_bac_sections IS NULL OR c.bac_section = ANY (ac.accepted_bac_sections))
          AND c.overall_average >= ac.min_average
          AND NOT EXISTS (SELECT 1 FROM admission_subject_requirement rq
                           WHERE rq.admission_condition_id = ac.id
                             AND coalesce((c.notes ->> rq.subject_key)::numeric, -1) < rq.min_grade)
        """,
        (DEMO_DATE,),
    ).fetchall()
    eligible: dict[str, set[str]] = {}
    for email, code in rows:
        eligible.setdefault(email, set()).add(code)
    c1 = eligible["candidat.demo1@example.tn"]
    c2 = eligible["candidat.demo2@example.tn"]
    c3 = eligible["candidat.demo3@example.tn"]
    assert {"LIC-INFO", "PREPA-MP"} <= c1
    assert c2 == {"LIC-GEST", "LIC-COMM"}  # série Économie et gestion : rien à l'IIT
    assert "PREPA-PT" in c3 and "PREPA-MP" not in c3  # moyenne 11,40 < 12


def test_passerelles_path_explorer(db: psycopg.Connection) -> None:
    rows = db.execute(
        "SELECT sp.code, tp.code, b.access_mode FROM bridge b"
        " JOIN programme sp ON sp.id = b.source_programme_id"
        " JOIN programme tp ON tp.id = b.target_programme_id"
        " WHERE b.publication_status = 'published' AND b.validity @> %s::date",
        (DEMO_DATE,),
    ).fetchall()
    assert ("PREPA-MP", "ING", "automatic") in rows
    assert ("LIC-INFO", "ING", "on_application") in rows
    assert len(rows) == 8  # l'archivée et celle en relecture sont exclues


# --- Réinitialisation (dernier test du module : il recrée la base) -----------------------------
def test_reset_recree_la_meme_base(seeded: dict) -> None:
    """`--reset` : downgrade base + upgrade head (rôle propriétaire) puis seed, mêmes comptes."""
    res = _run(
        [
            str(SEED),
            "--reset",
            "--quiet",
            "--database-url",
            _env("TEST_DATABASE_URL"),
            "--migration-database-url",
            _env("TEST_MIGRATION_DATABASE_URL"),
        ]
    )
    assert res.returncode == 0, res.stderr
    assert "0 déjà présente(s)" in res.stdout
    assert _counts(seeded["url"]) == seeded["counts_2"]
