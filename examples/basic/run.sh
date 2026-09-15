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

# The example's config names its own database; run against $DB_URL instead
# through a copy whose database_url is swapped (migrate commands read the config).
cfg="$(mktemp --suffix=.yaml)"
trap 'rm -f "$cfg" "${schema:-}"' EXIT
sed "s|^database_url: .*|database_url: $DB_URL|" "db/environments/local.yaml" > "$cfg"

psql "$DB_URL" -v ON_ERROR_STOP=1 -q -c "DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;"

# The README's two commands: apply the migrations, then show the ledger.
confiture migrate up --config "$cfg" --migrations-dir db/migrations
confiture migrate status --config "$cfg" --migrations-dir db/migrations | grep -q "0 pending"
psql "$DB_URL" -v ON_ERROR_STOP=1 -Atc "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public' AND table_name IN ('users', 'posts', 'comments')" | grep -qx 3

# Medium 1, once per seeded environment. `local` includes db/seeds/development and
# `test` includes db/seeds/test, so both builds are the only thing that ever applies
# those files — a seed file no run applies is data that has never loaded (#266).
# Each build starts from a reset schema because it creates the tables itself.
schema="$(mktemp)"
reset() { psql "$DB_URL" -v ON_ERROR_STOP=1 -q -c "DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;"; }
apply_and_count() {   # $1 = expected posts
    psql "$DB_URL" -v ON_ERROR_STOP=1 -q -f "$schema"
    psql "$DB_URL" -v ON_ERROR_STOP=1 -Atc "SELECT count(*) FROM users" | grep -qx 3
    psql "$DB_URL" -v ON_ERROR_STOP=1 -Atc "SELECT count(*) FROM posts" | grep -qx "$1"
}

reset
confiture build --env local --project-dir . --output "$schema"   # + db/seeds/development
apply_and_count 6

reset
confiture build --env test --project-dir . --output "$schema"    # + db/seeds/test
apply_and_count 3

echo "✅ basic: ok"
