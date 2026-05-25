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
        """CREATE OR REPLACE FUNCTION is never an error-severity violation.

        It may emit an info-severity shape-risk note (added in 0.13.0);
        that's not a gate failure, so we only assert on error-severity
        matches here.
        """
        sql = """CREATE OR REPLACE FUNCTION add_numbers(a INT, b INT)
        RETURNS INT AS $$ SELECT a + b; $$ LANGUAGE sql;"""
        matches = detect_non_idempotent_patterns(sql)

        assert [m for m in matches if m.severity == "error"] == []

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
        """CREATE OR REPLACE VIEW is never an error-severity violation.

        Since 0.13.0 a bare CoR VIEW emits an info-severity shape-risk
        note; the gate isn't affected.
        """
        sql = "CREATE OR REPLACE VIEW v_users AS SELECT * FROM users;"
        matches = detect_non_idempotent_patterns(sql)

        assert [m for m in matches if m.severity == "error"] == []


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
        """Distinguishes idempotent from non-idempotent (gate-relevant only).

        Since 0.13.0, ``CREATE OR REPLACE FUNCTION`` emits an info-severity
        shape-risk note. The gate only cares about error-severity matches.
        """
        sql = """
CREATE TABLE IF NOT EXISTS users (id INT);
CREATE TABLE orders (id INT);
CREATE OR REPLACE FUNCTION fn_test() RETURNS VOID AS $$ BEGIN END; $$ LANGUAGE plpgsql;
CREATE FUNCTION fn_bad() RETURNS VOID AS $$ BEGIN END; $$ LANGUAGE plpgsql;
"""
        matches = detect_non_idempotent_patterns(sql)
        error_matches = [m for m in matches if m.severity == "error"]

        assert len(error_matches) == 2
        snippets = [m.sql_snippet for m in error_matches]
        assert any("orders" in s for s in snippets)
        assert any("fn_bad" in s for s in snippets)


class TestAlterTableAddConstraintCheck:
    """ADD CONSTRAINT ... CHECK detection."""

    def test_detect_add_constraint_check(self):
        sql = "ALTER TABLE foo ADD CONSTRAINT chk_x CHECK (id > 0);"
        matches = detect_non_idempotent_patterns(sql)
        assert len(matches) == 1
        assert matches[0].pattern == IdempotencyPattern.ALTER_TABLE_ADD_CONSTRAINT_CHECK
        assert matches[0].pattern.fix_available is False

    def test_detect_schema_qualified_add_constraint_check(self):
        sql = "ALTER TABLE app.foo ADD CONSTRAINT chk_x CHECK (id > 0);"
        matches = detect_non_idempotent_patterns(sql)
        assert len(matches) == 1
        assert matches[0].pattern == IdempotencyPattern.ALTER_TABLE_ADD_CONSTRAINT_CHECK

    def test_skip_add_constraint_check_in_do_block(self):
        sql = """DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='chk_x') THEN
                ALTER TABLE foo ADD CONSTRAINT chk_x CHECK (id > 0);
            END IF;
        END $$;"""
        matches = detect_non_idempotent_patterns(sql)
        assert len(matches) == 0


class TestAlterTableAddConstraintPrimaryKey:
    """ADD CONSTRAINT ... PRIMARY KEY detection."""

    def test_detect_add_constraint_primary_key(self):
        sql = "ALTER TABLE foo ADD CONSTRAINT foo_pk PRIMARY KEY (id);"
        matches = detect_non_idempotent_patterns(sql)
        assert len(matches) == 1
        assert matches[0].pattern == IdempotencyPattern.ALTER_TABLE_ADD_CONSTRAINT_PRIMARY_KEY


class TestAlterTableAddConstraintUnique:
    """ADD CONSTRAINT ... UNIQUE detection."""

    def test_detect_add_constraint_unique(self):
        sql = "ALTER TABLE foo ADD CONSTRAINT foo_uq UNIQUE (email);"
        matches = detect_non_idempotent_patterns(sql)
        assert len(matches) == 1
        assert matches[0].pattern == IdempotencyPattern.ALTER_TABLE_ADD_CONSTRAINT_UNIQUE


class TestDropAddConstraintPair:
    """DROP CONSTRAINT IF EXISTS + ADD CONSTRAINT pair recognizer."""

    def test_drop_then_add_constraint_check_is_idempotent(self):
        sql = (
            "ALTER TABLE foo DROP CONSTRAINT IF EXISTS chk_x;"
            "ALTER TABLE foo ADD CONSTRAINT chk_x CHECK (id > 0);"
        )
        matches = detect_non_idempotent_patterns(sql)
        assert matches == []

    def test_drop_then_add_constraint_primary_key_is_idempotent(self):
        sql = (
            "ALTER TABLE foo DROP CONSTRAINT IF EXISTS foo_pk;"
            "ALTER TABLE foo ADD CONSTRAINT foo_pk PRIMARY KEY (id);"
        )
        matches = detect_non_idempotent_patterns(sql)
        assert matches == []

    def test_drop_unrelated_does_not_silence_violation(self):
        # DROP for a *different* constraint name does NOT silence the ADD
        sql = (
            "ALTER TABLE foo DROP CONSTRAINT IF EXISTS chk_other;"
            "ALTER TABLE foo ADD CONSTRAINT chk_x CHECK (id > 0);"
        )
        matches = detect_non_idempotent_patterns(sql)
        assert len(matches) == 1
        assert matches[0].pattern == IdempotencyPattern.ALTER_TABLE_ADD_CONSTRAINT_CHECK


class TestAlterTableRenameColumn:
    """ALTER TABLE ... RENAME COLUMN detection."""

    def test_detect_rename_column(self):
        sql = "ALTER TABLE foo RENAME COLUMN old TO new;"
        matches = detect_non_idempotent_patterns(sql)
        assert len(matches) == 1
        assert matches[0].pattern == IdempotencyPattern.ALTER_TABLE_RENAME_COLUMN
        assert matches[0].pattern.fix_available is False

    def test_detect_rename_column_implicit(self):
        # PG allows omitting "COLUMN"
        sql = "ALTER TABLE foo RENAME old TO new;"
        matches = detect_non_idempotent_patterns(sql)
        assert len(matches) == 1
        assert matches[0].pattern == IdempotencyPattern.ALTER_TABLE_RENAME_COLUMN

    def test_skip_rename_column_in_do_block_with_exception(self):
        sql = """DO $$ BEGIN
            ALTER TABLE foo RENAME COLUMN old TO new;
        EXCEPTION WHEN undefined_column THEN NULL;
        END $$;"""
        matches = detect_non_idempotent_patterns(sql)
        assert len(matches) == 0


class TestOwnerToDetection:
    """ALTER (TABLE|VIEW|MATERIALIZED VIEW) ... OWNER TO."""

    def test_detect_alter_table_owner_to(self):
        sql = "ALTER TABLE foo OWNER TO alice;"
        matches = detect_non_idempotent_patterns(sql)
        assert len(matches) == 1
        assert matches[0].pattern == IdempotencyPattern.ALTER_TABLE_OWNER

    def test_detect_alter_view_owner_to(self):
        sql = "ALTER VIEW v_foo OWNER TO alice;"
        matches = detect_non_idempotent_patterns(sql)
        assert len(matches) == 1
        assert matches[0].pattern == IdempotencyPattern.ALTER_VIEW_OWNER

    def test_detect_alter_materialized_view_owner_to(self):
        sql = "ALTER MATERIALIZED VIEW mv_foo OWNER TO alice;"
        matches = detect_non_idempotent_patterns(sql)
        assert len(matches) == 1
        # MATERIALIZED VIEW must NOT also match the plain VIEW pattern
        assert matches[0].pattern == IdempotencyPattern.ALTER_MATVIEW_OWNER

    def test_owner_to_all_three_in_one_sql(self):
        sql = (
            "ALTER TABLE foo OWNER TO alice;"
            "ALTER VIEW v_foo OWNER TO alice;"
            "ALTER MATERIALIZED VIEW mv_foo OWNER TO alice;"
        )
        matches = detect_non_idempotent_patterns(sql)
        kinds = {m.pattern for m in matches}
        assert kinds == {
            IdempotencyPattern.ALTER_TABLE_OWNER,
            IdempotencyPattern.ALTER_VIEW_OWNER,
            IdempotencyPattern.ALTER_MATVIEW_OWNER,
        }


class TestPhase03KnownLimitations:
    """Document quoted-identifier and multi-clause limitations of the regex detector."""

    def test_quoted_identifier_currently_slips_through(self):
        # Known limitation: \w+ does not match quoted identifiers.
        # A future pglast-backed detector will close this gap.
        sql = 'ALTER TABLE "My-Table" ADD CONSTRAINT "chk-x" CHECK (id > 0);'
        matches = detect_non_idempotent_patterns(sql)
        assert matches == []  # currently missed

    def test_multi_clause_alter_only_first_constraint_flagged(self):
        # Known limitation: only the first ADD CONSTRAINT in a multi-clause
        # ALTER is detected. Comma-split parsing belongs in a future AST upgrade.
        sql = "ALTER TABLE foo ADD CONSTRAINT a CHECK (id > 0), ADD CONSTRAINT b CHECK (id < 10);"
        matches = detect_non_idempotent_patterns(sql)
        assert len(matches) == 1


class TestPatternSeverityPlumbing:
    def test_pattern_definition_default_severity_error(self):
        from confiture.core.idempotency.patterns import PATTERNS

        # All pre-0.13.0 patterns default to "error". Only the three
        # new CoR shape-risk detectors are info-severity.
        info_patterns = {
            "CREATE_OR_REPLACE_VIEW_SHAPE_RISK",
            "CREATE_OR_REPLACE_FUNCTION_SHAPE_RISK",
            "CREATE_OR_REPLACE_PROCEDURE_SHAPE_RISK",
        }
        for pd in PATTERNS:
            if pd.pattern.value in info_patterns:
                assert pd.severity == "info", pd.pattern
            else:
                assert pd.severity == "error", pd.pattern

    def test_create_or_replace_view_finding_has_info_severity(self):
        sql = "CREATE OR REPLACE VIEW v_users AS SELECT id FROM users;"
        matches = detect_non_idempotent_patterns(sql)
        assert len(matches) == 1
        assert matches[0].severity == "info"


class TestCreateOrReplaceViewNote:
    def test_bare_cor_view_emits_info_finding(self):
        sql = "CREATE OR REPLACE VIEW v_users AS SELECT id FROM users;"
        matches = detect_non_idempotent_patterns(sql)
        assert len(matches) == 1
        m = matches[0]
        assert m.pattern == IdempotencyPattern.CREATE_OR_REPLACE_VIEW_SHAPE_RISK
        assert m.severity == "info"

    def test_drop_view_if_exists_then_cor_silences_note(self):
        sql = "DROP VIEW IF EXISTS v_users;CREATE OR REPLACE VIEW v_users AS SELECT id FROM users;"
        matches = detect_non_idempotent_patterns(sql)
        assert matches == []


class TestCreateOrReplaceFunctionNote:
    def test_bare_cor_function_emits_info_finding(self):
        sql = "CREATE OR REPLACE FUNCTION f_summary() RETURNS void AS $$ BEGIN END; $$ LANGUAGE plpgsql;"
        matches = detect_non_idempotent_patterns(sql)
        info_matches = [m for m in matches if m.severity == "info"]
        assert len(info_matches) == 1
        assert info_matches[0].pattern == IdempotencyPattern.CREATE_OR_REPLACE_FUNCTION_SHAPE_RISK

    def test_drop_function_if_exists_then_cor_silences_note(self):
        sql = (
            "DROP FUNCTION IF EXISTS f_summary;"
            "CREATE OR REPLACE FUNCTION f_summary() RETURNS void AS $$ BEGIN END; $$ LANGUAGE plpgsql;"
        )
        matches = detect_non_idempotent_patterns(sql)
        assert [m for m in matches if m.severity == "info"] == []


class TestCreateOrReplaceProcedureNote:
    def test_bare_cor_procedure_emits_info_finding(self):
        sql = "CREATE OR REPLACE PROCEDURE p_sync() AS $$ BEGIN END; $$ LANGUAGE plpgsql;"
        matches = detect_non_idempotent_patterns(sql)
        info_matches = [m for m in matches if m.severity == "info"]
        assert len(info_matches) == 1
        assert info_matches[0].pattern == IdempotencyPattern.CREATE_OR_REPLACE_PROCEDURE_SHAPE_RISK

    def test_drop_procedure_if_exists_then_cor_silences_note(self):
        sql = (
            "DROP PROCEDURE IF EXISTS p_sync;"
            "CREATE OR REPLACE PROCEDURE p_sync() AS $$ BEGIN END; $$ LANGUAGE plpgsql;"
        )
        matches = detect_non_idempotent_patterns(sql)
        assert [m for m in matches if m.severity == "info"] == []
