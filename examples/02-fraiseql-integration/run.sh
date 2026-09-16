#!/usr/bin/env bash
# Smoke run of this example against a real database.
#
#   CONFITURE_EXAMPLE_DB_URL=postgresql://user:pw@host/db ./run.sh
#
# Defaults to a local database named confiture_test_examples. The public schema
# of the target database is RESET at the start, so point it at a scratch database.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

DB_URL="${CONFITURE_EXAMPLE_DB_URL:-postgresql://localhost/confiture_test_examples}"

schema="$(mktemp)"
# The example's config names its own database; run against $DB_URL instead
# through a copy whose database_url is swapped (migrate commands read the config).
cfg="$(mktemp --suffix=.yaml)"
trap 'rm -f "$schema" "$cfg"' EXIT
sed "s|^database_url: .*|database_url: $DB_URL|" "db/environments/local.yaml" > "$cfg"

psql "$DB_URL" -v ON_ERROR_STOP=1 -q -c "DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;"

# Medium 1: build the whole schema from db/schema/ and apply it in one pass.
# The DDL is checked in (see 10_tables/generated.sql) precisely so that this
# works on a fresh clone with no code-generation step in between.
confiture build --env local --project-dir . --output "$schema"
psql "$DB_URL" -v ON_ERROR_STOP=1 -q -f "$schema"

# The CQRS pair exists on both sides: normalized tb_* for writes, denormalized
# tv_* for reads.
for table in tb_user tb_post tb_comment tv_user tv_post tv_comment; do
    psql "$DB_URL" -v ON_ERROR_STOP=1 -Atc \
        "SELECT to_regclass('public.${table}') IS NOT NULL" | grep -qx t
done

# The optional business identifier is unique where it is set, and unconstrained
# where it is not — a partial unique index, which is the only way PostgreSQL
# spells this (there is no partial UNIQUE constraint).
psql "$DB_URL" -v ON_ERROR_STOP=1 -q <<'SQL'
INSERT INTO tb_user (pk_user, email, username, full_name, identifier)
VALUES (gen_random_uuid(), 'a@example.com', 'alice', 'Alice A', NULL),
       (gen_random_uuid(), 'b@example.com', 'bob',   'Bob B',   NULL),
       (gen_random_uuid(), 'c@example.com', 'carol', 'Carol C', 'ACME-1');
SQL
if psql "$DB_URL" -q -c \
    "INSERT INTO tb_user (pk_user, email, username, full_name, identifier)
     VALUES (gen_random_uuid(), 'd@example.com', 'dave', 'Dave D', 'ACME-1');" 2>/dev/null; then
    echo "❌ duplicate identifier was accepted; the partial unique index is not doing its job"
    exit 1
fi

# The query side projects JSONB into typed columns. The immutable ones are
# GENERATED; created_at is written by the projector, because a STORED generated
# column's expression must be IMMUTABLE and text -> timestamptz is not.
psql "$DB_URL" -v ON_ERROR_STOP=1 -q <<'SQL'
INSERT INTO tv_user (id, data, created_at)
VALUES (
    gen_random_uuid(),
    '{"email": "alice@example.com", "username": "alice", "isActive": true}'::jsonb,
    '2026-01-01T00:00:00Z'
);
SQL
psql "$DB_URL" -v ON_ERROR_STOP=1 -Atc \
    "SELECT email = 'alice@example.com' AND username = 'alice' AND is_active
     FROM tv_user LIMIT 1" | grep -qx t

# Medium 2: the migration in db/migrations/ is what an *existing* database needs
# to reach the shape the DDL already describes. A database built from current DDL
# is already there, so the ledger is baselined rather than replayed — the same
# split as 01-basic-migration.
confiture migrate baseline --through 001 --config "$cfg" --migrations-dir db/migrations
confiture migrate status --config "$cfg" --migrations-dir db/migrations | grep -q "0 pending"

echo "✅ 02-fraiseql-integration: ok"
