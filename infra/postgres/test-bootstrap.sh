#!/bin/sh
set -eu
NP_RUNTIME_PASSWORD=$(cat /run/secrets/runtime_password)
NP_MIGRATOR_PASSWORD=$(cat /run/secrets/migrator_password)
NP_TEST_TOKEN=$(cat /run/secrets/test_token)
export NP_RUNTIME_PASSWORD NP_MIGRATOR_PASSWORD NP_TEST_TOKEN
psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" <<'SQL'
\getenv runtime_password NP_RUNTIME_PASSWORD
\getenv migrator_password NP_MIGRATOR_PASSWORD
\getenv test_token NP_TEST_TOKEN
CREATE ROLE np_runtime LOGIN PASSWORD :'runtime_password' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE np_migrator LOGIN PASSWORD :'migrator_password' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
REVOKE ALL ON DATABASE nightpoint_test FROM PUBLIC;
GRANT CONNECT ON DATABASE nightpoint_test TO np_runtime,np_migrator;
GRANT CREATE ON DATABASE nightpoint_test TO np_migrator;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
CREATE SCHEMA migration AUTHORIZATION np_migrator;
REVOKE ALL ON SCHEMA migration FROM PUBLIC;
CREATE SCHEMA test_guard AUTHORIZATION np_admin;
REVOKE ALL ON SCHEMA test_guard FROM PUBLIC;
CREATE TABLE test_guard.marker(token_hash text NOT NULL);
INSERT INTO test_guard.marker VALUES (encode(sha256(convert_to(:'test_token','UTF8')),'hex'));
CREATE FUNCTION test_guard.identity_proof() RETURNS TABLE(system_identifier text,database_oid oid,token_hash text)
LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog AS $$
 SELECT c.system_identifier::text,d.oid,m.token_hash FROM pg_control_system() c,
 pg_database d, test_guard.marker m WHERE d.datname=current_database()
$$;
REVOKE ALL ON FUNCTION test_guard.identity_proof() FROM PUBLIC;
GRANT USAGE ON SCHEMA test_guard TO np_runtime,np_migrator;
GRANT EXECUTE ON FUNCTION test_guard.identity_proof() TO np_runtime,np_migrator;
ALTER ROLE np_runtime SET search_path=nightpoint,public;
ALTER ROLE np_runtime SET statement_timeout='2s';
ALTER ROLE np_runtime SET lock_timeout='1s';
CREATE DATABASE nightpoint_shadow OWNER np_admin;
REVOKE ALL ON DATABASE nightpoint_shadow FROM PUBLIC;
GRANT CONNECT ON DATABASE nightpoint_shadow TO np_runtime,np_migrator;
-- Publish completion only after all bootstrap statements, including the shadow
-- database, have succeeded. Health is not the independent connection attestation.
BEGIN;
CREATE FUNCTION test_guard.bootstrap_complete() RETURNS boolean
LANGUAGE sql SET search_path=pg_catalog AS $$ SELECT true $$;
REVOKE ALL ON FUNCTION test_guard.bootstrap_complete() FROM PUBLIC;
COMMIT;
SQL
unset NP_RUNTIME_PASSWORD NP_MIGRATOR_PASSWORD NP_TEST_TOKEN
