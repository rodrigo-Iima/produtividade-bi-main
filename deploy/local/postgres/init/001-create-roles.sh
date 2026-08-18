#!/usr/bin/env bash

set -euo pipefail

psql_base=(
    psql
    --username "$POSTGRES_USER"
    --dbname "$POSTGRES_DB"
    --set ON_ERROR_STOP=1
)

"${psql_base[@]}" \
    --set etl_password="$LOCAL_POSTGRES_ETL_PASSWORD" \
    --set reader_password="$LOCAL_POSTGRES_READER_PASSWORD" \
    --set migrator_user="$POSTGRES_USER" \
    --set database_name="$POSTGRES_DB" <<'SQL'
SELECT format(
    'CREATE ROLE produtividade_etl LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD %L',
    :'etl_password'
)
WHERE NOT EXISTS (
    SELECT 1 FROM pg_roles WHERE rolname = 'produtividade_etl'
)\gexec

SELECT format(
    'ALTER ROLE produtividade_etl PASSWORD %L',
    :'etl_password'
)
\gexec

SELECT format(
    'CREATE ROLE produtividade_reader LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD %L',
    :'reader_password'
)
WHERE NOT EXISTS (
    SELECT 1 FROM pg_roles WHERE rolname = 'produtividade_reader'
)\gexec

SELECT format(
    'ALTER ROLE produtividade_reader PASSWORD %L',
    :'reader_password'
)
\gexec

ALTER ROLE produtividade_reader
    SET default_transaction_read_only = on;
ALTER ROLE produtividade_reader CONNECTION LIMIT 10;

REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO produtividade_etl, produtividade_reader;

SELECT format(
    'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO produtividade_etl',
    :'migrator_user'
)
\gexec
SELECT format(
    'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO produtividade_etl',
    :'migrator_user'
)
\gexec
SELECT format(
    'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public GRANT EXECUTE ON FUNCTIONS TO produtividade_etl',
    :'migrator_user'
)
\gexec

SELECT format(
    'GRANT CONNECT ON DATABASE %I TO produtividade_etl, produtividade_reader',
    :'database_name'
)
\gexec
SQL
