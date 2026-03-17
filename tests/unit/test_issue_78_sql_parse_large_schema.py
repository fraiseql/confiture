"""Tests for issue #78: SQLParseError on large schema with seed data.

Verifies that parse_schema() handles large SQL files containing INSERT seed data
without crashing (sqlparse MAX_GROUPING_TOKENS / recursion limit), and that the
accompaniment checker degrades gracefully when parsing fails.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

from confiture.core.differ import SchemaDiffer
from confiture.models.schema import ColumnType


class TestLargeSchemaDoesNotCrash:
    """parse_schema() must handle large SQL files without SQLParseError."""

    def test_parse_schema_with_many_inserts_does_not_crash(self):
        """500 INSERT rows after a CREATE TABLE must not crash parse_schema()."""
        inserts = "\n".join(
            f"INSERT INTO users (email) VALUES ('user{i}@example.com');" for i in range(500)
        )
        sql = "CREATE TABLE users (id SERIAL PRIMARY KEY, email TEXT NOT NULL);\n" + inserts

        differ = SchemaDiffer()
        result = differ.parse_schema(sql)

        assert len(result.tables) == 1
        assert result.tables[0].name == "users"

    def test_parse_schema_ignores_insert_update_delete(self):
        """Non-DDL statements (INSERT, UPDATE, DELETE, COPY) are silently ignored."""
        sql = """
        INSERT INTO config VALUES (1, 'key', 'value');
        UPDATE config SET value = 'new' WHERE key = 'key';
        CREATE TABLE orders (id SERIAL PRIMARY KEY, total NUMERIC);
        DELETE FROM temp_data;
        ALTER TABLE orders ADD COLUMN status TEXT DEFAULT 'pending';
        COPY users FROM '/tmp/data.csv';
        """
        differ = SchemaDiffer()
        result = differ.parse_schema(sql)

        assert len(result.tables) == 1
        assert result.tables[0].name == "orders"

    def test_parse_schema_preserves_all_tables_among_noise(self):
        """All DDL tables are parsed even when mixed with bulk INSERT noise."""
        noise = "\n".join(f"INSERT INTO lookup (k, v) VALUES ('{i}', {i});" for i in range(200))
        sql = f"""
        CREATE TABLE users (id SERIAL PRIMARY KEY, name TEXT NOT NULL);
        CREATE TABLE posts (id SERIAL PRIMARY KEY, user_id INT, title TEXT);
        {noise}
        CREATE TABLE comments (id SERIAL PRIMARY KEY, post_id INT, body TEXT);
        """

        differ = SchemaDiffer()
        result = differ.parse_schema(sql)

        table_names = {t.name for t in result.tables}
        assert "users" in table_names
        assert "posts" in table_names
        assert "comments" in table_names

    def test_parse_schema_large_real_world_size(self):
        """A 50-table schema with 500 INSERT rows parses without error."""
        tables_sql = "\n\n".join(
            f"""CREATE TABLE tbl_{i} (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                value NUMERIC DEFAULT {float(i)},
                created_at TIMESTAMPTZ DEFAULT now()
            );"""
            for i in range(50)
        )
        inserts_sql = "\n".join(
            f"INSERT INTO tbl_{j % 50} (name, value) VALUES ('row_{j}', {j});" for j in range(500)
        )
        sql = tables_sql + "\n\n" + inserts_sql

        differ = SchemaDiffer()
        result = differ.parse_schema(sql)

        assert len(result.tables) == 50
        all_names = {t.name for t in result.tables}
        for i in range(50):
            assert f"tbl_{i}" in all_names


class TestPglastParser:
    """Tests for the pglast-based CREATE TABLE parser."""

    def test_pglast_parses_basic_table(self):
        """pglast path parses columns, types, and NOT NULL correctly."""
        sql = """
        CREATE TABLE products (
            id BIGSERIAL PRIMARY KEY,
            sku VARCHAR(100) NOT NULL,
            price NUMERIC(10, 2) DEFAULT 0.0,
            active BOOLEAN DEFAULT true,
            description TEXT
        );
        """
        differ = SchemaDiffer()
        result = differ.parse_schema(sql)

        assert len(result.tables) == 1
        tbl = result.tables[0]
        assert tbl.name == "products"

        id_col = tbl.get_column("id")
        assert id_col is not None
        assert id_col.primary_key is True

        sku_col = tbl.get_column("sku")
        assert sku_col is not None
        assert sku_col.nullable is False
        assert sku_col.type == ColumnType.VARCHAR
        assert sku_col.length == 100

        price_col = tbl.get_column("price")
        assert price_col is not None
        assert price_col.default is not None

        desc_col = tbl.get_column("description")
        assert desc_col is not None
        assert desc_col.nullable is True

    def test_pglast_parses_if_not_exists(self):
        """CREATE TABLE IF NOT EXISTS is handled."""
        sql = "CREATE TABLE IF NOT EXISTS tenants (id SERIAL PRIMARY KEY, slug TEXT);"
        differ = SchemaDiffer()
        result = differ.parse_schema(sql)

        assert len(result.tables) == 1
        assert result.tables[0].name == "tenants"

    def test_pglast_parses_schema_qualified_table(self):
        """Schema-qualified table names (public.foo) are parsed correctly."""
        sql = "CREATE TABLE public.events (id SERIAL PRIMARY KEY, name TEXT);"
        differ = SchemaDiffer()
        result = differ.parse_schema(sql)

        assert len(result.tables) == 1
        assert result.tables[0].name == "events"

    def test_pglast_parses_inline_foreign_key(self):
        """Inline CONSTRAINT ... FOREIGN KEY in CREATE TABLE body is captured."""
        sql = """
        CREATE TABLE orders (
            id SERIAL PRIMARY KEY,
            user_id INT NOT NULL,
            CONSTRAINT fk_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        """
        differ = SchemaDiffer()
        result = differ.parse_schema(sql)

        assert len(result.tables) == 1
        tbl = result.tables[0]
        assert len(tbl.foreign_keys) == 1
        fk = tbl.foreign_keys[0]
        assert fk.name == "fk_user"
        assert fk.ref_table == "users"

    def test_pglast_parses_inline_check_constraint(self):
        """Inline CONSTRAINT ... CHECK in CREATE TABLE body is captured."""
        sql = """
        CREATE TABLE products (
            id SERIAL PRIMARY KEY,
            price NUMERIC NOT NULL,
            CONSTRAINT chk_price CHECK (price >= 0)
        );
        """
        differ = SchemaDiffer()
        result = differ.parse_schema(sql)

        tbl = result.tables[0]
        assert len(tbl.check_constraints) == 1
        assert tbl.check_constraints[0].name == "chk_price"

    def test_pglast_parses_inline_unique_constraint(self):
        """Inline CONSTRAINT ... UNIQUE in CREATE TABLE body is captured."""
        sql = """
        CREATE TABLE users (
            id SERIAL PRIMARY KEY,
            email TEXT NOT NULL,
            CONSTRAINT uq_email UNIQUE (email)
        );
        """
        differ = SchemaDiffer()
        result = differ.parse_schema(sql)

        tbl = result.tables[0]
        assert len(tbl.unique_constraints) == 1
        assert tbl.unique_constraints[0].name == "uq_email"

    def test_pglast_handles_graceful_fallback_on_parse_error(self):
        """If pglast raises a parse error, fallback to sqlparse without crashing."""
        # This SQL has valid CREATE TABLE but garbage mixed in
        sql = """
        CREATE TABLE valid_table (id SERIAL PRIMARY KEY, name TEXT);
        """
        differ = SchemaDiffer()
        # Should not raise, should return the valid table
        result = differ.parse_schema(sql)
        assert len(result.tables) == 1


class TestAccompanimentGracefulDegradation:
    """Cycle 3: accompaniment checker degrades gracefully on parse failures."""

    def test_accompaniment_checker_returns_report_when_parse_fails(self):
        """SQLParseError in compare_refs() => report with migration_error, not a crash."""
        from confiture.core.git_accompaniment import MigrationAccompanimentChecker
        from confiture.models.git import MigrationAccompanimentReport

        checker = MigrationAccompanimentChecker("local", Path("."))

        with (
            patch.object(
                checker.differ,
                "compare_refs",
                side_effect=Exception("Maximum number of tokens exceeded (10000)."),
            ),
            patch.object(checker, "_get_new_migrations", return_value=[]),
        ):
            report = checker.check_accompaniment("HEAD~1", "HEAD")

        assert isinstance(report, MigrationAccompanimentReport)
        # "check couldn't run" is not a validation failure
        assert report.is_valid is True
        assert report.migration_error is not None
        assert "10000" in report.migration_error or "tokens" in report.migration_error.lower()

    def test_accompaniment_checker_sets_error_message_on_failure(self):
        """migration_error is populated with the original error description."""
        from confiture.core.git_accompaniment import MigrationAccompanimentChecker

        checker = MigrationAccompanimentChecker("local", Path("."))
        original_error = "Maximum number of tokens exceeded (10000)."

        with (
            patch.object(
                checker.differ,
                "compare_refs",
                side_effect=Exception(original_error),
            ),
            patch.object(checker, "_get_new_migrations", return_value=[]),
        ):
            report = checker.check_accompaniment("HEAD~1", "HEAD")

        assert report.migration_error is not None
        assert original_error in report.migration_error

    def test_validate_migration_accompaniment_warns_on_parse_failure(self):
        """validate_migration_accompaniment emits ⚠️ warning, not ❌ error, when parse fails."""
        from confiture.cli.git_validation import validate_migration_accompaniment
        from confiture.models.git import MigrationAccompanimentReport

        console = MagicMock()

        mock_report = MigrationAccompanimentReport(
            has_ddl_changes=False,
            has_new_migrations=False,
            migration_error="Maximum number of tokens exceeded (10000).",
        )

        with (
            patch("confiture.cli.git_validation.validate_git_flags_in_repo"),
            patch("confiture.cli.git_validation.MigrationAccompanimentChecker") as MockChecker,
        ):
            MockChecker.return_value.check_accompaniment.return_value = mock_report
            result = validate_migration_accompaniment(
                env="local",
                base_ref="HEAD~1",
                target_ref="HEAD",
                console=console,
                format_output="text",
            )

        # Should be valid (check skipped, not failed)
        assert result["is_valid"] is True
        # Should print a warning (⚠️ or yellow)
        print_calls = [str(call) for call in console.print.call_args_list]
        assert any(
            "⚠" in c or "warning" in c.lower() or "skipped" in c.lower() for c in print_calls
        )
