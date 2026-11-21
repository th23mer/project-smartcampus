"""Contraintes du catalogue (SA-12) : cas refusés / acceptés repris du §3 de SA-12.

Rôle applicatif `smartcampus_app`, transaction annulée à la fin de chaque test.
"""

from __future__ import annotations

import psycopg
import pytest
from psycopg import errors

from tests.models.conftest import Seed, expect_error, ok

pytestmark = pytest.mark.db


def test_publication_par_le_meme_staff_refusee(db: psycopg.Connection, seed: Seed) -> None:
    """Quatre yeux : published_by = submitted_by → ck_fee_schedule_four_eyes."""
    expect_error(
        db,
        "INSERT INTO fee_schedule (programme_id, academic_year, registration_fee,"
        " annual_tuition_fee, publication_status, valid_from, created_by, submitted_by,"
        " submitted_at, published_by, published_at)"
        " VALUES (%s, '2027-2028', 1, 1, 'published', '2026-11-01', %s, %s, now(), %s, now())",
        (seed.programme, seed.r, seed.r, seed.r),
        exc=errors.CheckViolation,
        constraint="ck_fee_schedule_four_eyes",
    )


def test_soumission_sans_soumetteur_refusee(db: psycopg.Connection, seed: Seed) -> None:
    fee = seed.fee("2027-2028")
    expect_error(
        db,
        "UPDATE fee_schedule SET publication_status = 'pending_review' WHERE id = %s",
        (fee,),
        exc=errors.CheckViolation,
        constraint="ck_fee_schedule_submitted",
    )


def test_publication_sans_publieur_refusee(db: psycopg.Connection, seed: Seed) -> None:
    fee = seed.fee("2027-2028", "pending_review")
    expect_error(
        db,
        "UPDATE fee_schedule SET publication_status = 'published' WHERE id = %s",
        (fee,),
        exc=errors.CheckViolation,
        constraint="ck_fee_schedule_published",
    )


def test_deux_grilles_publiees_qui_se_chevauchent_refusees(
    db: psycopg.Connection, seed: Seed
) -> None:
    seed.fee("2027-2028", "published", valid_from="2026-11-01")
    with pytest.raises(errors.ExclusionViolation) as info, db.transaction():
        seed.fee("2027-2028", "published", valid_from="2027-01-01")
    assert info.value.diag.constraint_name == "ex_fee_schedule_one_published"


def test_deux_annees_publiees_en_parallele_acceptees(db: psycopg.Connection, seed: Seed) -> None:
    """D-A : 2027-2028 et 2028-2029 publiées et valides en même temps."""
    seed.fee("2027-2028", "published", valid_from="2026-11-01")
    seed.fee("2028-2029", "published", valid_from="2026-11-01")
    n = db.execute(
        "SELECT count(*) FROM fee_schedule WHERE programme_id = %s"
        " AND publication_status = 'published' AND validity @> date '2027-01-15'",
        (seed.programme,),
    ).fetchone()[0]
    assert n == 2


def test_grille_specialite_et_grille_formation_coexistent(
    db: psycopg.Connection, seed: Seed
) -> None:
    """COALESCE(speciality_id, uuid nul) : la grille « formation » et la grille GL diffèrent."""
    seed.fee("2027-2028", "published")
    seed.fee("2027-2028", "published", speciality_id=seed.speciality)
    with pytest.raises(errors.ExclusionViolation), db.transaction():
        seed.fee("2027-2028", "published", valid_from="2026-06-01")


def test_publication_par_un_second_staff_et_audit(db: psycopg.Connection, seed: Seed) -> None:
    """Publication acceptée ; l'audit garde l'action `publish`, l'auteur et les colonnes."""
    fee = seed.fee("2027-2028", "pending_review")
    db.execute("SELECT set_config('app.current_user_id', %s, true)", (str(seed.u),))
    db.execute(
        "UPDATE fee_schedule SET publication_status = 'published', published_by = %s,"
        " published_at = now() WHERE id = %s",
        (seed.u, fee),
    )
    row = db.execute(
        "SELECT action, actor_id, changed_fields FROM catalogue_audit_log"
        " WHERE row_id = %s AND action = 'publish'",
        (fee,),
    ).fetchone()
    assert row == ("publish", seed.u, ["publication_status", "published_at", "published_by"])
    actions = {
        r[0]
        for r in db.execute(
            "SELECT action FROM catalogue_audit_log WHERE row_id = %s", (fee,)
        ).fetchall()
    }
    assert actions == {"insert", "publish"}


def test_rejet_journalise_reject(db: psycopg.Connection, seed: Seed) -> None:
    fee = seed.fee("2027-2028", "pending_review")
    db.execute(
        "UPDATE fee_schedule SET publication_status = 'draft', submitted_by = NULL,"
        " submitted_at = NULL WHERE id = %s",
        (fee,),
    )
    actions = [
        r[0]
        for r in db.execute(
            "SELECT action FROM catalogue_audit_log WHERE row_id = %s", (fee,)
        ).fetchall()
    ]
    assert "reject" in actions


def test_mise_a_jour_sans_changement_non_journalisee(db: psycopg.Connection, seed: Seed) -> None:
    fee = seed.fee("2027-2028")
    db.execute("UPDATE fee_schedule SET notes_fr = notes_fr WHERE id = %s", (fee,))
    n = db.execute("SELECT count(*) FROM catalogue_audit_log WHERE row_id = %s", (fee,))
    assert n.fetchone()[0] == 1  # seulement l'insert


def test_ancienne_cle_de_bac_anglaise_refusee(db: psycopg.Connection, seed: Seed) -> None:
    """C1 : clés françaises ; `math` est refusée."""
    sql = (
        "INSERT INTO admission_condition (programme_id, entry_level, applicant_category,"
        " required_diploma, accepted_bac_sections, academic_year, summary_fr, created_by)"
        " VALUES (%s, 1, 'new_bachelor', 'baccalaureate', %s, '2027-2028', 'Résumé', %s)"
    )
    expect_error(
        db,
        sql,
        (seed.programme, ["math"], seed.r),
        exc=errors.CheckViolation,
        constraint="ck_admission_condition_accepted_bac_sections",
    )
    ok(db, sql, (seed.programme, ["mathematiques", "sciences_informatique"], seed.r))


def test_conditions_par_annee_universitaire(db: psycopg.Connection, seed: Seed) -> None:
    """D-I : conditions publiées pour deux rentrées en parallèle ; même rentrée refusée."""
    sql = (
        "INSERT INTO admission_condition (programme_id, entry_level, applicant_category,"
        " required_diploma, academic_year, summary_fr, publication_status, valid_from,"
        " created_by, submitted_by, submitted_at, published_by, published_at)"
        " VALUES (%s, 1, 'new_bachelor', 'baccalaureate', %s, 'Résumé', 'published',"
        " '2026-03-01', %s, %s, now(), %s, now())"
    )
    ok(db, sql, (seed.programme, "2027-2028", seed.r, seed.r, seed.u))
    ok(db, sql, (seed.programme, "2028-2029", seed.r, seed.r, seed.u))
    expect_error(
        db,
        sql,
        (seed.programme, "2027-2028", seed.r, seed.r, seed.u),
        exc=errors.ExclusionViolation,
        constraint="ex_admission_condition_one_published",
    )


def test_lignes_non_publiees_absentes_du_filtre_officiel(
    db: psycopg.Connection, seed: Seed
) -> None:
    seed.fee("2025-2026", "archived", valid_to="2026-09-01")
    seed.fee("2026-2027")  # brouillon
    seed.fee("2027-2028", "pending_review")
    published = seed.fee("2028-2029", "published")
    rows = db.execute(
        "SELECT id FROM fee_schedule WHERE programme_id = %s"
        " AND publication_status = 'published' AND validity @> date '2027-01-15'",
        (seed.programme,),
    ).fetchall()
    assert rows == [(published,)]


def test_colonnes_generees(db: psycopg.Connection, seed: Seed) -> None:
    fee = seed.fee("2027-2028", other_fees=150, other_fees_label_fr="Assurance")
    total, validity = db.execute(
        "SELECT annual_total, validity::text FROM fee_schedule WHERE id = %s", (fee,)
    ).fetchone()
    assert total == 7350
    assert validity == "[2026-03-01,)"


def test_autres_frais_sans_libelle_refuses(db: psycopg.Connection, seed: Seed) -> None:
    with pytest.raises(errors.CheckViolation) as info, db.transaction():
        seed.fee("2027-2028", other_fees=150)
    assert info.value.diag.constraint_name == "ck_fee_schedule_other_label"


def test_specialite_d_une_autre_formation_refusee(db: psycopg.Connection, seed: Seed) -> None:
    """FK composite (speciality_id, programme_id) → speciality(id, programme_id)."""
    other = seed.programme_row(f"ING-{seed.tag}")
    with pytest.raises(errors.ForeignKeyViolation) as info, db.transaction():
        seed.fee("2027-2028", programme_id=other, speciality_id=seed.speciality)
    assert info.value.diag.constraint_name == "fk_fee_schedule_speciality"


def test_version_publiee_figee(db: psycopg.Connection, seed: Seed) -> None:
    """D17 : on ne modifie pas une version publiée ; raccourcir valid_to et archiver : OK."""
    fee = seed.fee("2027-2028", "published")
    expect_error(
        db,
        "UPDATE fee_schedule SET annual_tuition_fee = 9999 WHERE id = %s",
        (fee,),
        exc=errors.CheckViolation,
        constraint="gd_fee_schedule_frozen",
    )
    expect_error(
        db,
        "UPDATE fee_schedule SET publication_status = 'draft' WHERE id = %s",
        (fee,),
        exc=errors.CheckViolation,
        constraint="gd_fee_schedule_frozen",
    )
    expect_error(
        db,
        "DELETE FROM fee_schedule WHERE id = %s",
        (fee,),
        exc=errors.CheckViolation,
        constraint="gd_fee_schedule_frozen",
    )
    ok(db, "UPDATE fee_schedule SET valid_to = '2027-09-01' WHERE id = %s", (fee,))
    expect_error(
        db,
        "UPDATE fee_schedule SET valid_to = '2028-09-01' WHERE id = %s",
        (fee,),
        exc=errors.CheckViolation,
        constraint="gd_fee_schedule_frozen",
    )
    ok(db, "UPDATE fee_schedule SET publication_status = 'archived' WHERE id = %s", (fee,))


def test_brouillon_supprimable_avec_ses_enfants(db: psycopg.Connection, seed: Seed) -> None:
    fee = seed.fee("2027-2028")
    plan = seed.one(
        "INSERT INTO payment_plan (fee_schedule_id, code, label_fr, installment_count)"
        " VALUES (%s, 'TRANCHES-3', '3 tranches', 3) RETURNING id",
        (fee,),
    )
    db.execute(
        "INSERT INTO payment_installment (payment_plan_id, installment_no, due_label_fr, amount)"
        " VALUES (%s, 1, 'À l''inscription', 2570)",
        (plan,),
    )
    ok(db, "DELETE FROM fee_schedule WHERE id = %s", (fee,))
    n = db.execute("SELECT count(*) FROM payment_plan WHERE id = %s", (plan,)).fetchone()[0]
    assert n == 0


def test_un_seul_plan_par_defaut(db: psycopg.Connection, seed: Seed) -> None:
    fee = seed.fee("2027-2028")
    sql = (
        "INSERT INTO payment_plan (fee_schedule_id, code, label_fr, installment_count,"
        " is_default) VALUES (%s, %s, 'Plan', 1, true)"
    )
    ok(db, sql, (fee, "COMPTANT"))
    expect_error(
        db,
        sql,
        (fee, "TRANCHES-3"),
        exc=errors.UniqueViolation,
        constraint="uq_payment_plan_default",
    )


def test_cursus_unique_meme_sans_specialite(db: psycopg.Connection, seed: Seed) -> None:
    """UNIQUE NULLS NOT DISTINCT (programme, spécialité, libellé de version)."""
    sql = (
        "INSERT INTO curriculum (programme_id, version_label, academic_year, created_by)"
        " VALUES (%s, 'v2026', '2026-2027', %s)"
    )
    ok(db, sql, (seed.programme, seed.r))
    expect_error(
        db,
        sql,
        (seed.programme, seed.r),
        exc=errors.UniqueViolation,
        constraint="uq_curriculum_version",
    )


def test_heures_totales_et_prerequis(db: psycopg.Connection, seed: Seed) -> None:
    cur = seed.one(
        "INSERT INTO curriculum (programme_id, version_label, academic_year, created_by)"
        " VALUES (%s, 'v2026', '2026-2027', %s) RETURNING id",
        (seed.programme, seed.r),
    )
    subj = seed.one(
        "INSERT INTO subject (institution_id, code, name_fr) VALUES (%s, 'ALGO1', 'Algo 1')"
        " RETURNING id",
        (seed.institution,),
    )
    cs, hours = db.execute(
        "INSERT INTO curriculum_subject (curriculum_id, subject_id, semester, coefficient,"
        " ects_credits, hours_lecture, hours_tutorial) VALUES (%s, %s, 1, 2, 5, 21, 21)"
        " RETURNING id, hours_total",
        (cur, subj),
    ).fetchone()
    assert hours == 42
    expect_error(
        db,
        "INSERT INTO prerequisite (curriculum_id, curriculum_subject_id) VALUES (%s, %s)",
        (cur, cs),
        exc=errors.CheckViolation,
        constraint="ck_prerequisite_content",
    )


def test_updated_at_maintenu_par_trigger(db: psycopg.Connection, seed: Seed) -> None:
    sub = seed.one(
        "INSERT INTO subject (institution_id, code, name_fr, created_at, updated_at)"
        " VALUES (%s, 'PROG1', 'Programmation', '2020-01-01', '2020-01-01') RETURNING id",
        (seed.institution,),
    )
    db.execute("UPDATE subject SET name_fr = 'Programmation C' WHERE id = %s", (sub,))
    year = db.execute("SELECT extract(year FROM updated_at) FROM subject WHERE id = %s", (sub,))
    assert year.fetchone()[0] > 2020


def test_journal_d_audit_append_only(db: psycopg.Connection, seed: Seed) -> None:
    """SA-16 : le rôle applicatif ne peut ni modifier ni supprimer le journal."""
    expect_error(
        db, "UPDATE catalogue_audit_log SET action = 'update'", exc=errors.InsufficientPrivilege
    )
    expect_error(db, "DELETE FROM catalogue_audit_log", exc=errors.InsufficientPrivilege)
