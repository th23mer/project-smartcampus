"""Contraintes de SA-13 (conversations, dossiers, rendez-vous, journaux) et droits SA-16."""

from __future__ import annotations

import uuid

import psycopg
import pytest
from psycopg import errors

from tests.models.conftest import Seed, expect_error, ok

pytestmark = pytest.mark.db


def _visitor(db: psycopg.Connection) -> uuid.UUID:
    return db.execute(
        "INSERT INTO visitor_session (token_hash, last_seen_at, idle_expires_at,"
        " hard_expires_at, quota_window_start) VALUES (%s, now(), now() + interval '24 hours',"
        " now() + interval '7 days', now()) RETURNING id",
        (uuid.uuid4().bytes,),
    ).fetchone()[0]


def _slot(db: psycopg.Connection, seed: Seed, start: str, end: str) -> uuid.UUID:
    return db.execute(
        "INSERT INTO appointment_slot (institution_id, appointment_type, staff_user_id,"
        " starts_at, ends_at, mode, created_by) VALUES (%s, 'interview', %s, %s, %s,"
        " 'onsite', %s) RETURNING id",
        (seed.institution, seed.u, start, end, seed.r),
    ).fetchone()[0]


def test_un_seul_rdv_actif_par_creneau(db: psycopg.Connection, seed: Seed) -> None:
    slot = _slot(db, seed, "2027-03-01 09:00+01", "2027-03-01 09:30+01")
    sql = (
        "INSERT INTO appointment (appointment_type, slot_id, candidate_profile_id, status,"
        " booked_via) VALUES ('interview', %s, %s, %s, 'agent_tool')"
    )
    ok(db, sql, (slot, seed.candidate(), "scheduled"))
    expect_error(
        db,
        sql,
        (slot, seed.candidate(), "confirmed"),
        exc=errors.UniqueViolation,
        constraint="uq_appointment_active_slot",
    )
    ok(db, sql, (slot, seed.candidate(), "cancelled"))  # un RDV annulé ne bloque pas


def test_rdv_planifie_sans_creneau_refuse(db: psycopg.Connection, seed: Seed) -> None:
    expect_error(
        db,
        "INSERT INTO appointment (appointment_type, candidate_profile_id, status, booked_via)"
        " VALUES ('interview', %s, 'scheduled', 'staff')",
        (seed.candidate(),),
        exc=errors.CheckViolation,
        constraint="ck_appointment_slot_required",
    )


def test_creneaux_qui_se_chevauchent_pour_un_responsable(
    db: psycopg.Connection, seed: Seed
) -> None:
    _slot(db, seed, "2027-03-01 09:00+01", "2027-03-01 10:00+01")
    with pytest.raises(errors.ExclusionViolation) as info, db.transaction():
        _slot(db, seed, "2027-03-01 09:30+01", "2027-03-01 10:30+01")
    assert info.value.diag.constraint_name == "ex_appointment_slot_staff_overlap"
    ok(db, "SELECT 1")
    _slot(db, seed, "2027-03-01 10:00+01", "2027-03-01 10:30+01")  # bornes contiguës : OK


def test_decision_d_admission_sans_decideur_refusee(db: psycopg.Connection, seed: Seed) -> None:
    cand = seed.candidate()
    user = db.execute("SELECT user_id FROM candidate_profile WHERE id = %s", (cand,)).fetchone()[0]
    consent = db.execute(
        "INSERT INTO consent (user_id, consent_type, granted, policy_version, channel)"
        " VALUES (%s, 'data_processing', true, 'privacy-v1', 'web_form') RETURNING id",
        (user,),
    ).fetchone()[0]
    sql = (
        "INSERT INTO preregistration (candidate_profile_id, programme_id, academic_year,"
        " status, consent_id, decided_by) VALUES (%s, %s, '2027-2028', %s, %s, %s)"
    )
    expect_error(
        db,
        sql,
        (cand, seed.programme, "admitted", consent, None),
        exc=errors.CheckViolation,
        constraint="ck_preregistration_human_decision",
    )
    ok(db, sql, (cand, seed.programme, "admitted", consent, seed.u))
    expect_error(  # doublon actif pour la même formation et la même année
        db,
        sql,
        (cand, seed.programme, "draft", consent, None),
        exc=errors.UniqueViolation,
        constraint="uq_preregistration_active",
    )


def test_conversation_a_un_seul_proprietaire(db: psycopg.Connection, seed: Seed) -> None:
    visitor = _visitor(db)
    sql = "INSERT INTO conversation (visitor_session_id, user_id) VALUES (%s, %s)"
    expect_error(
        db, sql, (visitor, seed.r), exc=errors.CheckViolation, constraint="ck_conversation_owner"
    )
    expect_error(
        db, sql, (None, None), exc=errors.CheckViolation, constraint="ck_conversation_owner"
    )
    ok(db, sql, (visitor, None))


def test_message_codes_de_langue_sa5(db: psycopg.Connection) -> None:
    visitor = _visitor(db)
    conv = db.execute(
        "INSERT INTO conversation (visitor_session_id) VALUES (%s) RETURNING id", (visitor,)
    ).fetchone()[0]
    sql = (
        "INSERT INTO message (conversation_id, seq, role, content, detected_language)"
        " VALUES (%s, %s, 'user', 'chnowa el frais?', %s)"
    )
    ok(db, sql, (conv, 1, "aeb_latn"))
    expect_error(
        db,
        sql,
        (conv, 2, "arabizi"),
        exc=errors.CheckViolation,
        constraint="ck_message_detected_language",
    )
    expect_error(
        db,
        sql,
        (conv, 1, "fr"),
        exc=errors.UniqueViolation,
        constraint="uq_message_conversation_id_seq",
    )


def test_status_history_append_only(db: psycopg.Connection, seed: Seed) -> None:
    ok(
        db,
        "INSERT INTO status_history (entity_type, entity_id, to_status, actor_type,"
        " actor_user_id, requires_human) VALUES ('fee_schedule', gen_random_uuid(),"
        " 'published', 'staff', %s, true)",
        (seed.u,),
    )
    expect_error(
        db,
        "INSERT INTO status_history (entity_type, entity_id, to_status, actor_type,"
        " requires_human) VALUES ('preregistration', gen_random_uuid(), 'admitted',"
        " 'ai_agent', true)",
        exc=errors.CheckViolation,
        constraint="ck_status_history_human_actor",
    )
    expect_error(db, "UPDATE status_history SET reason = 'x'", exc=errors.InsufficientPrivilege)
    expect_error(db, "DELETE FROM status_history", exc=errors.InsufficientPrivilege)
    expect_error(db, "UPDATE consent SET granted = false", exc=errors.InsufficientPrivilege)


def test_journal_des_agents_purge_et_suppression_conversation(db: psycopg.Connection) -> None:
    """agent_action_log : UPDATE seulement de arguments/result (D33) ; SET NULL à la purge."""
    visitor = _visitor(db)
    conv = db.execute(
        "INSERT INTO conversation (visitor_session_id) VALUES (%s) RETURNING id", (visitor,)
    ).fetchone()[0]
    log = db.execute(
        "INSERT INTO agent_action_log (conversation_id, agent, step_type, tool_name, arguments,"
        " status, duration_ms, actor_type, visitor_session_id) VALUES (%s, 'orientation_agent',"
        " 'tool_call', 'get_fees', '{\"programme\": \"LIC-INFO\"}', 'succeeded', 12, 'visitor',"
        " %s) RETURNING id",
        (conv, visitor),
    ).fetchone()[0]
    ok(db, "UPDATE agent_action_log SET arguments = NULL, result = NULL WHERE id = %s", (log,))
    expect_error(
        db,
        "UPDATE agent_action_log SET status = 'failed' WHERE id = %s",
        (log,),
        exc=errors.InsufficientPrivilege,
    )
    expect_error(db, "DELETE FROM agent_action_log", exc=errors.InsufficientPrivilege)
    # Purge visiteur : la conversation part, le journal reste (conversation_id → NULL).
    ok(db, "DELETE FROM conversation WHERE id = %s", (conv,))
    row = db.execute(
        "SELECT conversation_id, duration_ms FROM agent_action_log WHERE id = %s", (log,)
    ).fetchone()
    assert row == (None, 12)


def test_purge_d_une_piece_ne_bloque_pas_le_dossier(db: psycopg.Connection, seed: Seed) -> None:
    """FK entrantes vers candidate_attachment en ON DELETE SET NULL (cohérence 16/11)."""
    cand = seed.candidate()
    att = db.execute(
        "INSERT INTO candidate_attachment (candidate_profile_id, attachment_type,"
        " content_sha256, storage_path, original_filename, mime_type, size_bytes, uploaded_by)"
        " VALUES (%s, 'bac_transcript', %s, %s, 'releve.pdf', 'application/pdf', 1000, %s)"
        " RETURNING id",
        (cand, "a" * 64, f"private/candidates/{uuid.uuid4()}.pdf", seed.r),
    ).fetchone()[0]
    rec = db.execute(
        "INSERT INTO academic_record (candidate_profile_id, record_type, bac_section, year,"
        " source, attachment_id) VALUES (%s, 'bac', 'mathematiques', 2026, 'declared', %s)"
        " RETURNING id",
        (cand, att),
    ).fetchone()[0]
    cur = db.execute(
        "INSERT INTO curriculum (programme_id, version_label, academic_year, created_by)"
        " VALUES (%s, 'v1', '2026-2027', %s) RETURNING id",
        (seed.programme, seed.r),
    ).fetchone()[0]
    eq = db.execute(
        "INSERT INTO equivalence_request (candidate_profile_id, target_curriculum_id,"
        " target_level, origin_institution_name, origin_programme_label,"
        " transcript_attachment_id) VALUES (%s, %s, 2, 'Fac démo', 'L1 Info', %s) RETURNING id",
        (cand, cur, att),
    ).fetchone()[0]
    ok(db, "DELETE FROM candidate_attachment WHERE id = %s", (att,))
    assert db.execute(
        "SELECT attachment_id FROM academic_record WHERE id = %s", (rec,)
    ).fetchone() == (None,)
    assert db.execute(
        "SELECT transcript_attachment_id FROM equivalence_request WHERE id = %s", (eq,)
    ).fetchone() == (None,)


def test_bac_section_obligatoire_pour_un_releve_de_bac(db: psycopg.Connection, seed: Seed) -> None:
    expect_error(
        db,
        "INSERT INTO academic_record (candidate_profile_id, record_type, year, source)"
        " VALUES (%s, 'bac', 2026, 'declared')",
        (seed.candidate(),),
        exc=errors.CheckViolation,
        constraint="ck_academic_record_bac_section_set",
    )


def test_idempotence_par_appelant(db: psycopg.Connection, seed: Seed) -> None:
    key = uuid.uuid4()
    sql = (
        "INSERT INTO idempotency_key (user_id, idempotency_key, method, route, request_hash,"
        " state, expires_at) VALUES (%s, %s, 'POST', '/preregistrations', '\\x00',"
        " 'in_progress', now() + interval '24 hours')"
    )
    ok(db, sql, (seed.r, key))
    expect_error(
        db,
        sql,
        (seed.r, key),
        exc=errors.UniqueViolation,
        constraint="uq_idempotency_key_caller_key",
    )
    ok(db, sql, (seed.u, key))  # même clé, autre appelant : OK


def test_question_qcm_utilisable_seulement_validee(db: psycopg.Connection) -> None:
    expect_error(
        db,
        "INSERT INTO mcq_question (topic, difficulty, stem, options, correct_keys, origin,"
        " status) VALUES ('algèbre', 2, 'Énoncé', '[]', '{a}', 'ai_generated', 'validated')",
        exc=errors.CheckViolation,
        constraint="ck_mcq_question_human_validation",
    )


def test_vue_validations_en_attente(db: psycopg.Connection) -> None:
    db.execute(
        "INSERT INTO mcq_question (topic, difficulty, stem, options, correct_keys, origin)"
        " VALUES ('algèbre', 2, 'Énoncé', '[]', '{a}', 'staff')"
    )
    kinds = {r[0] for r in db.execute("SELECT kind FROM v_pending_validation").fetchall()}
    assert "mcq_question" in kinds
