"""Unit tests for Migration Generator (Milestone 1.11)."""

import re

import pytest

from confiture.core.migration_generator import MigrationGenerator
from confiture.core.schema_change import (
    ColumnAdded,
    ColumnDefaultChanged,
    ColumnDropped,
    ColumnNullabilityChanged,
    ColumnRenamed,
    ColumnTypeChanged,
    SchemaDiff,
    TableAdded,
    TableDropped,
)
from confiture.core.schema_model import RelationName
from tests.unit._schema_changes import replaced, spelled
from tests.unit._schema_models import table


class TestMigrationGenerator:
    """Test migration file generation from schema diffs."""

    def test_generate_migration_creates_file(self, tmp_path):
        """Should create migration file in migrations directory."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        diff = SchemaDiff(
            changes=[ColumnAdded(RelationName(None, "users"), spelled("email", "TEXT"))]
        )

        generator = MigrationGenerator(migrations_dir=migrations_dir)
        migration_file = generator.generate(diff, name="add_users_table")

        assert migration_file.exists()
        assert migration_file.parent == migrations_dir
        assert "add_users_table" in migration_file.name

    def test_generate_migration_with_version_number(self, tmp_path):
        """Should generate timestamp-based version numbers."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        generator = MigrationGenerator(migrations_dir=migrations_dir)

        # First migration should have timestamp format
        diff1 = SchemaDiff(
            changes=[ColumnAdded(RelationName(None, "users"), spelled("email", "TEXT"))]
        )
        file1 = generator.generate(diff1, name="add_email")
        assert re.match(r"^\d{14}_", file1.name), (
            f"Filename {file1.name} should start with 14-digit timestamp"
        )

        # Second migration should also have timestamp format (may be same second or later)
        diff2 = SchemaDiff(
            changes=[ColumnAdded(RelationName(None, "posts"), spelled("title", "TEXT"))]
        )
        file2 = generator.generate(diff2, name="add_title")
        assert re.match(r"^\d{14}_", file2.name), (
            f"Filename {file2.name} should start with 14-digit timestamp"
        )
        # Timestamps should be >= (can be same second or later)
        assert file2.name[:14] >= file1.name[:14]

    def test_generate_migration_for_add_table(self, tmp_path):
        """ADD_TABLE renders the CREATE TABLE from the change's columns (issue #196)."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        diff = SchemaDiff(
            changes=[
                TableAdded(
                    table(
                        "users",
                        spelled("id", "integer", nullable=False),
                        spelled("email", "text"),
                    )
                )
            ]
        )
        generator = MigrationGenerator(migrations_dir=migrations_dir)
        content = generator.generate(diff, name="add_users_table").read_text()

        assert 'self.execute("""-- confiture:creates users\nCREATE TABLE users (' in content
        assert "id integer NOT NULL" in content and "email text" in content
        assert 'self.execute("DROP TABLE users;")' in content

    def test_generate_migration_for_drop_table(self, tmp_path):
        """Should generate correct SQL for DROP_TABLE."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        diff = SchemaDiff(changes=[TableDropped(table("old_table"))])

        generator = MigrationGenerator(migrations_dir=migrations_dir)
        migration_file = generator.generate(diff, name="drop_old_table")

        content = migration_file.read_text()

        # Up should drop the table
        assert "DROP TABLE old_table" in content

        # Down would need to recreate it (but the table declared no columns)
        assert (
            "# irreversible: no rollback derived for" in content
            or "CREATE TABLE old_table" in content
        )

    def test_generate_migration_for_add_column(self, tmp_path):
        """Should generate correct SQL for ADD_COLUMN."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        diff = SchemaDiff(
            changes=[
                ColumnAdded(RelationName(None, "users"), spelled("email", "TEXT", nullable=False))
            ]
        )

        generator = MigrationGenerator(migrations_dir=migrations_dir)
        migration_file = generator.generate(diff, name="add_user_email")

        content = migration_file.read_text()

        # Up should add column
        assert "ALTER TABLE users" in content
        assert "ADD COLUMN IF NOT EXISTS email" in content

        # Down should drop column
        assert "DROP COLUMN email" in content

    def test_generate_migration_for_drop_column(self, tmp_path):
        """Should generate correct SQL for DROP_COLUMN."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        diff = SchemaDiff(
            changes=[ColumnDropped(RelationName(None, "users"), spelled("old_field", "TEXT"))]
        )

        generator = MigrationGenerator(migrations_dir=migrations_dir)
        migration_file = generator.generate(diff, name="drop_old_field")

        content = migration_file.read_text()

        # Up should drop column
        assert "ALTER TABLE users" in content
        assert "DROP COLUMN old_field" in content

        # Down restores it from the definition the change carries
        assert "ADD COLUMN old_field TEXT" in content

    def test_generate_migration_for_rename_column(self, tmp_path):
        """Should generate correct SQL for RENAME_COLUMN."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        diff = SchemaDiff(
            changes=[ColumnRenamed(RelationName(None, "users"), "full_name", "display_name")]
        )

        generator = MigrationGenerator(migrations_dir=migrations_dir)
        migration_file = generator.generate(diff, name="rename_user_full_name")

        content = migration_file.read_text()

        # Up should rename column
        assert "ALTER TABLE users" in content
        assert "RENAME COLUMN full_name TO display_name" in content

        # Down should rename back
        assert "RENAME COLUMN display_name TO full_name" in content

    def test_generate_migration_for_change_column_type(self, tmp_path):
        """Should generate correct SQL for CHANGE_COLUMN_TYPE."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        diff = SchemaDiff(
            changes=[
                ColumnTypeChanged(
                    RelationName(None, "users"), spelled("age", "INTEGER"), spelled("age", "BIGINT")
                )
            ]
        )

        generator = MigrationGenerator(migrations_dir=migrations_dir)
        migration_file = generator.generate(diff, name="change_age_to_bigint")

        content = migration_file.read_text()

        # Up should change type
        assert "ALTER TABLE users" in content
        assert "ALTER COLUMN age TYPE BIGINT" in content

        # Down should change back
        assert "ALTER COLUMN age TYPE INTEGER" in content

    def test_generate_migration_for_change_nullable(self, tmp_path):
        """Should generate correct SQL for CHANGE_COLUMN_NULLABLE."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        diff = SchemaDiff(
            changes=[ColumnNullabilityChanged(RelationName(None, "users"), "email", nullable=False)]
        )

        generator = MigrationGenerator(migrations_dir=migrations_dir)
        migration_file = generator.generate(diff, name="make_email_not_null")

        content = migration_file.read_text()

        # Up should add NOT NULL
        assert "ALTER TABLE users" in content
        assert "ALTER COLUMN email SET NOT NULL" in content

        # Down should drop NOT NULL
        assert "ALTER COLUMN email DROP NOT NULL" in content

    def test_generate_migration_for_change_default(self, tmp_path):
        """Should generate correct SQL for CHANGE_COLUMN_DEFAULT."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        diff = SchemaDiff(
            changes=[
                ColumnDefaultChanged(RelationName(None, "settings"), "enabled", "FALSE", "TRUE")
            ]
        )

        generator = MigrationGenerator(migrations_dir=migrations_dir)
        migration_file = generator.generate(diff, name="change_default_enabled")

        content = migration_file.read_text()

        # Up should set new default
        assert "ALTER TABLE settings" in content
        assert "ALTER COLUMN enabled SET DEFAULT TRUE" in content

        # Down should set old default
        assert "ALTER COLUMN enabled SET DEFAULT FALSE" in content

    def test_generate_migration_with_multiple_changes(self, tmp_path):
        """Should generate migration with multiple changes."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        diff = SchemaDiff(
            changes=[
                ColumnAdded(RelationName(None, "users"), spelled("email", "TEXT")),
                ColumnRenamed(RelationName(None, "users"), "name", "username"),
            ]
        )

        generator = MigrationGenerator(migrations_dir=migrations_dir)
        migration_file = generator.generate(diff, name="multiple_changes")

        content = migration_file.read_text()

        # Should contain all changes
        assert "ADD COLUMN email" in content
        assert "RENAME COLUMN name TO username" in content

    def test_generate_migration_empty_diff(self, tmp_path):
        """Should handle empty diff gracefully."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        diff = SchemaDiff(changes=[])

        generator = MigrationGenerator(migrations_dir=migrations_dir)

        with pytest.raises(ValueError, match="No changes to generate"):
            generator.generate(diff, name="empty")

    def test_migration_file_is_valid_python(self, tmp_path):
        """Generated migration file should be valid Python."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        diff = SchemaDiff(changes=[ColumnRenamed(RelationName(None, "users"), "name", "username")])

        generator = MigrationGenerator(migrations_dir=migrations_dir)
        migration_file = generator.generate(diff, name="test_migration")

        # Try to compile the file
        content = migration_file.read_text()
        assert compile(content, str(migration_file), "exec") is not None

    def test_get_next_version_empty_dir(self, tmp_path):
        """Should return timestamp version for empty migrations directory."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        generator = MigrationGenerator(migrations_dir=migrations_dir)
        version = generator._get_next_version()

        assert re.match(r"^\d{14}$", version), f"Version {version} should be 14-digit timestamp"

    def test_get_next_version_with_existing(self, tmp_path):
        """Should return timestamp version regardless of existing migrations."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        # Create existing migrations (old format or new format - doesn't matter)
        (migrations_dir / "001_first.py").touch()
        (migrations_dir / "002_second.py").touch()

        generator = MigrationGenerator(migrations_dir=migrations_dir)
        version = generator._get_next_version()

        assert re.match(r"^\d{14}$", version), f"Version {version} should be 14-digit timestamp"

    def test_to_class_name_conversion(self, tmp_path):
        """Should convert snake_case to PascalCase."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        diff = SchemaDiff(
            changes=[ColumnAdded(RelationName(None, "users"), spelled("email", "TEXT"))]
        )

        generator = MigrationGenerator(migrations_dir=migrations_dir)
        migration_file = generator.generate(diff, name="add_users_table")

        content = migration_file.read_text()

        # Should have PascalCase class name
        assert "class AddUsersTable(Migration):" in content


class TestGenerateSql:
    """``generate_sql`` writes the pair every reader of a migration understands."""

    def test_writes_an_up_and_a_down_file(self, tmp_path):
        diff = SchemaDiff(
            changes=[
                ColumnAdded(RelationName(None, "users"), spelled("bio", "TEXT")),
                ColumnAdded(RelationName(None, "users"), spelled("age", "INTEGER")),
            ]
        )
        up = MigrationGenerator(migrations_dir=tmp_path).generate_sql(
            diff, name="add_profile", version="20260101000000"
        )
        assert up.name == "20260101000000_add_profile.up.sql"
        assert up.read_text() == (
            "-- Migration: add_profile\n-- Version: 20260101000000\n\n"
            "-- confiture:tier additive\nALTER TABLE users ADD COLUMN bio TEXT;\n\n"
            "-- confiture:tier additive\nALTER TABLE users ADD COLUMN age INTEGER;\n"
        )
        down = up.with_name("20260101000000_add_profile.down.sql")
        assert down.read_text() == (
            "-- Migration: add_profile\n-- Version: 20260101000000\n\n"
            "-- confiture:tier irreversible\nALTER TABLE users DROP COLUMN age;\n\n"
            "-- confiture:tier irreversible\nALTER TABLE users DROP COLUMN bio;\n"
        )

    def test_a_change_with_no_sql_leaves_a_warning_not_silence(self, tmp_path):
        diff = SchemaDiff(
            changes=[
                replaced(
                    "domain",
                    "d_positive",
                    "CREATE DOMAIN d_positive AS integer CHECK (VALUE > 0)",
                    "CREATE DOMAIN d_positive AS integer CHECK (VALUE >= 0)",
                )
            ]
        )
        up = MigrationGenerator(migrations_dir=tmp_path).generate_sql(
            diff, name="redefine", version="20260101000000"
        )
        body = up.read_text().splitlines()[-1]
        assert body.startswith("-- WARNING: no SQL derived for: ")
        assert body.endswith("Edit this file before deploying.")

    def test_refuses_an_empty_diff(self, tmp_path):
        with pytest.raises(ValueError, match="No changes"):
            MigrationGenerator(migrations_dir=tmp_path).generate_sql(SchemaDiff(changes=[]), "x")


def test_a_file_with_a_matview_recreate_and_a_paired_matview_index_runs_in_autocommit(tmp_path):
    """A paired matview index is built ``CONCURRENTLY``, which takes the whole file out of
    a transaction, as a table's does; the recreate is followed by its own indexes."""
    import pglast

    from confiture.core.differ import SchemaDiffer
    from confiture.models.sql_file_migration import _detect_transactional

    base = "CREATE TABLE t (id int, n int);\n"
    old = (
        base + "CREATE MATERIALIZED VIEW mv_a AS SELECT id FROM t;\n"
        "CREATE MATERIALIZED VIEW mv_b AS SELECT id FROM t;\n"
        "CREATE INDEX ix_a ON mv_a (id);\n"
    )
    new = (
        base + "CREATE MATERIALIZED VIEW mv_a AS SELECT id, n FROM t;\n"
        "CREATE MATERIALIZED VIEW mv_b AS SELECT id FROM t;\n"
        "CREATE INDEX ix_a ON mv_a (id);\nCREATE UNIQUE INDEX ux_b ON mv_b (id);\n"
    )
    up = MigrationGenerator(migrations_dir=tmp_path).generate_sql(
        SchemaDiffer().compare(old, new), name="matviews", version="20260101000000"
    )
    statements = [raw.stmt for raw in pglast.parse_sql(up.read_text())]
    shapes = [
        (type(s).__name__, getattr(s, "idxname", None), getattr(s, "concurrent", None))
        for s in statements
    ]
    assert shapes == [
        ("IndexStmt", "ux_b", True),
        ("DropStmt", None, False),
        ("CreateTableAsStmt", None, None),
        ("IndexStmt", "ix_a", False),
    ]
    assert _detect_transactional(up) is False


def _plain_creates(sql: str) -> list[tuple[str | None, str]]:
    """``(schema, name)`` of every table and matview *sql* creates without IF NOT EXISTS."""
    import pglast

    from confiture.core._pglast_enums import member

    matview = member("ObjectType", "OBJECT_MATVIEW")
    found = []
    for raw in pglast.parse_sql(sql):
        stmt = raw.stmt
        if type(stmt).__name__ == "CreateStmt" and not stmt.if_not_exists:
            found.append((stmt.relation.schemaname, stmt.relation.relname))
        elif (
            type(stmt).__name__ == "CreateTableAsStmt"
            and stmt.objtype == matview
            and not stmt.if_not_exists
        ):
            found.append((stmt.into.rel.schemaname, stmt.into.rel.relname))
    return found


def _creates_arguments(sql: str) -> list[str | None]:
    from confiture.core.sql_lexer import directives

    return [d.argument for d in directives(sql) if d.name == "creates"]


def _generated(tmp_path, old: str, new: str) -> tuple[str, str, str]:
    """The up, the down and the ``.py`` confiture generates from *old* to *new*."""
    from confiture.core.differ import SchemaDiffer

    diff = SchemaDiffer().compare(old, new)
    generator = MigrationGenerator(migrations_dir=tmp_path)
    up = generator.generate_sql(diff, name="m", version="20260101000000", destructive="allow")
    down = up.with_name(up.name.replace(".up.sql", ".down.sql"))
    py = generator.generate(diff, name="m", version="20260101000001", destructive="allow")
    return up.read_text(), down.read_text(), py.read_text()


class TestPlainCreates:
    """A file that runs in one transaction creates what it proves new plainly, and says so."""

    OLD = (
        "CREATE TABLE t (id int);\n"
        "CREATE TABLE gone (id int);\n"
        "CREATE MATERIALIZED VIEW mv_gone AS SELECT id FROM t;\n"
        "CREATE MATERIALIZED VIEW mv_r AS SELECT id FROM t;\n"
    )
    NEW = (
        "CREATE TABLE t (id int);\n"
        "CREATE TABLE fresh (id int);\n"
        "CREATE MATERIALIZED VIEW mv_new AS SELECT id FROM t;\n"
        "CREATE MATERIALIZED VIEW mv_r AS SELECT id, 1 AS one FROM t;\n"
    )

    def test_generate_sql_declares_each_relation_it_creates(self, tmp_path):
        up, down, _ = _generated(tmp_path, self.OLD, self.NEW)
        assert sorted(_creates_arguments(up)) == ["fresh", "mv_new", "mv_r"]
        assert sorted(_plain_creates(up)) == [(None, "fresh"), (None, "mv_new"), (None, "mv_r")]
        assert sorted(_creates_arguments(down)) == ["gone", "mv_gone", "mv_r"]
        assert sorted(_plain_creates(down)) == [(None, "gone"), (None, "mv_gone"), (None, "mv_r")]

    def test_the_directive_sits_above_the_blocks_irreversible_and_tier_lines(self, tmp_path):
        up, down, _ = _generated(tmp_path, self.OLD, self.NEW)
        assert "-- confiture:creates fresh\n-- confiture:tier additive\nCREATE TABLE fresh" in up
        replaced = next(b for b in up.split("\n\n") if "DROP MATERIALIZED VIEW IF EXISTS mv_r" in b)
        assert replaced.splitlines()[0] == "-- confiture:creates mv_r"
        assert replaced.splitlines()[1].startswith("-- confiture:tier ")
        block = next(b for b in down.split("\n\n") if "CREATE TABLE gone" in b)
        assert block.splitlines()[0] == "-- confiture:creates gone"

    def test_the_py_form_declares_inside_the_executed_literal(self, tmp_path):
        _, _, py = _generated(tmp_path, self.OLD, self.NEW)
        assert 'self.execute("""-- confiture:creates fresh\nCREATE TABLE fresh (' in py
        assert "-- confiture:creates gone\nCREATE TABLE gone (" in py

    def test_a_file_with_a_concurrent_index_keeps_if_not_exists_and_declares_nothing(
        self, tmp_path
    ):
        old = "CREATE TABLE t (a int);\nCREATE TABLE gone (id int);\n"
        new = "CREATE TABLE t (a int);\nCREATE INDEX ix_t_a ON t (a);\nCREATE TABLE u (id int);\n"
        up, down, py = _generated(tmp_path, old, new)
        for text in (up, down, py):
            assert "confiture:creates" not in text
        assert "CREATE INDEX CONCURRENTLY" in up
        assert _plain_creates(up) == []
        assert _plain_creates(down) == []
        assert "CREATE TABLE IF NOT EXISTS u" in up
        assert "CREATE TABLE IF NOT EXISTS gone" in down
        assert "CREATE TABLE IF NOT EXISTS u" in py

    def test_a_file_with_an_enum_add_value_keeps_if_not_exists(self, tmp_path):
        old = "CREATE TYPE e AS ENUM ('a');\n"
        new = "CREATE TYPE e AS ENUM ('a', 'b');\nCREATE TABLE u (id int);\n"
        up, _, py = _generated(tmp_path, old, new)
        assert "ADD VALUE" in up
        assert "CREATE TABLE IF NOT EXISTS u" in up
        assert "confiture:creates" not in up + py

    def test_the_down_follows_the_up_files_mode(self, tmp_path):
        """The down alone would run in one transaction; it runs in the up's mode, so it re-applies."""
        from confiture.core.migration_analyzer import runs_in_one_transaction

        old = "CREATE TYPE e AS ENUM ('a');\nCREATE TABLE gone (id int);\n"
        new = "CREATE TYPE e AS ENUM ('a', 'b');\n"
        up, down, _ = _generated(tmp_path, old, new)
        assert not runs_in_one_transaction(up)
        assert runs_in_one_transaction(down)
        assert "CREATE TABLE IF NOT EXISTS gone" in down
        assert "confiture:creates" not in down

    def test_a_replace_with_no_statement_is_refused_before_any_file(self, tmp_path):
        from confiture.core.ddl_objects import DDLObject
        from confiture.core.schema_change import ObjectReplaced
        from confiture.exceptions import DifferError
        from tests.unit._schema_changes import ref

        old = DDLObject(
            ref=ref("matview", "mv"),
            definition="CREATE MATERIALIZED VIEW mv AS SELECT 1 AS a",
            create_sql="CREATE MATERIALIZED VIEW IF NOT EXISTS mv AS SELECT 1 AS a",
        )
        empty = DDLObject(ref=ref("matview", "mv"), definition="", create_sql="")
        diff = SchemaDiff(changes=[ObjectReplaced(old.ref, old, empty)])
        with pytest.raises(DifferError) as refused:
            MigrationGenerator(migrations_dir=tmp_path).generate_sql(
                diff, name="m", version="20260101000000"
            )
        assert refused.value.error_code == "DIFFER_409"
        assert list(tmp_path.iterdir()) == []

    def test_a_generated_pair_and_py_have_no_create_table_violation(self, tmp_path):
        from confiture.core.idempotency.validator import IdempotencyValidator

        _generated(tmp_path, self.OLD, self.NEW)
        report = IdempotencyValidator().validate_directory(tmp_path)
        assert len(report.scanned_files) == 3
        assert [v for v in report.violations if v.pattern.value == "CREATE_TABLE"] == []

    def test_a_generated_up_is_a_fixed_point_of_the_create_table_fix(self, tmp_path):
        from confiture.core.idempotency.fixer import IdempotencyFixer
        from confiture.core.idempotency.models import IdempotencyPattern

        up, down, _ = _generated(tmp_path, self.OLD, self.NEW)
        fixer = IdempotencyFixer(fix_patterns=[IdempotencyPattern.CREATE_TABLE])
        assert fixer.fix(up) == up
        assert fixer.fix(down) == down


def test_a_file_with_a_tview_replace_and_its_index_pair_runs_in_autocommit(tmp_path):
    """The index pair straddles ``pg_tviews_create_or_replace()``: the drop before, the add
    after, ``CONCURRENTLY``; the down drops the new one, replaces back, re-creates the old."""
    import pglast

    from confiture.core.differ import SchemaDiffer
    from confiture.models.sql_file_migration import _detect_transactional

    base = "CREATE TABLE t (id int, n int);\n"
    old = base + "CREATE TABLE tv_a AS SELECT id FROM t;\nCREATE INDEX ix_tv_a ON tv_a (id);\n"
    new = base + "CREATE TABLE tv_a AS SELECT id, n FROM t;\nCREATE INDEX ix_tv_a ON tv_a (n);\n"
    up = MigrationGenerator(migrations_dir=tmp_path).generate_sql(
        SchemaDiffer().compare(old, new), name="tviews", version="20260101000000"
    )
    down = up.with_name(up.name.replace(".up.sql", ".down.sql"))

    def shapes(path):
        return [
            (type(s).__name__, getattr(s, "concurrent", None))
            for s in (raw.stmt for raw in pglast.parse_sql(path.read_text()))
        ]

    assert shapes(up) == [("DropStmt", True), ("SelectStmt", None), ("IndexStmt", True)]
    assert shapes(down) == [("DropStmt", True), ("SelectStmt", None), ("IndexStmt", True)]
    assert "(n)" in up.read_text().split("pg_tviews_create_or_replace")[1]
    assert "(id)" in down.read_text().split("pg_tviews_create_or_replace")[1]
    assert _detect_transactional(up) is False
