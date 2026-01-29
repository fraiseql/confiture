"""Tests for idempotency pattern detection."""

from confiture.core.idempotency.models import IdempotencyPattern
from confiture.core.idempotency.patterns import (
    PatternMatch,
    detect_non_idempotent_patterns,
)


class TestCreateTableDetection:
    """Tests for CREATE TABLE pattern detection."""

    def test_detect_create_table_without_if_not_exists(self):
        """Detects CREATE TABLE without IF NOT EXISTS."""
        sql = "CREATE TABLE users (id INT PRIMARY KEY);"
        matches = detect_non_idempotent_patterns(sql)

        assert len(matches) == 1
        assert matches[0].pattern == IdempotencyPattern.CREATE_TABLE
        assert matches[0].line_number == 1

    def test_skip_create_table_with_if_not_exists(self):
        """Skips CREATE TABLE IF NOT EXISTS (already idempotent)."""
        sql = "CREATE TABLE IF NOT EXISTS users (id INT PRIMARY KEY);"
        matches = detect_non_idempotent_patterns(sql)

        assert len(matches) == 0

    def test_detect_create_table_with_schema(self):
        """Detects schema-qualified CREATE TABLE."""
        sql = "CREATE TABLE app.users (id INT PRIMARY KEY);"
        matches = detect_non_idempotent_patterns(sql)

        assert len(matches) == 1
        assert "app.users" in matches[0].sql_snippet

    def test_multiline_create_table(self):
        """Detects CREATE TABLE spanning multiple lines."""
        sql = """CREATE TABLE users (
            id INT PRIMARY KEY,
            name TEXT NOT NULL
        );"""
        matches = detect_non_idempotent_patterns(sql)

        assert len(matches) == 1
        assert matches[0].pattern == IdempotencyPattern.CREATE_TABLE


class TestCreateIndexDetection:
    """Tests for CREATE INDEX pattern detection."""

    def test_detect_create_index_without_if_not_exists(self):
        """Detects CREATE INDEX without IF NOT EXISTS."""
        sql = "CREATE INDEX idx_users_email ON users(email);"
        matches = detect_non_idempotent_patterns(sql)

        assert len(matches) == 1
        assert matches[0].pattern == IdempotencyPattern.CREATE_INDEX

    def test_skip_create_index_with_if_not_exists(self):
        """Skips CREATE INDEX IF NOT EXISTS."""
        sql = "CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);"
        matches = detect_non_idempotent_patterns(sql)

        assert len(matches) == 0

    def test_detect_create_unique_index(self):
        """Detects CREATE UNIQUE INDEX without IF NOT EXISTS."""
        sql = "CREATE UNIQUE INDEX idx_users_email ON users(email);"
        matches = detect_non_idempotent_patterns(sql)

        assert len(matches) == 1
        assert matches[0].pattern == IdempotencyPattern.CREATE_UNIQUE_INDEX

    def test_skip_create_index_concurrently_with_if_not_exists(self):
        """Skips CREATE INDEX CONCURRENTLY IF NOT EXISTS."""
        sql = "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_users ON users(email);"
        matches = detect_non_idempotent_patterns(sql)

        assert len(matches) == 0


class TestCreateFunctionDetection:
    """Tests for CREATE FUNCTION pattern detection."""

    def test_detect_create_function_without_or_replace(self):
        """Detects CREATE FUNCTION without OR REPLACE."""
        sql = """CREATE FUNCTION add_numbers(a INT, b INT)
        RETURNS INT AS $$ SELECT a + b; $$ LANGUAGE sql;"""
        matches = detect_non_idempotent_patterns(sql)

        assert len(matches) == 1
        assert matches[0].pattern == IdempotencyPattern.CREATE_FUNCTION

    def test_skip_create_or_replace_function(self):
        """Skips CREATE OR REPLACE FUNCTION."""
        sql = """CREATE OR REPLACE FUNCTION add_numbers(a INT, b INT)
        RETURNS INT AS $$ SELECT a + b; $$ LANGUAGE sql;"""
        matches = detect_non_idempotent_patterns(sql)

        assert len(matches) == 0

    def test_detect_create_procedure_without_or_replace(self):
        """Detects CREATE PROCEDURE without OR REPLACE."""
        sql = "CREATE PROCEDURE do_something() LANGUAGE plpgsql AS $$ BEGIN END; $$;"
        matches = detect_non_idempotent_patterns(sql)

        assert len(matches) == 1
        assert matches[0].pattern == IdempotencyPattern.CREATE_PROCEDURE


class TestCreateViewDetection:
    """Tests for CREATE VIEW pattern detection."""

    def test_detect_create_view_without_or_replace(self):
        """Detects CREATE VIEW without OR REPLACE."""
        sql = "CREATE VIEW v_users AS SELECT * FROM users;"
        matches = detect_non_idempotent_patterns(sql)

        assert len(matches) == 1
        assert matches[0].pattern == IdempotencyPattern.CREATE_VIEW

    def test_skip_create_or_replace_view(self):
        """Skips CREATE OR REPLACE VIEW."""
        sql = "CREATE OR REPLACE VIEW v_users AS SELECT * FROM users;"
        matches = detect_non_idempotent_patterns(sql)

        assert len(matches) == 0


class TestCreateTypeDetection:
    """Tests for CREATE TYPE pattern detection."""

    def test_detect_create_type(self):
        """Detects CREATE TYPE (always non-idempotent without DO block)."""
        sql = "CREATE TYPE mood AS ENUM ('sad', 'happy');"
        matches = detect_non_idempotent_patterns(sql)

        assert len(matches) == 1
        assert matches[0].pattern == IdempotencyPattern.CREATE_TYPE

    def test_skip_create_type_in_do_block(self):
        """Skips CREATE TYPE wrapped in DO block with type check."""
        sql = """DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'mood') THEN
                CREATE TYPE mood AS ENUM ('sad', 'happy');
            END IF;
        END $$;"""
        matches = detect_non_idempotent_patterns(sql)

        # The CREATE TYPE inside the DO block should not be flagged
        # because the DO block provides the idempotency check
        assert len(matches) == 0


class TestAlterTableAddColumnDetection:
    """Tests for ALTER TABLE ADD COLUMN detection."""

    def test_detect_alter_table_add_column(self):
        """Detects ALTER TABLE ADD COLUMN without protection."""
        sql = "ALTER TABLE users ADD COLUMN email TEXT;"
        matches = detect_non_idempotent_patterns(sql)

        assert len(matches) == 1
        assert matches[0].pattern == IdempotencyPattern.ALTER_TABLE_ADD_COLUMN

    def test_skip_alter_table_add_column_if_not_exists(self):
        """Skips ALTER TABLE ADD COLUMN IF NOT EXISTS (PG 9.6+)."""
        sql = "ALTER TABLE users ADD COLUMN IF NOT EXISTS email TEXT;"
        matches = detect_non_idempotent_patterns(sql)

        assert len(matches) == 0

    def test_skip_alter_table_add_column_in_do_block(self):
        """Skips ADD COLUMN wrapped in DO block with exception handler."""
        sql = """DO $$ BEGIN
            ALTER TABLE users ADD COLUMN email TEXT;
        EXCEPTION WHEN duplicate_column THEN NULL;
        END $$;"""
        matches = detect_non_idempotent_patterns(sql)

        assert len(matches) == 0


class TestDropStatementDetection:
    """Tests for DROP statement detection."""

    def test_detect_drop_table_without_if_exists(self):
        """Detects DROP TABLE without IF EXISTS."""
        sql = "DROP TABLE users;"
        matches = detect_non_idempotent_patterns(sql)

        assert len(matches) == 1
        assert matches[0].pattern == IdempotencyPattern.DROP_TABLE

    def test_skip_drop_table_if_exists(self):
        """Skips DROP TABLE IF EXISTS."""
        sql = "DROP TABLE IF EXISTS users;"
        matches = detect_non_idempotent_patterns(sql)

        assert len(matches) == 0

    def test_detect_drop_index_without_if_exists(self):
        """Detects DROP INDEX without IF EXISTS."""
        sql = "DROP INDEX idx_users_email;"
        matches = detect_non_idempotent_patterns(sql)

        assert len(matches) == 1
        assert matches[0].pattern == IdempotencyPattern.DROP_INDEX

    def test_detect_drop_function_without_if_exists(self):
        """Detects DROP FUNCTION without IF EXISTS."""
        sql = "DROP FUNCTION add_numbers(INT, INT);"
        matches = detect_non_idempotent_patterns(sql)

        assert len(matches) == 1
        assert matches[0].pattern == IdempotencyPattern.DROP_FUNCTION

    def test_detect_drop_view_without_if_exists(self):
        """Detects DROP VIEW without IF EXISTS."""
        sql = "DROP VIEW v_users;"
        matches = detect_non_idempotent_patterns(sql)

        assert len(matches) == 1
        assert matches[0].pattern == IdempotencyPattern.DROP_VIEW


class TestLineNumberTracking:
    """Tests for accurate line number tracking."""

    def test_line_numbers_are_accurate(self):
        """Line numbers correctly identify violation locations."""
        sql = """-- Comment line 1
-- Comment line 2
CREATE TABLE users (id INT);
-- Comment line 4
CREATE INDEX idx ON users(id);
"""
        matches = detect_non_idempotent_patterns(sql)

        assert len(matches) == 2
        # CREATE TABLE is on line 3
        table_match = next(m for m in matches if m.pattern == IdempotencyPattern.CREATE_TABLE)
        assert table_match.line_number == 3
        # CREATE INDEX is on line 5
        index_match = next(m for m in matches if m.pattern == IdempotencyPattern.CREATE_INDEX)
        assert index_match.line_number == 5

    def test_multiline_statement_reports_first_line(self):
        """Multi-line statements report the starting line number."""
        sql = """SELECT 1;
CREATE TABLE users (
    id INT PRIMARY KEY,
    name TEXT
);"""
        matches = detect_non_idempotent_patterns(sql)

        assert len(matches) == 1
        assert matches[0].line_number == 2  # CREATE TABLE starts on line 2


class TestPatternMatch:
    """Tests for PatternMatch dataclass."""

    def test_pattern_match_has_required_fields(self):
        """PatternMatch has all required fields."""
        match = PatternMatch(
            pattern=IdempotencyPattern.CREATE_TABLE,
            sql_snippet="CREATE TABLE users",
            line_number=1,
            start_pos=0,
            end_pos=18,
        )

        assert match.pattern == IdempotencyPattern.CREATE_TABLE
        assert match.sql_snippet == "CREATE TABLE users"
        assert match.line_number == 1
        assert match.start_pos == 0
        assert match.end_pos == 18


class TestMultiplePatterns:
    """Tests for detecting multiple patterns in one file."""

    def test_detect_multiple_violations(self):
        """Detects multiple non-idempotent patterns in one SQL."""
        sql = """
CREATE TABLE users (id INT PRIMARY KEY);
CREATE INDEX idx_users ON users(id);
CREATE FUNCTION fn_test() RETURNS VOID AS $$ BEGIN END; $$ LANGUAGE plpgsql;
DROP TABLE old_table;
"""
        matches = detect_non_idempotent_patterns(sql)

        assert len(matches) == 4
        patterns = {m.pattern for m in matches}
        assert IdempotencyPattern.CREATE_TABLE in patterns
        assert IdempotencyPattern.CREATE_INDEX in patterns
        assert IdempotencyPattern.CREATE_FUNCTION in patterns
        assert IdempotencyPattern.DROP_TABLE in patterns

    def test_mixed_idempotent_and_non_idempotent(self):
        """Correctly distinguishes idempotent from non-idempotent."""
        sql = """
CREATE TABLE IF NOT EXISTS users (id INT);
CREATE TABLE orders (id INT);
CREATE OR REPLACE FUNCTION fn_test() RETURNS VOID AS $$ BEGIN END; $$ LANGUAGE plpgsql;
CREATE FUNCTION fn_bad() RETURNS VOID AS $$ BEGIN END; $$ LANGUAGE plpgsql;
"""
        matches = detect_non_idempotent_patterns(sql)

        assert len(matches) == 2
        # Only CREATE TABLE orders and CREATE FUNCTION fn_bad should be flagged
        snippets = [m.sql_snippet for m in matches]
        assert any("orders" in s for s in snippets)
        assert any("fn_bad" in s for s in snippets)
