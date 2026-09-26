#!/usr/bin/env bash
# A tenant-scoped schema: the whole `tenant` lint family passes, then the
# schema is built and PostgreSQL refuses a row that crosses tenants.
#
#   CONFITURE_EXAMPLE_DB_URL=postgresql://user:pw@host/db ./run.sh
#
# Stands up one scratch database on the server in $CONFITURE_EXAMPLE_DB_URL and
# DROPS it at the end. Point it at a scratch server.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

DB_URL="${CONFITURE_EXAMPLE_DB_URL:-postgresql://localhost/confiture_test_examples}"
base="${DB_URL%/*}"
DB_NAME=confiture_ex09_multi_tenant
WORK_URL="${base}/${DB_NAME}"
ADMIN_URL="${base}/postgres"
work="$(mktemp -d)"

cleanup() {
    psql "$ADMIN_URL" -q -c "DROP DATABASE IF EXISTS ${DB_NAME} WITH (FORCE)" >/dev/null 2>&1 || true
}
trap 'cleanup; rm -rf "$work"' EXIT

fail() { echo "❌ $1" >&2; exit 1; }
sql() { psql "$WORK_URL" -v ON_ERROR_STOP=1 -qtA -c "$1"; }

echo "Lint: db/project.yaml declares tenancy:, so the tenant family runs"
confiture lint --project-dir . --format json --fail-on info > "$work/lint.json" \
    || fail "lint failed: $(cat "$work/lint.json")"
python - "$work/lint.json" <<'PY' || fail "expected a clean run: $(cat "$work/lint.json")"
import json, sys
report = json.load(open(sys.argv[1]))
assert report["violations"]["items"] == [], report["violations"]
assert report["skipped"] == [] and report["degraded"] == [], report
PY
echo "✅ no finding at any severity; nothing skipped, nothing degraded"

echo
echo "Build: the schema, applied to a scratch database"
confiture build --env local --project-dir . --output "$work/schema.sql" > /dev/null
cleanup
psql "$ADMIN_URL" -v ON_ERROR_STOP=1 -q -c "CREATE DATABASE ${DB_NAME}"
psql "$WORK_URL" -v ON_ERROR_STOP=1 -q -f "$work/schema.sql"
echo "✅ built"

A=00000000-0000-0000-0000-00000000000a
B=00000000-0000-0000-0000-00000000000b
sql "INSERT INTO management.tb_organization VALUES ('$A', 'Tenant A'), ('$B', 'Tenant B');
     INSERT INTO catalog.tb_company VALUES (gen_random_uuid(), 'Shared Supplier Ltd', NULL);
     INSERT INTO catalog.tb_product VALUES (gen_random_uuid(), 'SKU-1', 'Widget');
     INSERT INTO catalog.tb_unit VALUES (gen_random_uuid(), 'kg', 'kilogram');
     INSERT INTO app.tb_provider (tenant_id, id, fk_company, terms)
         SELECT t, gen_random_uuid(), c.id, 'net 30'
         FROM catalog.tb_company c, (VALUES ('$A'::uuid), ('$B'::uuid)) v(t);
     INSERT INTO app.tb_custom_unit VALUES ('$A', gen_random_uuid(), 'pallet', 'pallet');"

echo
echo "The routine supplies tenant_id; the same reference serves two tenants"
for t in "$A" "$B"; do
    sql "SELECT app.fn_create_order('$t', (SELECT id FROM app.tb_provider WHERE tenant_id = '$t'), 'PO-1')" > /dev/null
done
[ "$(sql "SELECT count(*) FROM app.v_order WHERE reference = 'PO-1'")" = "2" ] \
    || fail "expected one PO-1 per tenant"
echo "✅ PO-1 for tenant A and PO-1 for tenant B, one company behind both providers"

echo
echo "A line on tenant A's own order is accepted"
sql "INSERT INTO app.tb_order_line (tenant_id, id, fk_order, fk_product, quantity)
     SELECT '$A', gen_random_uuid(), o.id, p.id, 1
     FROM app.tb_order o CROSS JOIN catalog.tb_product p
     WHERE o.tenant_id = '$A'"
echo "✅ accepted"

echo
echo "A line of tenant B's that names tenant A's order is refused by the foreign key"
set +e
out="$(sql "INSERT INTO app.tb_order_line (tenant_id, id, fk_order, fk_product, quantity)
            SELECT '$B', gen_random_uuid(), o.id, p.id, 1
            FROM app.tb_order o CROSS JOIN catalog.tb_product p
            WHERE o.tenant_id = '$A'" 2>&1)"; rc=$?
set -e
[ "$rc" -ne 0 ] || fail "a cross-tenant order line was accepted"
grep -q 'foreign key' <<< "$out" || fail "expected a foreign-key violation, got: $out"
echo "✅ refused: $(grep -m1 'violates' <<< "$out" | sed 's/^ERROR: *//')"

echo
echo "The hybrid view: the standard units for every tenant, and each tenant's own"
[ "$(sql "SELECT string_agg(code, ',' ORDER BY code) FROM app.v_unit WHERE tenant_id = '$A'")" = "kg,pallet" ] \
    || fail "tenant A should see kg and its own pallet"
[ "$(sql "SELECT string_agg(code, ',' ORDER BY code) FROM app.v_unit WHERE tenant_id = '$B'")" = "kg" ] \
    || fail "tenant B should see kg only"
echo "✅ tenant A: kg, pallet; tenant B: kg"

echo
echo "Multi-tenant example passed."
