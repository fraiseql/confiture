"""Reconciliation tests: a single source of truth for auto-fix availability.

Pre-0.16: ``IdempotencyPattern.fix_available`` claimed 17 patterns were
fixable while ``_get_suggested_fix`` only dispatched for 11 — so
``dry_run`` underreported the auto-fix coverage that ``fix()`` actually
performs.

This module pins the contract: every pattern that ``fix_available`` reports
as ``True`` must also be routed by ``_get_suggested_fix``.
"""

from __future__ import annotations

from confiture.core.idempotency.fixer import (
    FIXABLE_PATTERNS,
    IdempotencyFixer,
)
from confiture.core.idempotency.models import IdempotencyPattern

# Minimal SQL snippets per fixable pattern — used to confirm the
# dispatch table actually routes the fix. The transformations are
# deliberately recognisable (``IF NOT EXISTS`` / ``OR REPLACE`` / etc.).
_FIXABLE_SAMPLE_SQL: dict[IdempotencyPattern, str] = {
    IdempotencyPattern.CREATE_TABLE: "CREATE TABLE users (id INT);",
    IdempotencyPattern.CREATE_INDEX: "CREATE INDEX idx_users_email ON users(email);",
    IdempotencyPattern.CREATE_UNIQUE_INDEX: (
        "CREATE UNIQUE INDEX idx_users_email ON users(email);"
    ),
    IdempotencyPattern.CREATE_FUNCTION: (
        "CREATE FUNCTION f() RETURNS void LANGUAGE sql AS $$ SELECT 1 $$;"
    ),
    IdempotencyPattern.CREATE_PROCEDURE: ("CREATE PROCEDURE p() LANGUAGE sql AS $$ SELECT 1 $$;"),
    IdempotencyPattern.CREATE_VIEW: "CREATE VIEW v AS SELECT 1;",
    IdempotencyPattern.CREATE_EXTENSION: "CREATE EXTENSION pgcrypto;",
    IdempotencyPattern.CREATE_SCHEMA: "CREATE SCHEMA app;",
    IdempotencyPattern.CREATE_SEQUENCE: "CREATE SEQUENCE seq_id;",
    IdempotencyPattern.ALTER_TABLE_ADD_COLUMN: ("ALTER TABLE users ADD COLUMN bio TEXT;"),
    IdempotencyPattern.DROP_TABLE: "DROP TABLE users;",
    IdempotencyPattern.DROP_INDEX: "DROP INDEX idx_users_email;",
    IdempotencyPattern.DROP_FUNCTION: "DROP FUNCTION f();",
    IdempotencyPattern.DROP_VIEW: "DROP VIEW v;",
    IdempotencyPattern.DROP_TYPE: "DROP TYPE status_enum;",
    IdempotencyPattern.DROP_SCHEMA: "DROP SCHEMA app;",
    IdempotencyPattern.DROP_SEQUENCE: "DROP SEQUENCE seq_id;",
}


class TestFixableSourceOfTruth:
    """``FIXABLE_PATTERNS`` is the single source of truth."""

    def test_fix_available_matches_fixable_patterns(self):
        """Every pattern marked ``fix_available`` is in ``FIXABLE_PATTERNS``."""
        claimed = {p for p in IdempotencyPattern if p.fix_available}
        assert claimed == FIXABLE_PATTERNS

    def test_fixable_set_is_non_empty(self):
        """Sanity check: at least the CREATE_TABLE entry survives."""
        assert IdempotencyPattern.CREATE_TABLE in FIXABLE_PATTERNS
        assert len(FIXABLE_PATTERNS) > 0


class TestDispatchCoverage:
    """``_get_suggested_fix`` routes every claimed-fixable pattern."""

    def test_dispatch_routes_every_fixable_pattern(self):
        """For each fixable pattern, dispatch produces a transformed snippet.

        Without the Cycle 2 fix, six patterns (CREATE_EXTENSION,
        CREATE_SCHEMA, CREATE_SEQUENCE, DROP_TYPE, DROP_SCHEMA,
        DROP_SEQUENCE) fail this — ``_get_suggested_fix`` returns the
        input unchanged because their dispatch entry is missing.
        """
        fixer = IdempotencyFixer()
        for pattern in FIXABLE_PATTERNS:
            sample = _FIXABLE_SAMPLE_SQL[pattern]
            transformed = fixer._get_suggested_fix(pattern, sample)
            assert transformed != sample, (
                f"_get_suggested_fix did not transform {pattern.name}: "
                f"input={sample!r} output={transformed!r}"
            )

    def test_six_patterns_previously_missing_dispatch_now_route(self):
        """The 6 patterns identified in Phase 01 review now route."""
        previously_missing = {
            IdempotencyPattern.CREATE_EXTENSION,
            IdempotencyPattern.CREATE_SCHEMA,
            IdempotencyPattern.CREATE_SEQUENCE,
            IdempotencyPattern.DROP_TYPE,
            IdempotencyPattern.DROP_SCHEMA,
            IdempotencyPattern.DROP_SEQUENCE,
        }
        fixer = IdempotencyFixer()
        for pattern in previously_missing:
            sample = _FIXABLE_SAMPLE_SQL[pattern]
            transformed = fixer._get_suggested_fix(pattern, sample)
            assert "IF NOT EXISTS" in transformed.upper() or "IF EXISTS" in transformed.upper(), (
                f"{pattern.name}: expected idempotency keyword in fix; got {transformed!r}"
            )


class TestDryRunReportsAllFixablePatterns:
    """End-to-end: ``dry_run`` no longer underreports auto-fix coverage."""

    def test_dry_run_emits_change_for_create_extension(self):
        """CREATE_EXTENSION was missing from dispatch — dry_run now reports it."""
        fixer = IdempotencyFixer()
        changes = fixer.dry_run("CREATE EXTENSION pgcrypto;")
        assert len(changes) == 1
        assert changes[0].pattern == IdempotencyPattern.CREATE_EXTENSION
        assert "IF NOT EXISTS" in changes[0].suggested_fix.upper()

    def test_dry_run_emits_change_for_drop_sequence(self):
        """DROP_SEQUENCE was missing from dispatch — dry_run now reports it."""
        fixer = IdempotencyFixer()
        changes = fixer.dry_run("DROP SEQUENCE seq_id;")
        assert len(changes) == 1
        assert changes[0].pattern == IdempotencyPattern.DROP_SEQUENCE
        assert "IF EXISTS" in changes[0].suggested_fix.upper()
