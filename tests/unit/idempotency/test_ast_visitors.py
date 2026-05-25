"""AST-backend-specific tests.

The shared :mod:`test_patterns` parity sweep covers cases that *should*
behave identically across backends. This file holds tests for behaviors
that are only correct on the AST backend — specifically the bugs and
limitations issue #122 closes.

Every test pins ``CONFITURE_IDEMPOTENCY_FORCE_REGEX=0`` (the default)
and is skipped under the regex backend; the regex-only counterparts
(in :class:`test_patterns.TestPhase03KnownLimitations`) document the
opposite outcome.
"""

from __future__ import annotations

import pytest

from confiture.core.idempotency.models import IdempotencyPattern
from confiture.core.idempotency.patterns import detect_non_idempotent_patterns

# These tests assert behavior that requires the AST backend; they skip
# under the regex run instead of running with backwards assertions.
pytestmark = pytest.mark.ast_only(
    reason="AST-only behavior — regex backend has the documented limitation"
)


class TestIssue122Bug1:
    """``ADD COLUMN IF NOT EXISTS`` on a schema-qualified table must not flag."""

    def test_schema_qualified_add_column_if_not_exists_is_clean(self):
        sql = "ALTER TABLE schema.tb_foo ADD COLUMN IF NOT EXISTS bar JSONB NOT NULL;"
        assert detect_non_idempotent_patterns(sql) == []

    def test_unqualified_add_column_if_not_exists_is_clean(self):
        sql = "ALTER TABLE tb_foo ADD COLUMN IF NOT EXISTS bar JSONB NOT NULL;"
        assert detect_non_idempotent_patterns(sql) == []


class TestIssue122Bug2:
    """Long identifiers must round-trip without truncation in pair recognizers."""

    def test_long_constraint_name_in_drop_add_pair_is_idempotent(self):
        long_name = "a_very_long_constraint_name_that_exceeds_typical_regex_capture_lengths"
        sql = (
            f"ALTER TABLE foo DROP CONSTRAINT IF EXISTS {long_name};"
            f"ALTER TABLE foo ADD CONSTRAINT {long_name} CHECK (id > 0);"
        )
        assert detect_non_idempotent_patterns(sql) == []

    def test_long_view_name_in_drop_create_pair_is_idempotent(self):
        long_name = "v_extremely_long_view_name_used_for_dashboard_analytics_with_many_columns"
        sql = f"DROP VIEW IF EXISTS {long_name};CREATE VIEW {long_name} AS SELECT 1;"
        assert detect_non_idempotent_patterns(sql) == []

    def test_long_function_name_in_drop_cor_pair_is_idempotent(self):
        long_name = "fn_extremely_long_function_name_used_in_the_reporting_subsystem"
        sql = (
            f"DROP FUNCTION IF EXISTS {long_name};"
            f"CREATE OR REPLACE FUNCTION {long_name}() RETURNS void "
            "AS $$ BEGIN END; $$ LANGUAGE plpgsql;"
        )
        assert detect_non_idempotent_patterns(sql) == []


class TestQuotedIdentifiers:
    """Quoted identifiers parse via pglast's unquoting — no longer slip through."""

    def test_quoted_table_with_dash_is_flagged(self):
        sql = 'ALTER TABLE "My-Table" ADD CONSTRAINT "chk-x" CHECK (id > 0);'
        matches = detect_non_idempotent_patterns(sql)
        assert len(matches) == 1
        assert matches[0].pattern == IdempotencyPattern.ALTER_TABLE_ADD_CONSTRAINT_CHECK

    def test_quoted_view_name_in_drop_create_pair_is_idempotent(self):
        sql = 'DROP VIEW IF EXISTS "My-View";CREATE VIEW "My-View" AS SELECT 1;'
        assert detect_non_idempotent_patterns(sql) == []


class TestMultiClauseAlter:
    """Every ADD CONSTRAINT clause in a multi-clause ALTER is flagged."""

    def test_two_clauses_both_flagged(self):
        sql = "ALTER TABLE foo ADD CONSTRAINT a CHECK (id > 0), ADD CONSTRAINT b CHECK (id < 10);"
        matches = detect_non_idempotent_patterns(sql)
        assert len(matches) == 2
        assert all(
            m.pattern == IdempotencyPattern.ALTER_TABLE_ADD_CONSTRAINT_CHECK for m in matches
        )

    def test_drop_then_add_in_same_alter_is_idempotent(self):
        """``DROP CONSTRAINT IF EXISTS x, ADD CONSTRAINT x …`` — recognized as a pair."""
        sql = (
            "ALTER TABLE foo DROP CONSTRAINT IF EXISTS chk_x, ADD CONSTRAINT chk_x CHECK (id > 0);"
        )
        assert detect_non_idempotent_patterns(sql) == []
