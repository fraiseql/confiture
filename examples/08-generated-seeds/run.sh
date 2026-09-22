#!/usr/bin/env bash
# Generated seeds, end to end: written through confiture.platform, validated at
# all five prep-seed levels, applied with `confiture seed apply`, resolved.
#
#   CONFITURE_EXAMPLE_DB_URL=postgresql://user:pw@host/db ./run.sh
#
# Stands up one scratch database on the server in $CONFITURE_EXAMPLE_DB_URL and
# DROPS it at the end. Point it at a scratch server.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

DB_URL="${CONFITURE_EXAMPLE_DB_URL:-postgresql://localhost/confiture_test_examples}"
base="${DB_URL%/*}"
DB_NAME=confiture_ex08_generated_seeds
WORK_URL="${base}/${DB_NAME}"
ADMIN_URL="${base}/postgres"
work="$(mktemp -d)"

cleanup() {
    psql "$ADMIN_URL" -q -c "DROP DATABASE IF EXISTS ${DB_NAME} WITH (FORCE)" >/dev/null 2>&1 || true
}
trap 'cleanup; rm -rf "$work"' EXIT

fail() { echo "❌ $1" >&2; exit 1; }
count() { psql "$WORK_URL" -tAc "SELECT COUNT(*) FROM $1"; }

echo "Generating the seeds: the same Random(42), the same files"
python generate.py "$work" > /dev/null
diff -r "$work" db/seeds/prep || fail "generate.py no longer writes the committed seeds"
echo "✅ $(ls db/seeds/prep | tr '\n' ' ')are what generate.py writes"

cleanup
psql "$ADMIN_URL" -v ON_ERROR_STOP=1 -q -c "CREATE DATABASE ${DB_NAME}"
echo
echo "Applying db/schema in build order"
find db/schema -name '*.sql' | sort | while read -r sql; do
    psql "$WORK_URL" -v ON_ERROR_STOP=1 -q -f "$sql"
done

echo
echo "Prep-seed validation, levels 1-5: loads the seeds, runs both resolvers, rolls back"
confiture seed validate --prep-seed --level 5 --seeds-dir db/seeds/prep \
    --database-url "$WORK_URL" --format json > "$work/validate.json" \
    || fail "validation failed: $(cat "$work/validate.json")"
python - "$work/validate.json" <<'PY' || fail "expected no violations: $(cat "$work/validate.json")"
import json, sys
report = json.load(open(sys.argv[1]))
assert report["violation_count"] == 0 and report["files_scanned"] == 2, report
PY
[ "$(count catalog.tb_product)" = "0" ] || fail "validation should have rolled back"
echo "✅ no violations over 2 files; the database is untouched"

echo
echo "The pattern itself: seed apply, then the resolvers, parents first"
confiture seed apply --seeds-dir db/seeds/prep --database-url "$WORK_URL" > /dev/null
psql "$WORK_URL" -v ON_ERROR_STOP=1 -q \
    -c "SELECT fn_resolve_tb_vendor()" -c "SELECT fn_resolve_tb_product()" > /dev/null
[ "$(count catalog.tb_vendor)" = "4" ] || fail "expected 4 vendors"
[ "$(count catalog.tb_product)" = "12" ] || fail "expected 12 products"
names="$(psql "$WORK_URL" -tAc "SELECT COUNT(*) FROM catalog.tb_vendor WHERE name LIKE '%O''Brien%'")"
[ "$names" != "0" ] || fail "a quote in a seeded name did not survive"
echo "✅ 4 vendors and 12 products in catalog, each product on its vendor's BIGINT key"

echo
echo "Generated-seeds example passed."
