"""Tests for idempotency CLI integration."""

from pathlib import Path

from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()


class TestIdempotencyValidateCLI:
    """Tests for confiture migrate validate --idempotent command."""

    def test_validate_idempotent_clean_migrations(self, tmp_path: Path):
        """Clean idempotent migrations pass validation."""
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)

        # Create an idempotent migration
        (migrations_dir / "001_create_users.up.sql").write_text(
            "CREATE TABLE IF NOT EXISTS users (id INT PRIMARY KEY);"
        )

        result = runner.invoke(
            app,
            [
                "migrate",
                "validate",
                "--idempotent",
                "--migrations-dir",
                str(migrations_dir),
            ],
        )

        assert result.exit_code == 0
        assert "idempotent" in result.stdout.lower() or "✅" in result.stdout

    def test_validate_idempotent_finds_violations(self, tmp_path: Path):
        """Non-idempotent migrations are flagged."""
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)

        # Create a non-idempotent migration
        (migrations_dir / "001_create_users.up.sql").write_text(
            "CREATE TABLE users (id INT PRIMARY KEY);"
        )

        result = runner.invoke(
            app,
            [
                "migrate",
                "validate",
                "--idempotent",
                "--migrations-dir",
                str(migrations_dir),
            ],
        )

        assert result.exit_code == 1
        assert "CREATE TABLE" in result.stdout or "violation" in result.stdout.lower()

    def test_validate_idempotent_shows_suggestions(self, tmp_path: Path):
        """Validation shows fix suggestions for violations."""
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)

        (migrations_dir / "001_create_users.up.sql").write_text(
            "CREATE TABLE users (id INT PRIMARY KEY);"
        )

        result = runner.invoke(
            app,
            [
                "migrate",
                "validate",
                "--idempotent",
                "--migrations-dir",
                str(migrations_dir),
            ],
        )

        assert "IF NOT EXISTS" in result.stdout

    def test_validate_idempotent_multiple_files(self, tmp_path: Path):
        """Validates multiple migration files."""
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)

        (migrations_dir / "001_create_users.up.sql").write_text(
            "CREATE TABLE users (id INT PRIMARY KEY);"
        )
        (migrations_dir / "002_create_index.up.sql").write_text(
            "CREATE INDEX idx_users ON users(id);"
        )

        result = runner.invoke(
            app,
            [
                "migrate",
                "validate",
                "--idempotent",
                "--migrations-dir",
                str(migrations_dir),
            ],
        )

        # Both files should have violations reported
        assert result.exit_code == 1
        assert "001_create_users" in result.stdout or "users" in result.stdout.lower()
        assert "002_create_index" in result.stdout or "index" in result.stdout.lower()

    def test_validate_idempotent_json_output(self, tmp_path: Path):
        """JSON output format works for idempotency validation."""
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)

        (migrations_dir / "001_create_users.up.sql").write_text(
            "CREATE TABLE users (id INT PRIMARY KEY);"
        )

        result = runner.invoke(
            app,
            [
                "migrate",
                "validate",
                "--idempotent",
                "--format",
                "json",
                "--migrations-dir",
                str(migrations_dir),
            ],
        )

        import json

        # Should be valid JSON
        output = json.loads(result.stdout)
        assert "violations" in output or "status" in output

    def test_validate_idempotent_file_output(self, tmp_path: Path):
        """Can save validation report to file."""
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)
        output_file = tmp_path / "report.json"

        (migrations_dir / "001_create_users.up.sql").write_text(
            "CREATE TABLE users (id INT PRIMARY KEY);"
        )

        runner.invoke(
            app,
            [
                "migrate",
                "validate",
                "--idempotent",
                "--format",
                "json",
                "--output",
                str(output_file),
                "--migrations-dir",
                str(migrations_dir),
            ],
        )

        assert output_file.exists()

    def test_validate_idempotent_empty_dir(self, tmp_path: Path):
        """Empty migrations directory handles gracefully."""
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)

        result = runner.invoke(
            app,
            [
                "migrate",
                "validate",
                "--idempotent",
                "--migrations-dir",
                str(migrations_dir),
            ],
        )

        assert result.exit_code == 0


class TestIdempotencyFixCLI:
    """Tests for confiture migrate fix --idempotent command."""

    def test_fix_idempotent_transforms_sql(self, tmp_path: Path):
        """Fix command transforms non-idempotent SQL to idempotent."""
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)

        migration_file = migrations_dir / "001_create_users.up.sql"
        migration_file.write_text("CREATE TABLE users (id INT PRIMARY KEY);")

        result = runner.invoke(
            app,
            [
                "migrate",
                "fix",
                "--idempotent",
                "--migrations-dir",
                str(migrations_dir),
            ],
        )

        assert result.exit_code == 0

        # File should be modified
        fixed_content = migration_file.read_text()
        assert "IF NOT EXISTS" in fixed_content

    def test_fix_idempotent_dry_run(self, tmp_path: Path):
        """Dry run shows changes without modifying files."""
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)

        migration_file = migrations_dir / "001_create_users.up.sql"
        original_content = "CREATE TABLE users (id INT PRIMARY KEY);"
        migration_file.write_text(original_content)

        result = runner.invoke(
            app,
            [
                "migrate",
                "fix",
                "--idempotent",
                "--dry-run",
                "--migrations-dir",
                str(migrations_dir),
            ],
        )

        assert result.exit_code == 0

        # File should NOT be modified
        assert migration_file.read_text() == original_content

        # Output should show what would change
        assert "IF NOT EXISTS" in result.stdout

    def test_fix_idempotent_multiple_files(self, tmp_path: Path):
        """Fix command handles multiple files."""
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)

        file1 = migrations_dir / "001_create_users.up.sql"
        file1.write_text("CREATE TABLE users (id INT);")

        file2 = migrations_dir / "002_create_index.up.sql"
        file2.write_text("CREATE INDEX idx_users ON users(id);")

        result = runner.invoke(
            app,
            [
                "migrate",
                "fix",
                "--idempotent",
                "--migrations-dir",
                str(migrations_dir),
            ],
        )

        assert result.exit_code == 0
        assert "IF NOT EXISTS" in file1.read_text()
        assert "IF NOT EXISTS" in file2.read_text()

    def test_fix_idempotent_preserves_already_idempotent(self, tmp_path: Path):
        """Fix command preserves files that are already idempotent."""
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)

        migration_file = migrations_dir / "001_create_users.up.sql"
        idempotent_content = "CREATE TABLE IF NOT EXISTS users (id INT PRIMARY KEY);"
        migration_file.write_text(idempotent_content)

        result = runner.invoke(
            app,
            [
                "migrate",
                "fix",
                "--idempotent",
                "--migrations-dir",
                str(migrations_dir),
            ],
        )

        assert result.exit_code == 0
        # Content should remain unchanged
        assert migration_file.read_text() == idempotent_content

    def test_fix_idempotent_json_output(self, tmp_path: Path):
        """JSON output format works for fix command."""
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)

        (migrations_dir / "001_create_users.up.sql").write_text(
            "CREATE TABLE users (id INT PRIMARY KEY);"
        )

        result = runner.invoke(
            app,
            [
                "migrate",
                "fix",
                "--idempotent",
                "--dry-run",
                "--format",
                "json",
                "--migrations-dir",
                str(migrations_dir),
            ],
        )

        import json

        output = json.loads(result.stdout)
        assert "files" in output or "fixed" in output or "changes" in output


class TestIdempotencyValidateCombined:
    """Tests for combined naming + idempotency validation."""

    def test_validate_both_naming_and_idempotent(self, tmp_path: Path):
        """Can run both naming and idempotency validation together."""
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)

        # Valid naming but not idempotent
        (migrations_dir / "001_create_users.up.sql").write_text(
            "CREATE TABLE users (id INT PRIMARY KEY);"
        )

        result = runner.invoke(
            app,
            [
                "migrate",
                "validate",
                "--idempotent",
                "--migrations-dir",
                str(migrations_dir),
            ],
        )

        # Should fail due to idempotency issue
        assert result.exit_code == 1

    def test_validate_naming_only_by_default(self, tmp_path: Path):
        """Without --idempotent flag, only naming is checked."""
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)

        # Valid naming but not idempotent - should pass without --idempotent
        (migrations_dir / "001_create_users.up.sql").write_text(
            "CREATE TABLE users (id INT PRIMARY KEY);"
        )

        result = runner.invoke(
            app,
            [
                "migrate",
                "validate",
                "--migrations-dir",
                str(migrations_dir),
            ],
        )

        # Should pass since naming is valid
        assert result.exit_code == 0


_PY_MIGRATION_TEMPLATE = """\
from confiture.models.migration import Migration


class M(Migration):
    version = "{version}"
    name = "{name}"

    def up(self) -> None:
{body}

    def down(self) -> None:
        pass
"""


def _write_py_migration(
    dir_: Path,
    *,
    version: str,
    name: str,
    body_lines: list[str],
) -> Path:
    indented = "\n".join(" " * 8 + line for line in body_lines)
    text = _PY_MIGRATION_TEMPLATE.format(version=version, name=name, body=indented)
    path = dir_ / f"{version}_{name}.py"
    path.write_text(text, encoding="utf-8")
    return path


class TestIdempotencyValidatePythonMigrations:
    """Phase 02: --idempotent now scans .py migrations alongside .up.sql."""

    def test_python_only_dir_with_non_idempotent_create_table_exits_1(self, tmp_path: Path) -> None:
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)
        _write_py_migration(
            migrations_dir,
            version="20260101000000",
            name="demo",
            body_lines=['self.execute("CREATE TABLE foo (id int);")'],
        )

        result = runner.invoke(
            app,
            [
                "migrate",
                "validate",
                "--idempotent",
                "--migrations-dir",
                str(migrations_dir),
            ],
        )

        assert result.exit_code == 1, result.stdout
        assert "20260101000000_demo.py" in result.stdout
        assert "CREATE TABLE" in result.stdout or "CREATE_TABLE" in result.stdout

    def test_violation_carries_source_line_in_json(self, tmp_path: Path) -> None:
        """Cycle 2: source_line is the .py line of the self.execute() call."""
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)
        py_path = _write_py_migration(
            migrations_dir,
            version="20260101000001",
            name="lined",
            body_lines=['self.execute("CREATE TABLE foo (id int);")'],
        )

        result = runner.invoke(
            app,
            [
                "migrate",
                "validate",
                "--idempotent",
                "--format",
                "json",
                "--migrations-dir",
                str(migrations_dir),
            ],
        )

        import json

        payload = json.loads(result.stdout)
        assert payload["status"] == "issues_found"
        assert len(payload["violations"]) == 1
        v = payload["violations"][0]
        assert v["file_path"] == str(py_path)
        assert v["source_line"] == 9  # body starts at indented line 9 of template

    def test_sql_violation_omits_source_line(self, tmp_path: Path) -> None:
        """Cycle 2: SQL-origin violations still have no source_line key."""
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)
        (migrations_dir / "001_x.up.sql").write_text("CREATE TABLE foo (id int);")

        result = runner.invoke(
            app,
            [
                "migrate",
                "validate",
                "--idempotent",
                "--format",
                "json",
                "--migrations-dir",
                str(migrations_dir),
            ],
        )

        import json

        payload = json.loads(result.stdout)
        assert "source_line" not in payload["violations"][0]

    def test_mixed_sql_and_python_directory(self, tmp_path: Path) -> None:
        """Cycle 3: violations from both kinds appear in the same report."""
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)
        (migrations_dir / "001_sqlonly.up.sql").write_text("CREATE TABLE sql_one (id int);")
        _write_py_migration(
            migrations_dir,
            version="20260101000002",
            name="pyonly",
            body_lines=['self.execute("CREATE TABLE py_one (id int);")'],
        )

        result = runner.invoke(
            app,
            [
                "migrate",
                "validate",
                "--idempotent",
                "--migrations-dir",
                str(migrations_dir),
            ],
        )

        assert result.exit_code == 1
        assert "001_sqlonly.up.sql" in result.stdout
        assert "20260101000002_pyonly.py" in result.stdout

    def test_dynamic_only_python_migration_warns_but_passes(self, tmp_path: Path) -> None:
        """Cycle 4: dynamic-only migration prints warnings, exit 0."""
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)
        _write_py_migration(
            migrations_dir,
            version="20260101000003",
            name="dyn",
            body_lines=['sql = "CREATE TABLE foo (id int);"', "self.execute(sql)"],
        )

        result = runner.invoke(
            app,
            [
                "migrate",
                "validate",
                "--idempotent",
                "--migrations-dir",
                str(migrations_dir),
            ],
        )

        assert result.exit_code == 0
        assert "⚠️" in result.stdout
        assert "20260101000003_dyn.py" in result.stdout
        assert "dynamic" in result.stdout.lower()

    def test_warnings_in_json_output(self, tmp_path: Path) -> None:
        """Cycle 5: JSON has warnings and has_warnings keys."""
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)
        _write_py_migration(
            migrations_dir,
            version="20260101000004",
            name="dynjson",
            body_lines=['sql = "x"', "self.execute(sql)"],
        )

        result = runner.invoke(
            app,
            [
                "migrate",
                "validate",
                "--idempotent",
                "--format",
                "json",
                "--migrations-dir",
                str(migrations_dir),
            ],
        )

        import json

        payload = json.loads(result.stdout)
        assert payload["has_warnings"] is True
        assert len(payload["warnings"]) == 1
        w = payload["warnings"][0]
        assert w["kind"] == "dynamic_execute"
        assert "20260101000004_dynjson.py" in w["source_file"]
        assert isinstance(w["source_line"], int)
        assert isinstance(w["message"], str)

    def test_violations_and_warnings_together(self, tmp_path: Path) -> None:
        """Cycle 6: static violation + dynamic warning render together; exit 1."""
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)
        _write_py_migration(
            migrations_dir,
            version="20260101000005",
            name="static",
            body_lines=['self.execute("CREATE TABLE foo (id int);")'],
        )
        _write_py_migration(
            migrations_dir,
            version="20260101000006",
            name="dyn",
            body_lines=['sql = "x"', "self.execute(sql)"],
        )

        result = runner.invoke(
            app,
            [
                "migrate",
                "validate",
                "--idempotent",
                "--migrations-dir",
                str(migrations_dir),
            ],
        )

        assert result.exit_code == 1
        assert "CREATE TABLE" in result.stdout or "CREATE_TABLE" in result.stdout
        assert "⚠️" in result.stdout

    def test_execute_file_validates_referenced_sql(self, tmp_path: Path) -> None:
        """Cycle 7: execute_file("...") flows its SQL through the validator."""
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)
        schema_dir = tmp_path / "db" / "schema"
        schema_dir.mkdir(parents=True)
        (schema_dir / "foo.sql").write_text("CREATE TABLE foo (id int);")
        _write_py_migration(
            migrations_dir,
            version="20260101000007",
            name="usesfile",
            body_lines=['self.execute_file("db/schema/foo.sql")'],
        )

        import os

        prev = Path.cwd()
        try:
            os.chdir(tmp_path)
            result = runner.invoke(
                app,
                [
                    "migrate",
                    "validate",
                    "--idempotent",
                    "--migrations-dir",
                    str(migrations_dir),
                ],
            )
        finally:
            os.chdir(prev)

        assert result.exit_code == 1
        assert "CREATE TABLE" in result.stdout or "CREATE_TABLE" in result.stdout

    def test_init_and_underscore_py_files_are_ignored(self, tmp_path: Path) -> None:
        """Cycle 8: __init__.py, _helpers.py, no-digit-prefix files are skipped."""
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)
        (migrations_dir / "__init__.py").write_text(
            "from confiture.models.migration import Migration\n"
            "class X(Migration):\n"
            '    version = "x"\n'
            '    name = "x"\n'
            "    def up(self):\n"
            '        self.execute("CREATE TABLE i (id int);")\n'
            "    def down(self):\n"
            "        pass\n"
        )
        (migrations_dir / "helpers.py").write_text(
            "from confiture.models.migration import Migration\n"
            "class H(Migration):\n"
            '    version = "h"\n'
            '    name = "h"\n'
            "    def up(self):\n"
            '        self.execute("CREATE TABLE h (id int);")\n'
            "    def down(self):\n"
            "        pass\n"
        )
        (migrations_dir / "_private.py").write_text(
            "from confiture.models.migration import Migration\n"
            "class P(Migration):\n"
            '    version = "p"\n'
            '    name = "p"\n'
            "    def up(self):\n"
            '        self.execute("CREATE TABLE p (id int);")\n'
            "    def down(self):\n"
            "        pass\n"
        )

        result = runner.invoke(
            app,
            [
                "migrate",
                "validate",
                "--idempotent",
                "--migrations-dir",
                str(migrations_dir),
            ],
        )

        # No real migrations present → empty-dir branch.
        assert result.exit_code == 0
        assert "No migration files found" in result.stdout


class TestIdempotencyFixPythonMigrations:
    """Phase 02b: migrate fix --idempotent is Python-aware."""

    def test_python_only_dir_no_writes_applied(self, tmp_path: Path) -> None:
        """Cycle 1: .py-only dir, no fixes applied; .py file never rewritten."""
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)
        py_path = _write_py_migration(
            migrations_dir,
            version="20260601000000",
            name="needs_fix",
            body_lines=['self.execute("CREATE TABLE foo (id int);")'],
        )

        mtime_before = py_path.stat().st_mtime_ns
        body_before = py_path.read_text(encoding="utf-8")

        result = runner.invoke(
            app,
            [
                "migrate",
                "fix",
                "--idempotent",
                "--migrations-dir",
                str(migrations_dir),
            ],
        )

        assert result.exit_code == 0, result.stdout
        assert py_path.read_text(encoding="utf-8") == body_before
        assert py_path.stat().st_mtime_ns == mtime_before
        assert "cannot be auto-fixed" in result.stdout
        assert "20260601000000_needs_fix.py" in result.stdout

    def test_mixed_dir_sql_fixed_python_untouched(self, tmp_path: Path) -> None:
        """Cycle 2: .sql is rewritten in place; .py left untouched."""
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)

        sql_path = migrations_dir / "001_sql.up.sql"
        sql_path.write_text("CREATE TABLE sql_one (id int);", encoding="utf-8")

        py_path = _write_py_migration(
            migrations_dir,
            version="20260601000001",
            name="py_one",
            body_lines=['self.execute("CREATE TABLE py_one (id int);")'],
        )
        py_body_before = py_path.read_text(encoding="utf-8")
        py_mtime_before = py_path.stat().st_mtime_ns

        result = runner.invoke(
            app,
            [
                "migrate",
                "fix",
                "--idempotent",
                "--migrations-dir",
                str(migrations_dir),
            ],
        )

        assert result.exit_code == 0, result.stdout
        # .sql got fixed
        rewritten = sql_path.read_text(encoding="utf-8")
        assert "IF NOT EXISTS" in rewritten
        # .py untouched
        assert py_path.read_text(encoding="utf-8") == py_body_before
        assert py_path.stat().st_mtime_ns == py_mtime_before
        assert "001_sql.up.sql" in result.stdout
        assert "20260601000001_py_one.py" in result.stdout
        assert "cannot be auto-fixed" in result.stdout

    def test_json_output_includes_manual_fix_required(self, tmp_path: Path) -> None:
        """Cycle 3: JSON output lists .py files under manual_fix_required."""
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)

        sql_path = migrations_dir / "001_sql.up.sql"
        sql_path.write_text("CREATE TABLE sql_one (id int);", encoding="utf-8")
        py_path = _write_py_migration(
            migrations_dir,
            version="20260601000002",
            name="py_one",
            body_lines=['self.execute("CREATE TABLE py_one (id int);")'],
        )

        result = runner.invoke(
            app,
            [
                "migrate",
                "fix",
                "--idempotent",
                "--format",
                "json",
                "--migrations-dir",
                str(migrations_dir),
            ],
        )

        import json

        payload = json.loads(result.stdout)
        assert "manual_fix_required" in payload
        manual = payload["manual_fix_required"]
        assert isinstance(manual, list)
        assert any(str(py_path) in m or "20260601000002_py_one.py" in m for m in manual)
        # Existing files_changed / files list keeps the .sql entry
        files_list = payload.get("files") or payload.get("files_changed") or []
        assert any(
            "001_sql.up.sql" in (f.get("file", "") if isinstance(f, dict) else f)
            for f in files_list
        )

    def test_dry_run_does_not_write_either_kind(self, tmp_path: Path) -> None:
        """Cycle 4: --dry-run leaves both .sql and .py on disk untouched."""
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)

        sql_path = migrations_dir / "001_sql.up.sql"
        sql_path.write_text("CREATE TABLE sql_one (id int);", encoding="utf-8")
        sql_body_before = sql_path.read_text(encoding="utf-8")

        py_path = _write_py_migration(
            migrations_dir,
            version="20260601000003",
            name="py_one",
            body_lines=['self.execute("CREATE TABLE py_one (id int);")'],
        )
        py_body_before = py_path.read_text(encoding="utf-8")

        result = runner.invoke(
            app,
            [
                "migrate",
                "fix",
                "--idempotent",
                "--dry-run",
                "--migrations-dir",
                str(migrations_dir),
            ],
        )

        assert result.exit_code == 0, result.stdout
        assert sql_path.read_text(encoding="utf-8") == sql_body_before
        assert py_path.read_text(encoding="utf-8") == py_body_before
        # Dry-run still surfaces both: .sql change preview AND .py manual notice
        assert "001_sql.up.sql" in result.stdout
        assert "20260601000003_py_one.py" in result.stdout


class TestPhase03CLIIntegration:
    """Cycles 10 + 11: new patterns reach the CLI both via .sql and via .py."""

    def test_all_new_patterns_via_sql(self, tmp_path: Path) -> None:
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)
        (migrations_dir / "001_constraints.up.sql").write_text(
            "ALTER TABLE foo ADD CONSTRAINT chk_x CHECK (id > 0);\n"
            "ALTER TABLE foo ADD CONSTRAINT foo_pk PRIMARY KEY (id);\n"
            "ALTER TABLE foo ADD CONSTRAINT foo_uq UNIQUE (email);\n"
            "ALTER TABLE foo RENAME COLUMN old TO new;\n"
            "ALTER TABLE foo OWNER TO alice;\n"
            "ALTER VIEW v_foo OWNER TO alice;\n"
            "ALTER MATERIALIZED VIEW mv_foo OWNER TO alice;\n"
        )

        result = runner.invoke(
            app,
            [
                "migrate",
                "validate",
                "--idempotent",
                "--migrations-dir",
                str(migrations_dir),
            ],
        )

        assert result.exit_code == 1, result.stdout
        for token in (
            "ADD_CONSTRAINT_CHECK",
            "ADD_CONSTRAINT_PRIMARY_KEY",
            "ADD_CONSTRAINT_UNIQUE",
            "RENAME_COLUMN",
            "ALTER_TABLE_OWNER",
            "ALTER_VIEW_OWNER",
            "ALTER_MATVIEW_OWNER",
        ):
            assert token in result.stdout, f"missing token {token} in output"

    def test_new_pattern_via_python_migration(self, tmp_path: Path) -> None:
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)
        _write_py_migration(
            migrations_dir,
            version="20260601100000",
            name="add_check",
            body_lines=[
                'self.execute("ALTER TABLE foo ADD CONSTRAINT chk_x CHECK (id > 0);")',
            ],
        )

        result = runner.invoke(
            app,
            [
                "migrate",
                "validate",
                "--idempotent",
                "--migrations-dir",
                str(migrations_dir),
            ],
        )

        assert result.exit_code == 1
        assert "ADD_CONSTRAINT_CHECK" in result.stdout
        assert "20260601100000_add_check.py" in result.stdout


class TestPhase04SeverityCLI:
    """Cycles 7-10: --strict-cor + info-severity rendering through the CLI."""

    def test_json_violation_carries_severity_and_blocking_key(self, tmp_path: Path) -> None:
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)
        (migrations_dir / "001_cor_view.up.sql").write_text(
            "CREATE OR REPLACE VIEW v_x AS SELECT 1;\n"
        )

        result = runner.invoke(
            app,
            [
                "migrate",
                "validate",
                "--idempotent",
                "--format",
                "json",
                "--migrations-dir",
                str(migrations_dir),
            ],
        )

        import json

        payload = json.loads(result.stdout)
        assert payload["has_blocking_violations"] is False
        assert len(payload["violations"]) == 1
        assert payload["violations"][0]["severity"] == "info"
        assert result.exit_code == 0

    def test_error_violation_sets_blocking_key_true(self, tmp_path: Path) -> None:
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)
        (migrations_dir / "001_err.up.sql").write_text("CREATE TABLE foo (id int);")

        result = runner.invoke(
            app,
            [
                "migrate",
                "validate",
                "--idempotent",
                "--format",
                "json",
                "--migrations-dir",
                str(migrations_dir),
            ],
        )

        import json

        payload = json.loads(result.stdout)
        assert payload["has_blocking_violations"] is True
        assert payload["violations"][0]["severity"] == "error"
        assert result.exit_code == 1

    def test_text_output_renders_info_in_separate_section(self, tmp_path: Path) -> None:
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)
        (migrations_dir / "001_cor.up.sql").write_text("CREATE OR REPLACE VIEW v_x AS SELECT 1;\n")

        result = runner.invoke(
            app,
            [
                "migrate",
                "validate",
                "--idempotent",
                "--migrations-dir",
                str(migrations_dir),
            ],
        )

        assert result.exit_code == 0
        assert "ℹ️" in result.stdout
        assert "informational" in result.stdout
        assert "--strict-cor" in result.stdout

    def test_strict_cor_flips_exit_code_for_info_findings(self, tmp_path: Path) -> None:
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)
        (migrations_dir / "001_cor.up.sql").write_text("CREATE OR REPLACE VIEW v_x AS SELECT 1;\n")

        result = runner.invoke(
            app,
            [
                "migrate",
                "validate",
                "--idempotent",
                "--strict-cor",
                "--migrations-dir",
                str(migrations_dir),
            ],
        )

        assert result.exit_code == 1
        # Severity stays info; only the gate flipped.
        assert "ℹ️" in result.stdout

    def test_python_migration_inherits_info_severity(self, tmp_path: Path) -> None:
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)
        _write_py_migration(
            migrations_dir,
            version="20260601200000",
            name="cor_view",
            body_lines=[
                'self.execute("CREATE OR REPLACE VIEW v_x AS SELECT 1;")',
            ],
        )

        result = runner.invoke(
            app,
            [
                "migrate",
                "validate",
                "--idempotent",
                "--format",
                "json",
                "--migrations-dir",
                str(migrations_dir),
            ],
        )

        import json

        payload = json.loads(result.stdout)
        assert payload["has_blocking_violations"] is False
        assert payload["violations"][0]["severity"] == "info"
        assert payload["violations"][0]["source_line"] is not None
        assert result.exit_code == 0
