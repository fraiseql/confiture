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

echo "✅ basic: ok"
