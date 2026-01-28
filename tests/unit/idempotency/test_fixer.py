"""Tests for idempotency auto-fix transformations."""

from textwrap import dedent

from confiture.core.idempotency.fixer import IdempotencyFixer
from confiture.core.idempotency.models import IdempotencyPattern


class TestCreateTableFix:
    """Tests for CREATE TABLE auto-fix."""

    def test_adds_if_not_exists_to_create_table(self):
        """Adds IF NOT EXISTS to CREATE TABLE."""
        sql = "CREATE TABLE users (id INT PRIMARY KEY);"
        fixer = IdempotencyFixer()

        result = fixer.fix(sql)

        assert "CREATE TABLE IF NOT EXISTS users" in result
        assert result.endswith(";")

    def test_preserves_schema_qualified_name(self):
        """Preserves schema prefix when fixing CREATE TABLE."""
        sql = "CREATE TABLE app.users (id INT PRIMARY KEY);"
        fixer = IdempotencyFixer()

        result = fixer.fix(sql)

        assert "CREATE TABLE IF NOT EXISTS app.users" in result

    def test_handles_multiline_create_table(self):
        """Handles multi-line CREATE TABLE statements."""
        sql = dedent("""
            CREATE TABLE users (
                id INT PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT UNIQUE
            );
        """).strip()
        fixer = IdempotencyFixer()

        result = fixer.fix(sql)

        assert "CREATE TABLE IF NOT EXISTS users" in result
        assert "id INT PRIMARY KEY" in result

    def test_skips_already_idempotent_create_table(self):
        """Does not modify already idempotent CREATE TABLE."""
        sql = "CREATE TABLE IF NOT EXISTS users (id INT);"
        fixer = IdempotencyFixer()

        result = fixer.fix(sql)

        assert result == sql


class TestCreateIndexFix:
    """Tests for CREATE INDEX auto-fix."""

    def test_adds_if_not_exists_to_create_index(self):
        """Adds IF NOT EXISTS to CREATE INDEX."""
        sql = "CREATE INDEX idx_users_email ON users(email);"
        fixer = IdempotencyFixer()

        result = fixer.fix(sql)

        assert "CREATE INDEX IF NOT EXISTS idx_users_email" in result

    def test_adds_if_not_exists_to_create_unique_index(self):
        """Adds IF NOT EXISTS to CREATE UNIQUE INDEX."""
        sql = "CREATE UNIQUE INDEX idx_users_email ON users(email);"
        fixer = IdempotencyFixer()

        result = fixer.fix(sql)

        assert "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email" in result

    def test_handles_create_index_concurrently(self):
        """Handles CREATE INDEX CONCURRENTLY."""
        sql = "CREATE INDEX CONCURRENTLY idx_users ON users(email);"
        fixer = IdempotencyFixer()

        result = fixer.fix(sql)

        assert "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_users" in result


class TestCreateFunctionFix:
    """Tests for CREATE FUNCTION auto-fix."""

    def test_adds_or_replace_to_create_function(self):
        """Adds OR REPLACE to CREATE FUNCTION."""
        sql = "CREATE FUNCTION add_nums(a INT, b INT) RETURNS INT AS $$ SELECT a + b; $$ LANGUAGE sql;"
        fixer = IdempotencyFixer()

        result = fixer.fix(sql)

        assert "CREATE OR REPLACE FUNCTION add_nums" in result

    def test_handles_multiline_function(self):
        """Handles multi-line function definitions."""
        sql = dedent("""
            CREATE FUNCTION calculate_total(order_id INT)
            RETURNS NUMERIC AS $$
            BEGIN
                RETURN (SELECT SUM(amount) FROM order_items WHERE fk_order = order_id);
            END;
            $$ LANGUAGE plpgsql;
        """).strip()
        fixer = IdempotencyFixer()

        result = fixer.fix(sql)

        assert "CREATE OR REPLACE FUNCTION calculate_total" in result

    def test_skips_already_idempotent_function(self):
        """Does not modify CREATE OR REPLACE FUNCTION."""
        sql = "CREATE OR REPLACE FUNCTION test() RETURNS VOID AS $$ BEGIN END; $$ LANGUAGE plpgsql;"
        fixer = IdempotencyFixer()

        result = fixer.fix(sql)

        assert result == sql


class TestCreateViewFix:
    """Tests for CREATE VIEW auto-fix."""

    def test_adds_or_replace_to_create_view(self):
        """Adds OR REPLACE to CREATE VIEW."""
        sql = "CREATE VIEW v_users AS SELECT * FROM users;"
        fixer = IdempotencyFixer()

        result = fixer.fix(sql)

        assert "CREATE OR REPLACE VIEW v_users" in result


class TestCreateProcedureFix:
    """Tests for CREATE PROCEDURE auto-fix."""

    def test_adds_or_replace_to_create_procedure(self):
        """Adds OR REPLACE to CREATE PROCEDURE."""
        sql = "CREATE PROCEDURE do_something() LANGUAGE plpgsql AS $$ BEGIN END; $$;"
        fixer = IdempotencyFixer()

        result = fixer.fix(sql)

        assert "CREATE OR REPLACE PROCEDURE do_something" in result


class TestAlterTableAddColumnFix:
    """Tests for ALTER TABLE ADD COLUMN auto-fix."""

    def test_adds_if_not_exists_to_add_column(self):
        """Adds IF NOT EXISTS to ALTER TABLE ADD COLUMN (PostgreSQL 9.6+)."""
        sql = "ALTER TABLE users ADD COLUMN email TEXT;"
        fixer = IdempotencyFixer()

        result = fixer.fix(sql)

        assert "ALTER TABLE users ADD COLUMN IF NOT EXISTS email" in result

    def test_handles_add_column_without_column_keyword(self):
        """Handles ALTER TABLE ADD without COLUMN keyword."""
        sql = "ALTER TABLE users ADD email TEXT;"
        fixer = IdempotencyFixer()

        result = fixer.fix(sql)

        # Should add both COLUMN and IF NOT EXISTS
        assert "ADD COLUMN IF NOT EXISTS email" in result or "ADD IF NOT EXISTS email" in result


class TestDropStatementFix:
    """Tests for DROP statement auto-fix."""

    def test_adds_if_exists_to_drop_table(self):
        """Adds IF EXISTS to DROP TABLE."""
        sql = "DROP TABLE users;"
        fixer = IdempotencyFixer()

        result = fixer.fix(sql)

        assert "DROP TABLE IF EXISTS users" in result

    def test_adds_if_exists_to_drop_index(self):
        """Adds IF EXISTS to DROP INDEX."""
        sql = "DROP INDEX idx_users_email;"
        fixer = IdempotencyFixer()

        result = fixer.fix(sql)

        assert "DROP INDEX IF EXISTS idx_users_email" in result

    def test_adds_if_exists_to_drop_function(self):
        """Adds IF EXISTS to DROP FUNCTION."""
        sql = "DROP FUNCTION add_nums(INT, INT);"
        fixer = IdempotencyFixer()

        result = fixer.fix(sql)

        assert "DROP FUNCTION IF EXISTS add_nums" in result

    def test_adds_if_exists_to_drop_view(self):
        """Adds IF EXISTS to DROP VIEW."""
        sql = "DROP VIEW v_users;"
        fixer = IdempotencyFixer()

        result = fixer.fix(sql)

        assert "DROP VIEW IF EXISTS v_users" in result

    def test_handles_drop_cascade(self):
        """Preserves CASCADE in DROP statements."""
        sql = "DROP TABLE users CASCADE;"
        fixer = IdempotencyFixer()

        result = fixer.fix(sql)

        assert "DROP TABLE IF EXISTS users CASCADE" in result

    def test_handles_drop_restrict(self):
        """Preserves RESTRICT in DROP statements."""
        sql = "DROP TABLE users RESTRICT;"
        fixer = IdempotencyFixer()

        result = fixer.fix(sql)

        assert "DROP TABLE IF EXISTS users RESTRICT" in result


class TestMultipleStatements:
    """Tests for fixing multiple statements."""

    def test_fixes_multiple_statements(self):
        """Fixes all non-idempotent statements in SQL."""
        sql = dedent("""
            CREATE TABLE users (id INT);
            CREATE INDEX idx_users ON users(id);
            CREATE FUNCTION test() RETURNS VOID AS $$ BEGIN END; $$ LANGUAGE plpgsql;
        """).strip()
        fixer = IdempotencyFixer()

        result = fixer.fix(sql)

        assert "CREATE TABLE IF NOT EXISTS users" in result
        assert "CREATE INDEX IF NOT EXISTS idx_users" in result
        assert "CREATE OR REPLACE FUNCTION test" in result

    def test_preserves_already_idempotent_mixed(self):
        """Preserves idempotent statements while fixing others."""
        sql = dedent("""
            CREATE TABLE IF NOT EXISTS users (id INT);
            CREATE INDEX idx_users ON users(id);
        """).strip()
        fixer = IdempotencyFixer()

        result = fixer.fix(sql)

        # First statement should be unchanged
        assert "CREATE TABLE IF NOT EXISTS users" in result
        # Second should be fixed
        assert "CREATE INDEX IF NOT EXISTS idx_users" in result


class TestDryRun:
    """Tests for dry-run mode."""

    def test_dry_run_returns_changes_without_modifying(self):
        """Dry run reports changes without modifying SQL."""
        sql = "CREATE TABLE users (id INT);"
        fixer = IdempotencyFixer()

        changes = fixer.dry_run(sql)

        assert len(changes) == 1
        assert changes[0].pattern == IdempotencyPattern.CREATE_TABLE
        assert "IF NOT EXISTS" in changes[0].suggested_fix


class TestSelectivePatternFix:
    """Tests for fixing only specific patterns."""

    def test_fix_only_specific_patterns(self):
        """Can fix only specific patterns."""
        sql = dedent("""
            CREATE TABLE users (id INT);
            CREATE INDEX idx ON users(id);
        """).strip()
        fixer = IdempotencyFixer(fix_patterns=[IdempotencyPattern.CREATE_TABLE])

        result = fixer.fix(sql)

        # CREATE TABLE should be fixed
        assert "CREATE TABLE IF NOT EXISTS users" in result
        # CREATE INDEX should NOT be fixed
        assert "CREATE INDEX idx" in result
        assert "IF NOT EXISTS idx" not in result
