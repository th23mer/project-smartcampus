# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "asyncpg==0.30.0",
#     "psycopg[binary]==3.2.10",
#     "sqlalchemy[asyncio]==2.0.43",
# ]
# ///
"""SA-16 · Vérification de la configuration PostgreSQL de SmartCampus AI.

Prouve, sur la base de développement et sur la base de test :
  1. la connexion des trois rôles par TCP avec mot de passe (asyncpg pour l'appli et le RAG,
     psycopg 3 pour Alembic), avec les URL du fichier .env ;
  2. la version du serveur (>= 15) et la présence des extensions vector, btree_gist, pgcrypto ;
  3. que smartcampus_app ne peut faire AUCUN DDL, mais a le DML sur une table créée plus tard
     par smartcampus_owner (privilèges par défaut) ;
  4. que smartcampus_rag_reader ne peut rien écrire et ne lit qu'une vue explicitement accordée.

Lancement (depuis la racine du dépôt) :  infra/db/check_db.sh  [--target dev|test|all]
Code de sortie 0 si tout est conforme, 1 sinon.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import psycopg
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import create_async_engine

RACINE = Path(__file__).resolve().parents[2]
EXTENSIONS_ATTENDUES = ("vector", "btree_gist", "pgcrypto")
SONDE = "zz_sa16_probe"          # table temporaire de test, supprimée à la fin
VUE_SONDE = "zz_sa16_probe_view"  # vue de test (imite v_searchable_chunk)

resultats: list[tuple[bool, str]] = []


def verifier(ok: bool, libelle: str) -> None:
    """Enregistre et affiche le résultat d'une vérification."""
    resultats.append((ok, libelle))
    print(f"  [{'OK' if ok else 'ÉCHEC'}] {libelle}")


def lire_env(chemin: Path) -> dict[str, str]:
    """Lit un fichier .env simple (CLE=valeur, commentaires #)."""
    valeurs: dict[str, str] = {}
    for ligne in chemin.read_text(encoding="utf-8").splitlines():
        ligne = ligne.strip()
        if not ligne or ligne.startswith("#") or "=" not in ligne:
            continue
        cle, valeur = ligne.split("=", 1)
        valeurs[cle.strip()] = valeur.strip().strip('"').strip("'")
    return valeurs


def url_brute(url_sqlalchemy: str) -> str:
    """postgresql+asyncpg://... -> postgresql://... (format attendu par asyncpg et psycopg)."""
    parties = urlsplit(url_sqlalchemy)
    return urlunsplit(("postgresql", *parties[1:]))


async def refuse(conn: asyncpg.Connection, sql: str) -> tuple[bool, str]:
    """Exécute `sql` et renvoie (True, code SQLSTATE) si PostgreSQL le refuse."""
    try:
        async with conn.transaction():
            await conn.execute(sql)
    except asyncpg.PostgresError as exc:
        return True, f"{exc.sqlstate} {type(exc).__name__}"
    return False, "accepté (anormal)"


async def verifier_cible(nom: str, env: dict[str, str], prefixe: str) -> None:
    url_app = url_brute(env[f"{prefixe}DATABASE_URL"])
    url_owner = url_brute(env[f"{prefixe}MIGRATION_DATABASE_URL"])
    url_rag = url_brute(env[f"{prefixe}RAG_READER_DATABASE_URL"])
    print(f"\n=== Base « {nom} » ({urlsplit(url_app).hostname}:{urlsplit(url_app).port}"
          f"/{urlsplit(url_app).path.lstrip('/')}) ===")

    # 0. URL telles quelles, via SQLAlchemy (comme backend/app/core/db.py et Alembic) -----
    moteur_async = create_async_engine(env[f"{prefixe}DATABASE_URL"])
    async with moteur_async.connect() as c:
        qui = (await c.execute(text("SELECT current_user"))).scalar_one()
    await moteur_async.dispose()
    verifier(qui == "smartcampus_app",
             f"SQLAlchemy async + asyncpg avec {prefixe}DATABASE_URL -> {qui}")
    moteur_sync = create_engine(env[f"{prefixe}MIGRATION_DATABASE_URL"])
    with moteur_sync.connect() as c:
        qui = c.execute(text("SELECT current_user")).scalar_one()
    moteur_sync.dispose()
    verifier(qui == "smartcampus_owner",
             f"SQLAlchemy sync + psycopg 3 avec {prefixe}MIGRATION_DATABASE_URL -> {qui}")

    # 1. Connexions des trois rôles -------------------------------------------------------
    owner = psycopg.connect(url_owner, autocommit=True)
    app = await asyncpg.connect(url_app)
    rag = await asyncpg.connect(url_rag)
    try:
        for role, conn in (("smartcampus_app", app), ("smartcampus_rag_reader", rag)):
            qui, su = await conn.fetchrow(
                "SELECT current_user, (SELECT rolsuper FROM pg_roles WHERE rolname = current_user)")
            verifier(qui == role and not su, f"connexion asyncpg de {role} (superutilisateur : {su})")
        qui, su, version_num, version = owner.execute(
            "SELECT current_user, (SELECT rolsuper FROM pg_roles WHERE rolname = current_user),"
            " current_setting('server_version_num')::int, current_setting('server_version')").fetchone()
        verifier(qui == "smartcampus_owner" and not su,
                 f"connexion psycopg de smartcampus_owner (superutilisateur : {su})")
        verifier(version_num >= 150000, f"PostgreSQL {version} (>= 15 exigé par SA-12)")

        # 2. Extensions ----------------------------------------------------------------------
        lignes = await app.fetch(
            "SELECT e.extname, e.extversion, pg_get_userbyid(e.extowner) AS proprio, "
            "(SELECT rolsuper FROM pg_roles WHERE oid = e.extowner) AS proprio_su "
            "FROM pg_extension e WHERE e.extname = ANY($1::text[]) ORDER BY 1",
            list(EXTENSIONS_ATTENDUES))
        trouvees = {r["extname"]: r for r in lignes}
        for ext in EXTENSIONS_ATTENDUES:
            r = trouvees.get(ext)
            # vector n'est pas « trusted » : créée par le superutilisateur à l'init (signalé).
            proprio_attendu = "postgres_superuser" if ext == "vector" else "smartcampus_owner"
            ok_proprio = r is not None and (
                r["proprio_su"] if proprio_attendu == "postgres_superuser"
                else r["proprio"] == proprio_attendu)
            verifier(ok_proprio,
                     f"extension {ext} " + (f"{r['extversion']} (propriétaire {r['proprio']})"
                                            if r else "ABSENTE"))
        if "vector" in trouvees:
            majeur, mineur = (int(x) for x in trouvees["vector"]["extversion"].split(".")[:2])
            verifier((majeur, mineur) >= (0, 8),
                     "pgvector >= 0.8 (hnsw.iterative_scan utilisé par SA-14)")

        # 3. Schéma et base : aucun droit implicite pour PUBLIC -----------------------------
        public_create, proprio_schema, public_connect = await app.fetchrow(
            "SELECT has_schema_privilege('public', 'public', 'CREATE'),"
            " (SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname = 'public'),"
            " has_database_privilege('public', current_database(), 'CONNECT')")
        verifier(not public_create, "PUBLIC n'a pas CREATE sur le schéma public")
        verifier(proprio_schema == "smartcampus_owner", f"schéma public possédé par {proprio_schema}")
        verifier(not public_connect, "PUBLIC n'a pas CONNECT sur la base (accès nominatif)")

        # 4. smartcampus_app : aucun DDL ------------------------------------------------------
        for sql, quoi in (
            ("CREATE TABLE zz_interdit (id int)", "CREATE TABLE"),
            ("CREATE SCHEMA zz_interdit", "CREATE SCHEMA"),
            ("CREATE TEMP TABLE zz_interdit (id int)", "CREATE TEMP TABLE"),
            ("CREATE EXTENSION IF NOT EXISTS hstore", "CREATE EXTENSION"),
        ):
            ok, detail = await refuse(app, sql)
            verifier(ok, f"smartcampus_app refusé pour {quoi} : {detail}")

        # 5. Privilèges par défaut : table créée APRÈS l'init par le propriétaire ------------
        owner.execute(f"DROP VIEW IF EXISTS {VUE_SONDE}; DROP TABLE IF EXISTS {SONDE}")
        owner.execute(f"CREATE TABLE {SONDE} (id uuid PRIMARY KEY DEFAULT gen_random_uuid(),"
                      f" label text NOT NULL, embedding vector(3))")
        owner.execute(f"CREATE VIEW {VUE_SONDE} AS SELECT id, label, embedding FROM {SONDE}")
        owner.execute(f"GRANT SELECT ON {VUE_SONDE} TO smartcampus_rag_reader")  # ce que fera SA-17
        try:
            async with app.transaction():
                await app.execute(f"INSERT INTO {SONDE} (label, embedding) VALUES ('a', '[1,0,0]')")
                await app.execute(f"UPDATE {SONDE} SET label = 'b'")
                n = await app.fetchval(f"SELECT count(*) FROM {SONDE} WHERE label = 'b'")
                await app.execute(f"DELETE FROM {SONDE}")
            verifier(n == 1, "smartcampus_app : SELECT/INSERT/UPDATE/DELETE sur une table créée "
                             "plus tard par le propriétaire (ALTER DEFAULT PRIVILEGES)")
            for sql, quoi in (
                (f"ALTER TABLE {SONDE} ADD COLUMN x int", "ALTER TABLE"),
                (f"DROP TABLE {SONDE}", "DROP TABLE"),
                (f"TRUNCATE {SONDE}", "TRUNCATE"),
                (f"CREATE INDEX zz_ix ON {SONDE} (label)", "CREATE INDEX"),
            ):
                ok, detail = await refuse(app, sql)
                verifier(ok, f"smartcampus_app refusé pour {quoi} : {detail}")

            # 6. smartcampus_rag_reader : lecture seule, vue accordée uniquement -------------
            owner.execute(f"INSERT INTO {SONDE} (label, embedding) VALUES ('doc', '[1,0,0]')")
            lu = await rag.fetchval(
                f"SELECT label FROM {VUE_SONDE} ORDER BY embedding <=> '[1,0,0]' LIMIT 1")
            verifier(lu == "doc", "smartcampus_rag_reader lit la vue accordée (tri pgvector <=>)")
            ro = await rag.fetchval("SHOW default_transaction_read_only")
            verifier(ro == "on", "smartcampus_rag_reader : transactions en lecture seule par défaut")
            ok, detail = await refuse(rag, f"SELECT * FROM {SONDE}")
            verifier(ok, f"smartcampus_rag_reader refusé pour SELECT sur la table de base : {detail}")
            # Chaque écriture est tentée deux fois : avec la lecture seule par défaut, puis en
            # forçant READ WRITE (contournable par le client) : c'est alors l'absence de
            # privilège (42501) qui bloque, pas seulement le mode lecture seule.
            for sql, quoi in (
                (f"INSERT INTO {SONDE} (label) VALUES ('x')", "INSERT"),
                (f"UPDATE {SONDE} SET label = 'x'", "UPDATE"),
                (f"DELETE FROM {SONDE}", "DELETE"),
                ("CREATE TABLE zz_interdit (id int)", "CREATE TABLE"),
                ("CREATE TEMP TABLE zz_t (id int)", "CREATE TEMP TABLE"),
            ):
                ok1, d1 = await refuse(rag, sql)
                ok2, d2 = await refuse(rag, "SET TRANSACTION READ WRITE; " + sql)
                verifier(ok1 and ok2 and d2.startswith("42501"),
                         f"smartcampus_rag_reader refusé pour {quoi} : {d1} ; en READ WRITE forcé : {d2}")
        finally:
            owner.execute(f"DROP VIEW IF EXISTS {VUE_SONDE}; DROP TABLE IF EXISTS {SONDE}")

        # 7. Authentification réelle (SCRAM) : un mauvais mot de passe est rejeté -------------
        try:
            mauvais = await asyncpg.connect(url_app.replace(
                f":{urlsplit(url_app).password}@", ":mauvais_mot_de_passe@"))
            await mauvais.close()
            verifier(False, "mot de passe erroné accepté (anormal)")
        except asyncpg.InvalidPasswordError as exc:
            verifier(True, f"mot de passe erroné rejeté : {exc.sqlstate} {type(exc).__name__}")
    finally:
        await app.close()
        await rag.close()
        owner.close()


async def principal() -> int:
    parser = argparse.ArgumentParser(description="Vérification PostgreSQL SA-16")
    parser.add_argument("--env-file", default=str(RACINE / ".env"))
    parser.add_argument("--target", choices=("dev", "test", "all"), default="all")
    args = parser.parse_args()
    env = lire_env(Path(args.env_file))
    cibles = {"dev": [("smartcampus (db)", "")], "test": [("smartcampus_test (db-test)", "TEST_")]}
    cibles["all"] = cibles["dev"] + cibles["test"]
    for nom, prefixe in cibles[args.target]:
        try:
            await verifier_cible(nom, env, prefixe)
        except (OSError, asyncpg.PostgresError, psycopg.Error) as exc:
            verifier(False, f"base « {nom} » inaccessible : {exc}")
    echecs = sum(1 for ok, _ in resultats if not ok)
    print(f"\nBilan : {len(resultats) - echecs}/{len(resultats)} vérifications conformes.")
    return 1 if echecs else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(principal()))
