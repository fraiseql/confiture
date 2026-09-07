#!/usr/bin/env bash
# Comment-validation example: three build scenarios, asserted.
#
# Runs against a scratch copy of this directory, so the example tree is never
# modified. Needs no database: `confiture build --output` only writes the file.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
cp -r "$SCRIPT_DIR"/. "$WORK"/
cd "$WORK"

break_schema() {
    cp db/schema/20_views_safe.sql db/schema/20_views.sql
    printf '/* This comment is unclosed\n   and will cause spillover\n' > db/schema/20_views_broken.sql
}

fail() { echo "❌ $1" >&2; exit 1; }

echo "Scenario 1: validation disabled in the config (--env unsafe) — the broken file builds"
break_schema
confiture build --env unsafe --project-dir . --output out_unsafe.sql > /dev/null 2>&1 \
    || fail "unsafe build should succeed (validation is disabled in unsafe.yaml)"
grep -q 'This comment is unclosed' out_unsafe.sql \
    || fail "the unclosed comment should have spilled into the output"
echo "✅ built silently — this is the problem the next two scenarios solve"

echo "Scenario 2: validation enabled in the config (--env safe) — the build fails"
break_schema
set +e
out="$(confiture build --env safe --project-dir . --output out_safe.sql 2>&1)"; rc=$?
set -e
[ "$rc" -ne 0 ] || fail "safe build should fail on the unclosed comment"
grep -q 'Comment validation failed' <<< "$out" || fail "expected 'Comment validation failed', got: $out"
grep -q 'Unclosed block comment' <<< "$out" || fail "expected the unclosed-comment finding"
echo "✅ exit $rc: $(grep -m1 'Unclosed block comment' <<< "$out" | sed 's/^ *//')"

echo "Scenario 3: --validate-comments overrides the unsafe config"
break_schema
set +e
out="$(confiture build --env unsafe --validate-comments --project-dir . --output out_override.sql 2>&1)"; rc=$?
set -e
[ "$rc" -ne 0 ] || fail "--validate-comments should override validate_comments.enabled=false"
grep -q 'Comment validation failed' <<< "$out" || fail "expected 'Comment validation failed', got: $out"
echo "✅ exit $rc with the CLI flag"

echo "All comment-validation scenarios passed."
