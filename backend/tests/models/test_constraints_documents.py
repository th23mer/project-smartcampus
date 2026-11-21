"""Contraintes de SA-14 (versions, chunks, file de jobs) et isolement du rôle RAG (SA-16)."""

from __future__ import annotations

import uuid

import psycopg
import pytest
from psycopg import errors

from tests.models.conftest import Seed, expect_error, ok, vec

pytestmark = pytest.mark.db


class Docs:
    """Petit jeu de données documentaire synthétique (dans la transaction du test)."""

    def __init__(self, db: psycopg.Connection, seed: Seed) -> None:
        self.db = db
        self.seed = seed
        self.model = db.execute(
            "INSERT INTO embedding_model (name, revision, dimension, is_active)"
            " VALUES (%s, 'r1', 1024, true) RETURNING id",
            (f"modele-demo-{uuid.uuid4().hex[:6]}",),
        ).fetchone()[0]
        self.document = db.execute(
            "INSERT INTO document (code, document_type, title_fr, institution_id,"
            " owner_user_id, created_by) VALUES (%s, 'official_guide', 'Guide de la Licence',"
            " %s, %s, %s) RETURNING id",
            (f"GUIDE-{seed.tag}", seed.institution, seed.r, seed.r),
        ).fetchone()[0]

    def version(self, n: int, sha: str, status: str = "draft", **kw) -> uuid.UUID:
        cols = {
            "document_id": self.document,
            "version_number": n,
            "content_sha256": sha,
            "storage_path": f"official/{uuid.uuid4()}.pdf",
            "original_filename": "guide.pdf",
            "mime_type": "application/pdf",
            "size_bytes": 2048,
            "language": "fr",
            "publication_status": status,
            "valid_from": "2026-09-01",
            "created_by": self.seed.r,
        }
        if status in ("pending_review", "published"):
            cols |= {"submitted_by": self.seed.r, "submitted_at": "2026-08-01"}
        if status == "published":
            cols |= {"published_by": self.seed.u, "published_at": "2026-08-02"}
        cols |= kw
        return self.db.execute(
            f"INSERT INTO document_version ({', '.join(cols)})"
            f" VALUES ({', '.join(['%s'] * len(cols))}) RETURNING id",
            tuple(cols.values()),
        ).fetchone()[0]

    def sync(self, version: uuid.UUID) -> uuid.UUID:
        """Job vector_sync + sa ligne sync_job, dans la même transaction (SA-14 §6.2)."""
        job = self.db.execute(
            "INSERT INTO job (job_type, dedup_key, concurrency_key) VALUES ('vector_sync', %s,"
            " %s) RETURNING id",
            (f"vector_sync:{version}:upsert:{self.model}:chunker-v1", f"document:{self.document}"),
        ).fetchone()[0]
        self.db.execute(
            "INSERT INTO sync_job (job_id, document_id, document_version_id, operation, trigger,"
            " embedding_model_id, chunker_version) VALUES (%s, %s, %s, 'upsert',"
            " 'version_created', %s, 'chunker-v1')",
            (job, self.document, version, self.model),
        )
        return job

    def chunk(self, version: uuid.UUID, job: uuid.UUID, i: int, content: str) -> None:
        self.db.execute(
            "INSERT INTO document_chunk (document_version_id, embedding_model_id, sync_job_id,"
            " chunk_index, content, token_count, char_start, char_end, section_path, embedding)"
            " VALUES (%s, %s, %s, %s, %s, 10, 0, 100, 'Chapitre 2 > Frais', %s)",
            (version, self.model, job, i, content, vec(i + 1)),
        )


@pytest.fixture
def docs(db: psycopg.Connection, seed: Seed) -> Docs:
    return Docs(db, seed)


def test_hash_de_version_unique_par_document(db: psycopg.Connection, docs: Docs) -> None:
    docs.version(1, "a" * 64)
    with pytest.raises(errors.UniqueViolation) as info, db.transaction():
        docs.version(2, "a" * 64)
    assert info.value.diag.constraint_name == "uq_document_version_document_id_content_sha256"
    # ON CONFLICT DO NOTHING : même fichier = version existante (idempotence du dépôt).
    rows = ok(
        db,
        "INSERT INTO document_version (document_id, version_number, content_sha256,"
        " storage_path, original_filename, mime_type, size_bytes, language, created_by)"
        " VALUES (%s, 3, %s, 'official/x.pdf', 'g.pdf', 'application/pdf', 1, 'fr', %s)"
        " ON CONFLICT (document_id, content_sha256) DO NOTHING RETURNING id",
        (docs.document, "a" * 64, docs.seed.r),
    )
    assert rows == []


def test_contenu_de_version_immuable(db: psycopg.Connection, docs: Docs) -> None:
    v = docs.version(1, "b" * 64)
    expect_error(
        db,
        "UPDATE document_version SET content_sha256 = %s WHERE id = %s",
        ("c" * 64, v),
        exc=errors.CheckViolation,
        constraint="gd_document_version_immutable",
    )
    ok(db, "UPDATE document_version SET change_note = 'Correction' WHERE id = %s", (v,))


def test_deux_versions_publiees_qui_se_chevauchent(db: psycopg.Connection, docs: Docs) -> None:
    docs.version(1, "d" * 64, "published")
    with pytest.raises(errors.ExclusionViolation) as info, db.transaction():
        docs.version(2, "e" * 64, "published", valid_from="2027-01-01")
    assert info.value.diag.constraint_name == "ex_document_version_validity"


def test_publication_a_quatre_yeux_des_documents(db: psycopg.Connection, docs: Docs) -> None:
    with pytest.raises(errors.CheckViolation) as info, db.transaction():
        docs.version(1, "f" * 64, "published", published_by=docs.seed.r)
    assert info.value.diag.constraint_name == "ck_document_version_four_eyes"


def test_version_publiee_figee_mais_etat_d_index_modifiable(
    db: psycopg.Connection, docs: Docs
) -> None:
    v = docs.version(1, "1" * 64, "published")
    ok(db, "UPDATE document_version SET index_status = 'removed' WHERE id = %s", (v,))
    expect_error(
        db,
        "UPDATE document_version SET change_note = 'x' WHERE id = %s",
        (v,),
        exc=errors.CheckViolation,
        constraint="gd_document_version_frozen",
    )


def test_job_vector_sync_sans_sync_job_refuse(db: psycopg.Connection) -> None:
    """Contrôle différé : vérifié en fin de transaction (ici forcé par SET CONSTRAINTS)."""
    with pytest.raises(errors.ForeignKeyViolation) as info, db.transaction():
        db.execute("INSERT INTO job (job_type) VALUES ('vector_sync')")
        db.execute("SET CONSTRAINTS ct_job_vector_sync_detail IMMEDIATE")
    assert info.value.diag.constraint_name == "ct_job_vector_sync_detail"
    db.execute("SET CONSTRAINTS ALL DEFERRED")
    ok(db, "INSERT INTO job (job_type, payload) VALUES ('email', '{\"notification_id\": 1}')")


def test_dedup_des_jobs_actifs(db: psycopg.Connection) -> None:
    sql = "INSERT INTO job (job_type, dedup_key, status) VALUES ('purge', 'purge:audio', %s)"
    ok(db, sql, ("queued",))
    expect_error(
        db, sql, ("running",), exc=errors.UniqueViolation, constraint="uq_job_dedup_active"
    )
    ok(db, sql, ("succeeded",))  # un job terminé ne bloque pas


def test_un_seul_modele_d_embedding_actif(db: psycopg.Connection, docs: Docs) -> None:
    expect_error(
        db,
        "INSERT INTO embedding_model (name, revision, dimension, is_active)"
        " VALUES ('autre', 'r1', 1024, true)",
        exc=errors.UniqueViolation,
        constraint="uq_embedding_model_active",
    )


def test_vue_rag_ne_montre_que_le_publie_indexe_valide(db: psycopg.Connection, docs: Docs) -> None:
    published = docs.version(
        1, "2" * 64, "published", index_status="indexed", valid_to="2099-01-01"
    )
    draft = docs.version(2, "3" * 64, index_status="indexed", valid_from="2099-01-01")
    for v in (published, draft):
        job = docs.sync(v)
        docs.chunk(v, job, 0, f"Frais d'inscription LIC-INFO version {v}")
        docs.chunk(v, job, 1, "Calendrier des examens")
    rows = db.execute(
        "SELECT DISTINCT document_version_id FROM v_searchable_chunk WHERE document_id = %s",
        (docs.document,),
    ).fetchall()
    assert rows == [(published,)]
    # Branche plein texte ('simple') et branche vectorielle (cosinus) sur la même vue.
    lex = db.execute(
        "SELECT content FROM v_searchable_chunk, websearch_to_tsquery('simple', 'LIC-INFO') q"
        " WHERE tsv @@ q AND document_id = %s",
        (docs.document,),
    ).fetchall()
    assert len(lex) == 1 and "LIC-INFO" in lex[0][0]
    nearest = db.execute(
        "SELECT content FROM v_searchable_chunk WHERE document_id = %s"
        " ORDER BY embedding <=> %s::vector LIMIT 1",
        (docs.document, vec(2)),
    ).fetchone()[0]
    assert nearest == "Calendrier des examens"
    state = db.execute(
        "SELECT current_version_id, index_status, last_job_status FROM v_document_index_state"
        " WHERE document_id = %s",
        (docs.document,),
    ).fetchone()
    assert state == (published, "indexed", "queued")


def test_suppression_d_un_brouillon_et_de_ses_chunks(db: psycopg.Connection, docs: Docs) -> None:
    v = docs.version(1, "4" * 64)
    job = docs.sync(v)
    docs.chunk(v, job, 0, "Texte")
    ok(db, "DELETE FROM document_version WHERE id = %s", (v,))
    n = db.execute("SELECT count(*) FROM document_chunk WHERE document_version_id = %s", (v,))
    assert n.fetchone()[0] == 0


def test_role_rag_ne_lit_que_la_vue(migrated: str, rag_url: str) -> None:
    with psycopg.connect(rag_url) as rag:
        rag.execute("SELECT count(*) FROM v_searchable_chunk").fetchone()
        for table in (
            "document_chunk",
            "document_version",
            "candidate_attachment",
            "message",
            "v_document_index_state",
        ):
            with pytest.raises(errors.InsufficientPrivilege), rag.transaction():
                rag.execute(f"SELECT 1 FROM {table} LIMIT 1")
        denied = (errors.ReadOnlySqlTransaction, errors.InsufficientPrivilege)
        with pytest.raises(denied), rag.transaction():
            rag.execute("CREATE TEMP TABLE t (x int)")
        rag.rollback()


def test_droits_poses_par_la_migration(owner_db: psycopg.Connection) -> None:
    """Le rôle RAG n'a qu'un seul droit : SELECT sur v_searchable_chunk."""
    rows = owner_db.execute(
        "SELECT table_name, privilege_type FROM information_schema.role_table_grants"
        " WHERE grantee = 'smartcampus_rag_reader'"
    ).fetchall()
    assert rows == [("v_searchable_chunk", "SELECT")]
    app = {
        (r[0], r[1])
        for r in owner_db.execute(
            "SELECT table_name, privilege_type FROM information_schema.role_table_grants"
            " WHERE grantee = 'smartcampus_app' AND table_name IN"
            " ('catalogue_audit_log','status_history','agent_action_log','consent')"
        ).fetchall()
    }
    assert not {p for _, p in app} & {"UPDATE", "DELETE", "TRUNCATE"}
    assert ("catalogue_audit_log", "INSERT") in app
