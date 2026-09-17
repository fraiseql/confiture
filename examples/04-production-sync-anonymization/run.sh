#!/usr/bin/env bash
# Smoke run of this example against a real database.
#
#   CONFITURE_EXAMPLE_DB_URL=postgresql://user:pw@host/db ./run.sh
#
# The example's own environments point at prod-db.example.com and
# staging-db.example.com, which is what they should look like. To demonstrate
# the sync for real, this script stands up two scratch databases on the server
# in $CONFITURE_EXAMPLE_DB_URL — one playing production, one playing staging —
# and DROPS both at the end. Point it at a scratch server.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

DB_URL="${CONFITURE_EXAMPLE_DB_URL:-postgresql://localhost/confiture_test_examples}"

# `confiture sync` resolves --from/--to as DSNs, and a DSN needs a host: derive
# the two demo databases from $DB_URL by swapping the database name.
base="${DB_URL%/*}"
SRC_URL="${base}/confiture_ex04_prod"
TGT_URL="${base}/confiture_ex04_staging"
ADMIN_URL="${base}/postgres"

cleanup() {
    psql "$ADMIN_URL" -q -c "DROP DATABASE IF EXISTS confiture_ex04_prod    WITH (FORCE)" >/dev/null 2>&1 || true
    psql "$ADMIN_URL" -q -c "DROP DATABASE IF EXISTS confiture_ex04_staging WITH (FORCE)" >/dev/null 2>&1 || true
    rm -f "${schema:-}"
}
trap cleanup EXIT

psql "$ADMIN_URL" -v ON_ERROR_STOP=1 -q \
    -c "DROP DATABASE IF EXISTS confiture_ex04_prod    WITH (FORCE)" \
    -c "DROP DATABASE IF EXISTS confiture_ex04_staging WITH (FORCE)" \
    -c "CREATE DATABASE confiture_ex04_prod" \
    -c "CREATE DATABASE confiture_ex04_staging"

# Both ends get the same schema from db/schema/ — sync copies rows, not tables,
# so the target must already have somewhere to put them.
schema="$(mktemp)"
confiture build --env production --project-dir . --output "$schema"
psql "$SRC_URL" -v ON_ERROR_STOP=1 -q -f "$schema"
psql "$TGT_URL" -v ON_ERROR_STOP=1 -q -f "$schema"

# "Production" gets data with recognisable PII in it, so that asserting its
# absence downstream means something.
psql "$SRC_URL" -v ON_ERROR_STOP=1 -q -f demo/seed_production.sql

# The keyed strategies need a per-deployment secret and have no default; a real
# deployment reads this from its secret store, never from a file in the repo.
export ANONYMIZATION_SECRET="${ANONYMIZATION_SECRET:-example-04-demo-secret}"

confiture sync \
    --from "$SRC_URL" \
    --to "$TGT_URL" \
    --anonymize \
    --anonymization-config db/sync/anonymization.yaml \
    --exclude audit_logs

# ---------------------------------------------------------------------------
# The assertions. `confiture sync` exiting 0 means rows moved, not that they
# were masked; the whole claim of this example is the masking, so it is checked
# against the target directly.
# ---------------------------------------------------------------------------
psql "$TGT_URL" -v ON_ERROR_STOP=1 -q -f verify_anonymization.sql

# audit_logs was excluded outright: the table exists in staging and is empty.
rows=$(psql "$TGT_URL" -Atc "SELECT count(*) FROM audit_logs")
if [[ "$rows" != "0" ]]; then
    echo "❌ audit_logs was copied to staging ($rows rows); --exclude did not hold"
    exit 1
fi

# Non-PII tables are copied verbatim — anonymization is opt-in per column.
products=$(psql "$TGT_URL" -Atc "SELECT count(*) FROM products WHERE sku LIKE 'SKU-%'")
if [[ "$products" != "2" ]]; then
    echo "❌ products did not survive the sync intact ($products of 2)"
    exit 1
fi

echo "✅ 04-production-sync-anonymization: ok"
