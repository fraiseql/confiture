"""Unit tests for view_helpers column rename handling (Issue #98).

Verifies that:
1. IdempotencyFixer uses DROP VIEW IF EXISTS CASCADE + CREATE VIEW
   instead of CREATE OR REPLACE VIEW (which fails on column renames)
2. When DROP VIEW already precedes CREATE VIEW, the fixer leaves it alone
3. recreate_saved_views() SQL preserves failed views in confiture.saved_views
4. Validator recognizes DROP+CREATE as idempotent (no false positives)
5. RecreateResult dataclass works correctly
"""

from __future__ import annotations

from importlib import resources
from textwrap import dedent

from confiture.core.idempotency.fixer import IdempotencyFixer
from confiture.core.idempotency.models import IdempotencyPattern
from confiture.core.idempotency.patterns import detect_non_idempotent_patterns
from confiture.core.view_manager import RecreateResult, SavedView


class TestFixerUsesDropCreateForViews:
    """IdempotencyFixer should use DROP+CREATE instead of CREATE OR REPLACE VIEW."""

    def test_standalone_create_view_gets_drop_prefix(self):
        """Standalone CREATE VIEW should get DROP IF EXISTS CASCADE prefix."""
        sql = "CREATE VIEW v_active AS SELECT * FROM users WHERE active;"
        fixer = IdempotencyFixer()

        result = fixer.fix(sql)

        assert "CREATE OR REPLACE VIEW" not in result
        assert "DROP VIEW IF EXISTS v_active CASCADE;" in result
        assert "CREATE VIEW v_active" in result

    def test_schema_qualified_create_view_gets_drop_prefix(self):
        """Schema-qualified CREATE VIEW gets correct DROP prefix."""
        sql = "CREATE VIEW public.v_orders AS SELECT id FROM orders;"
        fixer = IdempotencyFixer()

        result = fixer.fix(sql)

        assert "CREATE OR REPLACE VIEW" not in result
        assert "DROP VIEW IF EXISTS public.v_orders CASCADE;" in result
        assert "CREATE VIEW public.v_orders" in result

    def test_skips_already_idempotent_create_or_replace_view(self):
        """Does not modify already idempotent CREATE OR REPLACE VIEW."""
        sql = "CREATE OR REPLACE VIEW v_users AS SELECT * FROM users;"
        fixer = IdempotencyFixer()

        result = fixer.fix(sql)

        assert result == sql


class TestFixerSkipsDropCreateViewPattern:
    """IdempotencyFixer should not add another DROP when DROP+CREATE already exists."""

    def test_skips_create_view_preceded_by_drop(self):
        """DROP VIEW + CREATE VIEW is already idempotent — leave it alone."""
        sql = dedent("""\
            DROP VIEW v_users CASCADE;
            CREATE VIEW v_users AS SELECT id, tenant_id FROM users;
        """)
        fixer = IdempotencyFixer()

        result = fixer.fix(sql)

        assert "CREATE OR REPLACE VIEW" not in result
        assert "CREATE VIEW v_users" in result
        # DROP should get IF EXISTS
        assert "DROP VIEW IF EXISTS v_users" in result
        # Should NOT have double DROP
        assert result.count("DROP VIEW") == 1

    def test_skips_schema_qualified_drop_create(self):
        """Schema-qualified DROP + CREATE is left alone."""
        sql = dedent("""\
            DROP VIEW public.v_orders CASCADE;
            CREATE VIEW public.v_orders AS SELECT id, status FROM orders;
        """)
        fixer = IdempotencyFixer()

        result = fixer.fix(sql)

        assert "CREATE OR REPLACE VIEW" not in result
        assert "CREATE VIEW public.v_orders" in result

    def test_skips_drop_if_exists_create(self):
        """DROP VIEW IF EXISTS + CREATE VIEW is left alone."""
        sql = dedent("""\
            DROP VIEW IF EXISTS v_stats CASCADE;
            CREATE VIEW v_stats AS SELECT count(*) FROM events;
        """)
        fixer = IdempotencyFixer()

        result = fixer.fix(sql)

        assert "CREATE OR REPLACE VIEW" not in result
        assert "CREATE VIEW v_stats" in result
        # Should NOT add a second DROP
        assert result.count("DROP VIEW") == 1

    def test_mixed_drop_create_and_standalone(self):
        """Only skip DROP prefix for views that already have a preceding DROP."""
        sql = dedent("""\
            DROP VIEW v_orders CASCADE;
            CREATE VIEW v_orders AS SELECT id, tenant_id FROM orders;
            CREATE VIEW v_stats AS SELECT count(*) FROM events;
        """)
        fixer = IdempotencyFixer()

        result = fixer.fix(sql)

        # v_orders: DROP+CREATE pattern, should NOT get another DROP
        assert "CREATE VIEW v_orders" in result
        assert "CREATE OR REPLACE VIEW" not in result
        # v_stats: standalone, should get DROP prefix
        assert "DROP VIEW IF EXISTS v_stats CASCADE;" in result
        assert "CREATE VIEW v_stats" in result

    def test_quoted_identifiers(self):
        """Handles quoted view names in DROP+CREATE pattern."""
        sql = dedent("""\
            DROP VIEW IF EXISTS "MyView" CASCADE;
            CREATE VIEW "MyView" AS SELECT id FROM t;
        """)
        fixer = IdempotencyFixer()

        result = fixer.fix(sql)

        assert "CREATE OR REPLACE VIEW" not in result
        assert 'CREATE VIEW "MyView"' in result

    def test_drop_restrict_create(self):
        """DROP VIEW RESTRICT + CREATE VIEW is left alone."""
        sql = dedent("""\
            DROP VIEW v_users RESTRICT;
            CREATE VIEW v_users AS SELECT id FROM users;
        """)
        fixer = IdempotencyFixer()

        result = fixer.fix(sql)

        assert "CREATE OR REPLACE VIEW" not in result
        assert "CREATE VIEW v_users" in result


class TestValidatorRecognizesDropCreatePattern:
    """detect_non_idempotent_patterns should not flag DROP+CREATE as non-idempotent."""

    def test_drop_if_exists_create_is_not_flagged(self):
        """DROP VIEW IF EXISTS + CREATE VIEW is recognized as idempotent."""
        sql = dedent("""\
            DROP VIEW IF EXISTS v_users CASCADE;
            CREATE VIEW v_users AS SELECT id, tenant_id FROM users;
        """)

        violations = detect_non_idempotent_patterns(sql)
        view_violations = [v for v in violations if v.pattern == IdempotencyPattern.CREATE_VIEW]

        assert len(view_violations) == 0

    def test_standalone_create_view_is_flagged(self):
        """Standalone CREATE VIEW is still flagged as non-idempotent."""
        sql = "CREATE VIEW v_users AS SELECT * FROM users;"

        violations = detect_non_idempotent_patterns(sql)
        view_violations = [v for v in violations if v.pattern == IdempotencyPattern.CREATE_VIEW]

        assert len(view_violations) == 1

    def test_fixer_then_validator_is_consistent(self):
        """After fixing, the validator should report zero CREATE VIEW violations."""
        sql = "CREATE VIEW v_users AS SELECT * FROM users;"
        fixer = IdempotencyFixer()

        fixed = fixer.fix(sql)
        violations = detect_non_idempotent_patterns(fixed)
        view_violations = [v for v in violations if v.pattern == IdempotencyPattern.CREATE_VIEW]

        assert len(view_violations) == 0

    def test_mixed_fixed_and_unfixed(self):
        """Only unfixed views are flagged after partial fix."""
        sql = dedent("""\
            DROP VIEW IF EXISTS v_fixed CASCADE;
            CREATE VIEW v_fixed AS SELECT id FROM t1;
            CREATE VIEW v_unfixed AS SELECT id FROM t2;
        """)

        violations = detect_non_idempotent_patterns(sql)
        view_violations = [v for v in violations if v.pattern == IdempotencyPattern.CREATE_VIEW]

        # Only v_unfixed should be flagged
        assert len(view_violations) == 1
        assert "v_unfixed" in view_violations[0].sql_snippet


class TestRecreateSavedViewsSQL:
    """Verify that the SQL function is resilient and preserves failed views."""

    def test_recreate_uses_exception_handling(self):
        """recreate_saved_views() SQL uses EXCEPTION WHEN OTHERS for resilience."""
        sql = resources.files("confiture.sql").joinpath("view_helpers.sql").read_text()

        recreate_start = sql.index("CREATE OR REPLACE FUNCTION confiture.recreate_saved_views()")
        recreate_body = sql[recreate_start:]

        assert "EXCEPTION WHEN OTHERS THEN" in recreate_body

    def test_failed_views_get_error_recorded(self):
        """Failed views have their error recorded in the table."""
        sql = resources.files("confiture.sql").joinpath("view_helpers.sql").read_text()

        recreate_start = sql.index("CREATE OR REPLACE FUNCTION confiture.recreate_saved_views()")
        recreate_body = sql[recreate_start:]

        assert "UPDATE confiture.saved_views" in recreate_body
        assert "error_message" in recreate_body

    def test_successful_views_cleaned_up(self):
        """Successfully recreated views are deleted from the table."""
        sql = resources.files("confiture.sql").joinpath("view_helpers.sql").read_text()

        recreate_start = sql.index("CREATE OR REPLACE FUNCTION confiture.recreate_saved_views()")
        recreate_body = sql[recreate_start:]

        assert "DELETE FROM confiture.saved_views WHERE recreated" in recreate_body

    def test_table_has_recreated_and_error_columns(self):
        """The saved_views table has recreated and error_message columns."""
        sql = resources.files("confiture.sql").joinpath("view_helpers.sql").read_text()

        assert "recreated     BOOLEAN NOT NULL DEFAULT FALSE" in sql
        assert "error_message TEXT" in sql


class TestRecreateResult:
    """Unit tests for the RecreateResult dataclass."""

    def test_empty_result(self):
        """Empty result has correct defaults."""
        result = RecreateResult()

        assert result.total == 0
        assert result.all_succeeded is True
        assert result.recreated == []
        assert result.failed == []

    def test_all_succeeded(self):
        """All succeeded when failed list is empty."""
        view = SavedView(
            oid=1, schema="public", name="v1", kind="v", depth=0, definition="SELECT 1"
        )
        result = RecreateResult(recreated=[view])

        assert result.total == 1
        assert result.all_succeeded is True

    def test_partial_failure(self):
        """Partial failure correctly reported."""
        ok = SavedView(oid=1, schema="public", name="v1", kind="v", depth=0, definition="SELECT 1")
        bad = SavedView(
            oid=2,
            schema="public",
            name="v2",
            kind="v",
            depth=1,
            definition="SELECT old_col FROM v1",
        )
        result = RecreateResult(recreated=[ok], failed=[(bad, "column old_col does not exist")])

        assert result.total == 2
        assert result.all_succeeded is False
        assert len(result.failed) == 1
        assert result.failed[0][1] == "column old_col does not exist"

    def test_to_dict(self):
        """to_dict produces correct structure."""
        view = SavedView(
            oid=1, schema="public", name="v1", kind="v", depth=0, definition="SELECT 1"
        )
        result = RecreateResult(
            recreated=[view],
            failed=[(view, "some error")],
        )

        d = result.to_dict()

        assert d["recreated_count"] == 1
        assert d["failed_count"] == 1
        assert d["total"] == 2
        assert d["all_succeeded"] is False
        assert d["failed"][0]["error"] == "some error"
        assert d["failed"][0]["definition"] == "SELECT 1"

    def test_saved_view_qualified_name(self):
        """SavedView.qualified_name returns schema.name."""
        view = SavedView(oid=1, schema="catalog", name="v_items", kind="v", depth=0, definition="")

        assert view.qualified_name == "catalog.v_items"
