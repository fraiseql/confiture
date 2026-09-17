#!/usr/bin/env bash
# Smoke run of the prep-seed validation example, both levels of it.
#
#   CONFITURE_EXAMPLE_DB_URL=postgresql://user:pw@host/db ./run.sh
#
# Stands up one scratch database on the server in $CONFITURE_EXAMPLE_DB_URL and
# DROPS it at the end. Point it at a scratch server.
#
# Levels 1-3 are static and need no database; levels 4-5 load the seeds, run the
# resolution function and check the result. Both are asserted here, because for
# a long time level 5 reported eight violations against this very schema — four
# of them CRITICAL — with no bad data anywhere in it.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

DB_URL="${CONFITURE_EXAMPLE_DB_URL:-postgresql://localhost/confiture_test_examples}"
base="${DB_URL%/*}"
DB_NAME=confiture_ex06_prep_seed
WORK_URL="${base}/${DB_NAME}"
ADMIN_URL="${base}/postgres"

cleanup() {
    psql "$ADMIN_URL" -q -c "DROP DATABASE IF EXISTS ${DB_NAME} WITH (FORCE)" >/dev/null 2>&1 || true
}
trap cleanup EXIT

fail() { echo "❌ $1" >&2; exit 1; }

cleanup
psql "$ADMIN_URL" -v ON_ERROR_STOP=1 -q -c "CREATE DATABASE ${DB_NAME}"

echo "Applying the prep_seed and catalog schemas"
psql "$WORK_URL" -v ON_ERROR_STOP=1 -q \
    -c "CREATE SCHEMA prep_seed" \
    -c "CREATE SCHEMA catalog"
for sql in db/schema/prep_seed/tb_manufacturer.sql \
           db/schema/catalog/tb_manufacturer.sql \
           db/schema/functions/fn_resolve_tb_manufacturer.sql; do
    psql "$WORK_URL" -v ON_ERROR_STOP=1 -q -f "$sql"
done

echo
echo "Levels 1-3 (static, no database)"
python validate_static.py > static.out 2>&1 || fail "static validation failed: $(cat static.out)"
grep -q "All static validation checks passed" static.out \
    || fail "expected a clean static run, got: $(cat static.out)"
echo "✅ $(grep -m1 'Total violations' static.out | sed 's/^ *//')"

echo
echo "Levels 1-5 (loads the seeds, runs fn_resolve_tb_manufacturer)"
set +e
DATABASE_URL="$WORK_URL" python validate_full.py > full.out 2>&1
rc=$?
set -e
[ "$rc" -eq 0 ] || fail "full validation exited $rc:
$(cat full.out)"
grep -q "All validation checks passed" full.out \
    || fail "expected a clean full run, got: $(cat full.out)"
echo "✅ $(grep -m1 'Total violations' full.out | sed 's/^ *//')"

echo
echo "Validation rolls back: the database is untouched by it"
# Level 5 loads and resolves inside a transaction it always rolls back, so a
# clean report is a report about data that no longer exists. Assert that too —
# "no violations" over an empty table is the shape of a verification that
# cannot fail.
rows="$(psql "$WORK_URL" -tAc 'SELECT COUNT(*) FROM catalog.tb_manufacturer')"
[ "$rows" = "0" ] || fail "validation should have rolled back, but left $rows rows"
echo "✅ catalog.tb_manufacturer is empty again"

echo
echo "The pattern itself: load the seeds, run the resolver, keep the result"
psql "$WORK_URL" -v ON_ERROR_STOP=1 -q -f db/seeds/prep/01_manufacturers.sql
psql "$WORK_URL" -v ON_ERROR_STOP=1 -tAqc "SELECT fn_resolve_tb_manufacturer()" > /dev/null
rows="$(psql "$WORK_URL" -tAc 'SELECT COUNT(*) FROM catalog.tb_manufacturer')"
[ "$rows" = "4" ] || fail "expected 4 resolved manufacturers, found ${rows:-0}"
nulls="$(psql "$WORK_URL" -tAc 'SELECT COUNT(*) FROM catalog.tb_manufacturer WHERE id IS NULL')"
[ "$nulls" = "0" ] || fail "expected no NULL ids after resolution, found $nulls"
pks="$(psql "$WORK_URL" -tAc 'SELECT COUNT(DISTINCT pk_manufacturer) FROM catalog.tb_manufacturer')"
[ "$pks" = "4" ] || fail "expected 4 distinct BIGINT keys, found ${pks:-0}"
echo "✅ 4 rows in catalog.tb_manufacturer: 4 distinct BIGINT keys, no NULL id"

rm -f static.out full.out
echo
echo "Prep-seed validation example passed."
