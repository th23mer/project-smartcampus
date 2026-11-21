#!/usr/bin/env bash
# SA-16 · Création des rôles et des privilèges de SmartCampus AI.
#
# Exécuté UNE SEULE FOIS par l'image officielle postgres, au premier démarrage sur un
# répertoire de données vide (/docker-entrypoint-initdb.d), en tant que superutilisateur
# POSTGRES_USER, sur la base POSTGRES_DB (smartcampus ou smartcampus_test).
#
# Les mots de passe viennent des variables d'environnement (fichier .env) : rien en dur.
# Le script est idempotent (relançable sans erreur) pour faciliter la maintenance.
set -euo pipefail

: "${POSTGRES_DB:?POSTGRES_DB manquant}"
: "${SMARTCAMPUS_OWNER_PASSWORD:?SMARTCAMPUS_OWNER_PASSWORD manquant}"
: "${SMARTCAMPUS_APP_PASSWORD:?SMARTCAMPUS_APP_PASSWORD manquant}"
: "${SMARTCAMPUS_RAG_READER_PASSWORD:?SMARTCAMPUS_RAG_READER_PASSWORD manquant}"

psql -v ON_ERROR_STOP=1 --no-psqlrc \
     --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
     -v db_name="$POSTGRES_DB" \
     -v owner_pw="$SMARTCAMPUS_OWNER_PASSWORD" \
     -v app_pw="$SMARTCAMPUS_APP_PASSWORD" \
     -v rag_pw="$SMARTCAMPUS_RAG_READER_PASSWORD" <<'SQL'
-- ---------------------------------------------------------------------------
-- 1. Rôles de connexion (aucun n'est superutilisateur, aucun ne crée de base ou de rôle)
-- ---------------------------------------------------------------------------
--   smartcampus_owner       : propriétaire de la base et du schéma public ; DDL ; Alembic UNIQUEMENT.
--   smartcampus_app         : backend FastAPI et worker ; DML seulement (SELECT/INSERT/UPDATE/DELETE).
--   smartcampus_rag_reader  : outil RAG search_documents ; lecture seule de la vue v_searchable_chunk
--                             (le GRANT SELECT sur la vue est posé par la migration SA-17).
SELECT format('CREATE ROLE %I LOGIN', r)
FROM unnest(ARRAY['smartcampus_owner','smartcampus_app','smartcampus_rag_reader']) AS r
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r)
\gexec

ALTER ROLE smartcampus_owner      LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD :'owner_pw';
ALTER ROLE smartcampus_app        LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD :'app_pw';
ALTER ROLE smartcampus_rag_reader LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD :'rag_pw';

COMMENT ON ROLE smartcampus_owner      IS 'SmartCampus : propriétaire du schéma, utilisé uniquement par Alembic (DDL).';
COMMENT ON ROLE smartcampus_app        IS 'SmartCampus : rôle applicatif (backend, worker), DML seulement, aucun DDL.';
COMMENT ON ROLE smartcampus_rag_reader IS 'SmartCampus : outil RAG, lecture seule de v_searchable_chunk (GRANT posé par SA-17).';

-- Garde-fous de session (défense en profondeur).
ALTER ROLE smartcampus_rag_reader SET default_transaction_read_only = on;
ALTER ROLE smartcampus_rag_reader SET statement_timeout = '10s';
ALTER ROLE smartcampus_app        SET statement_timeout = '30s';
ALTER ROLE smartcampus_app        SET idle_in_transaction_session_timeout = '60s';

-- ---------------------------------------------------------------------------
-- 2. Base : propriété au rôle de migration, plus aucun droit implicite pour PUBLIC
-- ---------------------------------------------------------------------------
SELECT format('ALTER DATABASE %I OWNER TO smartcampus_owner', :'db_name') \gexec
SELECT format('REVOKE ALL ON DATABASE %I FROM PUBLIC', :'db_name') \gexec          -- retire CONNECT et TEMPORARY
SELECT format('GRANT CONNECT ON DATABASE %I TO smartcampus_app, smartcampus_rag_reader', :'db_name') \gexec
SELECT format('ALTER DATABASE %I SET timezone TO %L', :'db_name', 'Africa/Tunis') \gexec

-- ---------------------------------------------------------------------------
-- 3. Schéma : on garde « public » (choix SA-16), possédé par smartcampus_owner
-- ---------------------------------------------------------------------------
ALTER SCHEMA public OWNER TO smartcampus_owner;
REVOKE ALL    ON SCHEMA public FROM PUBLIC;            -- en particulier CREATE (déjà le défaut en PG ≥ 15)
GRANT  USAGE  ON SCHEMA public TO smartcampus_app, smartcampus_rag_reader;
COMMENT ON SCHEMA public IS 'SmartCampus AI : schéma unique, objets créés par smartcampus_owner via Alembic.';

-- ---------------------------------------------------------------------------
-- 4. Privilèges par défaut : toute table/séquence/fonction créée plus tard par
--    smartcampus_owner (migrations Alembic) est utilisable en DML par smartcampus_app.
--    smartcampus_rag_reader ne reçoit RIEN par défaut : droits explicites dans SA-17.
-- ---------------------------------------------------------------------------
ALTER DEFAULT PRIVILEGES FOR ROLE smartcampus_owner IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO smartcampus_app;
ALTER DEFAULT PRIVILEGES FOR ROLE smartcampus_owner IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO smartcampus_app;
-- Fonctions : EXECUTE reste accordé à PUBLIC (défaut PostgreSQL). Le retirer bloquerait
-- les opérateurs de pgvector (<=>) pour le rôle RAG ; une fonction ne donne aucun accès
-- aux tables en dehors des droits de l'appelant (sauf SECURITY DEFINER, à éviter en SA-17).

-- ---------------------------------------------------------------------------
-- 5. Extensions
--    * vector (pgvector : embeddings + index HNSW) n'est PAS « trusted » : seul un
--      superutilisateur peut la créer. Elle est donc créée ici par POSTGRES_USER
--      (propriétaire de l'extension = superutilisateur). Les migrations Alembic peuvent
--      rejouer CREATE EXTENSION IF NOT EXISTS vector sans erreur (elle existe déjà).
--    * btree_gist (contraintes d'exclusion des versions publiées, SA-12 D2) et pgcrypto
--      (digest SHA-256 côté SQL si besoin ; gen_random_uuid() est natif depuis PG 13) sont
--      « trusted » : elles sont créées PAR LE PROPRIÉTAIRE smartcampus_owner (SA-12).
-- ---------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS vector     WITH SCHEMA public;
SET ROLE smartcampus_owner;
CREATE EXTENSION IF NOT EXISTS btree_gist WITH SCHEMA public;
CREATE EXTENSION IF NOT EXISTS pgcrypto   WITH SCHEMA public;
RESET ROLE;
SQL

echo "SA-16 : rôles, privilèges et extensions prêts sur la base « $POSTGRES_DB »."
