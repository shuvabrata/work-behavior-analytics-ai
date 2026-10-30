#!/bin/bash
# Creates the separate database Keycloak uses. Runs ONLY on a fresh pgdata
# volume (Postgres executes /docker-entrypoint-initdb.d once). On an existing
# volume this file is skipped, and the operator runs the idempotent snippet in
# DEVELOPER_QUICK_START.md instead. Schemas never mix: the application stays in
# POSTGRES_DB, Keycloak lives in `keycloak`.
#
# Shell rather than SQL so the password comes from the environment: a committed
# .sql file cannot read a variable and would force the literal into git.
set -euo pipefail

: "${KEYCLOAK_DB_PASSWORD:?KEYCLOAK_DB_PASSWORD must be set (see .env.example)}"

psql -v ON_ERROR_STOP=1 \
     --username "$POSTGRES_USER" \
     --dbname "$POSTGRES_DB" <<EOSQL
CREATE ROLE keycloak WITH LOGIN PASSWORD '${KEYCLOAK_DB_PASSWORD}';
CREATE DATABASE keycloak OWNER keycloak;
EOSQL
