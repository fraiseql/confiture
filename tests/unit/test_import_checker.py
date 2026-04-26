"""Tests for ImportChecker — migration import validation."""

import json
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.import_checker import ImportChecker

# ---------------------------------------------------------------------------
# Helpers: write migration .py files into a tmp directory
# ---------------------------------------------------------------------------

VALID_MIGRATION = """\
from confiture.models.migration import Migration

class CreateUsers(Migration):
    version = "20260426120000"
    name = "create_users"

    def up(self):
        self.execute("CREATE TABLE users (id INT);")

    def down(self):
        self.execute("DROP TABLE users;")
"""

SYNTAX_ERROR_MIGRATION = """\
from confiture.models.migration import Migration

class Broken(Migration  # missing closing paren
    version = "20260426120001"
    name = "broken"

    def up(self):
        pass

    def down(self):
        pass
"""

NO_MIGRATION_CLASS = """\
# A Python file with no Migration subclass
def hello():
    return "world"
"""

MISSING_VERSION = """\
from confiture.models.migration import Migration

class NoVersion(Migration):
    name = "no_version"

    def up(self):
        pass

    def down(self):
        pass
"""

MISSING_NAME = """\
from confiture.models.migration import Migration

class NoName(Migration):
    version = "20260426120003"

    def up(self):
        pass

    def down(self):
        pass
"""

EMPTY_VERSION = """\
from confiture.models.migration import Migration

class EmptyVersion(Migration):
    version = ""
    name = "empty_version"

    def up(self):
        pass

    def down(self):
        pass
"""

VERSION_NOT_STRING = """\
from confiture.models.migration import Migration

class BadVersion(Migration):
    version = 42
    name = "bad_version"

    def up(self):
        pass

    def down(self):
        pass
"""

ABSTRACT_UP = """\
from confiture.models.migration import Migration

class StillAbstract(Migration):
    version = "20260426120006"
    name = "still_abstract"

    def down(self):
        pass
"""

ABSTRACT_DOWN = """\
from confiture.models.migration import Migration

class NoDown(Migration):
    version = "20260426120007"
    name = "no_down"

    def up(self):
        pass
"""

MISSING_IMPORT = """\
import nonexistent_package_xyz

from confiture.models.migration import Migration

class BadImport(Migration):
    version = "20260426120008"
    name = "bad_import"

    def up(self):
        pass

    def down(self):
        pass
"""


def _write_migration(migrations_dir: Path, filename: str, content: str) -> Path:
    """Write a migration file and return its path."""
    p = migrations_dir / filename
    p.write_text(content, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Level 1: import + class extraction
# ---------------------------------------------------------------------------


class TestLevel1Import:
    """IMP001/IMP002: module import and class extraction."""

    def test_valid_migration_passes(self, tmp_path: Path) -> None:
        _write_migration(tmp_path, "20260426120000_create_users.py", VALID_MIGRATION)

        result = ImportChecker(tmp_path).check()

        assert result.success
        assert result.checked == 1
        assert result.passed == 1
        assert result.failed == 0
        assert result.violations == []

    def test_syntax_error_imp001(self, tmp_path: Path) -> None:
        _write_migration(tmp_path, "20260426120001_broken.py", SYNTAX_ERROR_MIGRATION)

        result = ImportChecker(tmp_path).check()

        assert not result.success
        assert result.failed == 1
        assert len(result.violations) == 1
        v = result.violations[0]
        assert v.rule == "IMP001"
        assert "20260426120001_broken.py" in v.file_path

    def test_no_migration_class_imp002(self, tmp_path: Path) -> None:
        _write_migration(tmp_path, "20260426120002_no_class.py", NO_MIGRATION_CLASS)

        result = ImportChecker(tmp_path).check()

        assert not result.success
        assert result.failed == 1
        assert result.violations[0].rule == "IMP002"

    def test_missing_import_imp001(self, tmp_path: Path) -> None:
        _write_migration(tmp_path, "20260426120008_bad_import.py", MISSING_IMPORT)

        result = ImportChecker(tmp_path).check()

        assert not result.success
        assert result.violations[0].rule == "IMP001"

    def test_empty_directory(self, tmp_path: Path) -> None:
        result = ImportChecker(tmp_path).check()

        assert result.success
        assert result.checked == 0
        assert result.passed == 0

    def test_sql_files_skipped(self, tmp_path: Path) -> None:
        (tmp_path / "20260426120000_init.up.sql").write_text("SELECT 1;")
        (tmp_path / "20260426120000_init.down.sql").write_text("SELECT 1;")

        result = ImportChecker(tmp_path).check()

        assert result.success
        assert result.checked == 0
        assert result.skipped_sql == 1

    def test_dunder_files_ignored(self, tmp_path: Path) -> None:
        (tmp_path / "__init__.py").write_text("")
        _write_migration(tmp_path, "20260426120000_valid.py", VALID_MIGRATION)

        result = ImportChecker(tmp_path).check()

        assert result.checked == 1
        assert result.passed == 1

    def test_multiple_files_mixed(self, tmp_path: Path) -> None:
        _write_migration(tmp_path, "20260426120000_good.py", VALID_MIGRATION)
        _write_migration(tmp_path, "20260426120001_bad.py", SYNTAX_ERROR_MIGRATION)

        result = ImportChecker(tmp_path).check()

        assert result.checked == 2
        assert result.passed == 1
        assert result.failed == 1


# ---------------------------------------------------------------------------
# Level 2: class attribute validation
# ---------------------------------------------------------------------------


class TestLevel2Attributes:
    """IMP003-IMP007: version, name, up(), down() validation."""

    def test_missing_version_imp003(self, tmp_path: Path) -> None:
        _write_migration(tmp_path, "20260426120003_no_ver.py", MISSING_VERSION)

        result = ImportChecker(tmp_path).check()

        assert not result.success
        rules = {v.rule for v in result.violations}
        assert "IMP003" in rules

    def test_missing_name_imp004(self, tmp_path: Path) -> None:
        _write_migration(tmp_path, "20260426120004_no_name.py", MISSING_NAME)

        result = ImportChecker(tmp_path).check()

        assert not result.success
        rules = {v.rule for v in result.violations}
        assert "IMP004" in rules

    def test_empty_version_imp005(self, tmp_path: Path) -> None:
        _write_migration(tmp_path, "20260426120005_empty_ver.py", EMPTY_VERSION)

        result = ImportChecker(tmp_path).check()

        assert not result.success
        rules = {v.rule for v in result.violations}
        assert "IMP005" in rules

    def test_version_not_string_imp005(self, tmp_path: Path) -> None:
        _write_migration(tmp_path, "20260426120005_bad_ver.py", VERSION_NOT_STRING)

        result = ImportChecker(tmp_path).check()

        assert not result.success
        rules = {v.rule for v in result.violations}
        assert "IMP005" in rules

    def test_abstract_up_imp006(self, tmp_path: Path) -> None:
        _write_migration(tmp_path, "20260426120006_no_up.py", ABSTRACT_UP)

        result = ImportChecker(tmp_path).check()

        assert not result.success
        rules = {v.rule for v in result.violations}
        assert "IMP006" in rules

    def test_abstract_down_imp007(self, tmp_path: Path) -> None:
        _write_migration(tmp_path, "20260426120007_no_down.py", ABSTRACT_DOWN)

        result = ImportChecker(tmp_path).check()

        assert not result.success
        rules = {v.rule for v in result.violations}
        assert "IMP007" in rules

    def test_level2_skipped_when_import_fails(self, tmp_path: Path) -> None:
        """If L1 fails, L2 checks should not produce additional violations."""
        _write_migration(tmp_path, "20260426120001_bad.py", SYNTAX_ERROR_MIGRATION)

        result = ImportChecker(tmp_path).check()

        # Only IMP001, no IMP003-IMP007
        assert all(v.rule == "IMP001" for v in result.violations)


# ---------------------------------------------------------------------------
# CLI integration: --check-imports flag
# ---------------------------------------------------------------------------

runner = CliRunner()


def _strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


class TestCheckImportsCLI:
    """CLI integration tests for migrate validate --check-imports."""

    def test_check_imports_passes_with_valid_migration(self, tmp_path: Path) -> None:
        _write_migration(tmp_path, "20260426120000_create_users.py", VALID_MIGRATION)

        result = runner.invoke(
            app, ["migrate", "validate", "--check-imports", "--migrations-dir", str(tmp_path)]
        )

        assert result.exit_code == 0
        assert "passed import check" in _strip_ansi(result.output)

    def test_check_imports_fails_with_syntax_error(self, tmp_path: Path) -> None:
        _write_migration(tmp_path, "20260426120001_bad.py", SYNTAX_ERROR_MIGRATION)

        result = runner.invoke(
            app, ["migrate", "validate", "--check-imports", "--migrations-dir", str(tmp_path)]
        )

        assert result.exit_code == 1
        assert "IMP001" in _strip_ansi(result.output)

    def test_check_imports_json_output(self, tmp_path: Path) -> None:
        _write_migration(tmp_path, "20260426120000_good.py", VALID_MIGRATION)
        _write_migration(tmp_path, "20260426120001_bad.py", SYNTAX_ERROR_MIGRATION)

        result = runner.invoke(
            app,
            [
                "migrate",
                "validate",
                "--check-imports",
                "--migrations-dir",
                str(tmp_path),
                "--format",
                "json",
            ],
        )

        assert result.exit_code == 1
        data = json.loads(result.output)
        assert data["check"] == "imports"
        assert data["checked"] == 2
        assert data["passed"] == 1
        assert data["failed"] == 1
        assert not data["success"]
        assert len(data["violations"]) == 1
        assert data["violations"][0]["rule"] == "IMP001"

    def test_check_imports_empty_dir_passes(self, tmp_path: Path) -> None:
        result = runner.invoke(
            app, ["migrate", "validate", "--check-imports", "--migrations-dir", str(tmp_path)]
        )

        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Level 3: AST-based static analysis of self.method() calls
# ---------------------------------------------------------------------------

CALLS_NONEXISTENT_METHOD = """\
from confiture.models.migration import Migration

class BadCalls(Migration):
    version = "20260426130000"
    name = "bad_calls"

    def up(self):
        self.run_query("SELECT 1;")

    def down(self):
        pass
"""

CALLS_VALID_METHODS = """\
from confiture.models.migration import Migration

class GoodCalls(Migration):
    version = "20260426130001"
    name = "good_calls"

    def up(self):
        self.execute("CREATE TABLE t (id INT);")
        self.execute_file("db/schema/func.sql")

    def down(self):
        self.execute("DROP TABLE t;")
"""

CALLS_OWN_HELPER = """\
from confiture.models.migration import Migration

class UsesHelper(Migration):
    version = "20260426130002"
    name = "uses_helper"

    def _create_tables(self):
        self.execute("CREATE TABLE a (id INT);")

    def up(self):
        self._create_tables()

    def down(self):
        self.execute("DROP TABLE a;")
"""

ACCESSES_NONEXISTENT_ATTR = """\
from confiture.models.migration import Migration

class BadAttr(Migration):
    version = "20260426130003"
    name = "bad_attr"

    def up(self):
        log = self.logger
        self.execute("SELECT 1;")

    def down(self):
        pass
"""

ACCESSES_CONNECTION = """\
from confiture.models.migration import Migration

class UsesConnection(Migration):
    version = "20260426130004"
    name = "uses_connection"

    def up(self):
        with self.connection.cursor() as cur:
            cur.execute("SELECT 1;")

    def down(self):
        pass
"""

NONEXISTENT_IN_DOWN = """\
from confiture.models.migration import Migration

class BadDown(Migration):
    version = "20260426130005"
    name = "bad_down"

    def up(self):
        self.execute("CREATE TABLE t (id INT);")

    def down(self):
        self.rollback_table("t")
"""

MULTIPLE_BAD_CALLS = """\
from confiture.models.migration import Migration

class MultipleBad(Migration):
    version = "20260426130006"
    name = "multiple_bad"

    def up(self):
        self.run_query("SELECT 1;")
        self.execute("CREATE TABLE t (id INT);")
        self.do_stuff()

    def down(self):
        pass
"""


class TestLevel3StaticAnalysis:
    """IMP008/IMP009: self.method() and self.attr checks via AST."""

    def test_nonexistent_method_imp008(self, tmp_path: Path) -> None:
        _write_migration(tmp_path, "20260426130000_bad.py", CALLS_NONEXISTENT_METHOD)

        result = ImportChecker(tmp_path).check()

        assert not result.success
        rules = {v.rule for v in result.violations}
        assert "IMP008" in rules
        assert any("run_query" in v.message for v in result.violations)

    def test_valid_methods_pass(self, tmp_path: Path) -> None:
        _write_migration(tmp_path, "20260426130001_good.py", CALLS_VALID_METHODS)

        result = ImportChecker(tmp_path).check()

        # No IMP008/IMP009 violations (execute and execute_file are valid methods)
        # IMP010 may fire because the referenced file doesn't exist — that's expected
        l3_method_violations = [v for v in result.violations if v.rule in ("IMP008", "IMP009")]
        assert l3_method_violations == []

    def test_own_helper_method_not_flagged(self, tmp_path: Path) -> None:
        _write_migration(tmp_path, "20260426130002_helper.py", CALLS_OWN_HELPER)

        result = ImportChecker(tmp_path).check()

        l3_violations = [v for v in result.violations if v.level == 3]
        assert l3_violations == []

    def test_nonexistent_attr_imp009(self, tmp_path: Path) -> None:
        _write_migration(tmp_path, "20260426130003_attr.py", ACCESSES_NONEXISTENT_ATTR)

        result = ImportChecker(tmp_path).check()

        assert not result.success
        rules = {v.rule for v in result.violations}
        assert "IMP009" in rules
        assert any("logger" in v.message for v in result.violations)

    def test_connection_access_allowed(self, tmp_path: Path) -> None:
        _write_migration(tmp_path, "20260426130004_conn.py", ACCESSES_CONNECTION)

        result = ImportChecker(tmp_path).check()

        l3_violations = [v for v in result.violations if v.level == 3]
        assert l3_violations == []

    def test_nonexistent_in_down_detected(self, tmp_path: Path) -> None:
        _write_migration(tmp_path, "20260426130005_down.py", NONEXISTENT_IN_DOWN)

        result = ImportChecker(tmp_path).check()

        assert not result.success
        imp008 = [v for v in result.violations if v.rule == "IMP008"]
        assert len(imp008) >= 1
        assert any("rollback_table" in v.message for v in imp008)

    def test_multiple_bad_calls_all_reported(self, tmp_path: Path) -> None:
        _write_migration(tmp_path, "20260426130006_multi.py", MULTIPLE_BAD_CALLS)

        result = ImportChecker(tmp_path).check()

        imp008 = [v for v in result.violations if v.rule == "IMP008"]
        bad_names = {v.message.split("self.")[1].split("(")[0].split(" ")[0] for v in imp008}
        assert "run_query" in bad_names
        assert "do_stuff" in bad_names

    def test_level3_skipped_when_l1_fails(self, tmp_path: Path) -> None:
        _write_migration(tmp_path, "20260426130007_bad.py", SYNTAX_ERROR_MIGRATION)

        result = ImportChecker(tmp_path).check()

        assert all(v.level < 3 for v in result.violations)

    def test_violations_include_line_numbers(self, tmp_path: Path) -> None:
        _write_migration(tmp_path, "20260426130000_bad.py", CALLS_NONEXISTENT_METHOD)

        result = ImportChecker(tmp_path).check()

        imp008 = [v for v in result.violations if v.rule == "IMP008"]
        assert len(imp008) >= 1
        # Message should mention the line number
        assert any("line" in v.message.lower() for v in imp008)


# ---------------------------------------------------------------------------
# Level 3 extension: execute_file reference validation (IMP010/IMP011)
# ---------------------------------------------------------------------------

EXECUTE_FILE_MISSING_REF = """\
from confiture.models.migration import Migration

class MissingRef(Migration):
    version = "20260426140000"
    name = "missing_ref"

    def up(self):
        self.execute_file("db/schema/functions/nonexistent.sql")

    def down(self):
        pass
"""

EXECUTE_FILE_VALID_REF = """\
from confiture.models.migration import Migration

class ValidRef(Migration):
    version = "20260426140001"
    name = "valid_ref"

    def up(self):
        self.execute_file("db/schema/functions/my_func.sql")

    def down(self):
        pass
"""

EXECUTE_FILE_DYNAMIC_PATH = """\
from confiture.models.migration import Migration

class DynamicPath(Migration):
    version = "20260426140002"
    name = "dynamic_path"

    def up(self):
        path = "db/schema/func.sql"
        self.execute_file(path)

    def down(self):
        pass
"""

EXECUTE_FILE_FSTRING = """\
from confiture.models.migration import Migration

class FStringPath(Migration):
    version = "20260426140003"
    name = "fstring_path"

    def up(self):
        name = "my_func"
        self.execute_file(f"db/schema/{name}.sql")

    def down(self):
        pass
"""


class TestExecuteFileRefValidation:
    """IMP010/IMP011: validate execute_file() file references."""

    def test_missing_file_imp010(self, tmp_path: Path, monkeypatch: "pytest.MonkeyPatch") -> None:
        monkeypatch.chdir(tmp_path)
        _write_migration(tmp_path, "20260426140000_ref.py", EXECUTE_FILE_MISSING_REF)

        result = ImportChecker(tmp_path).check()

        assert not result.success
        imp010 = [v for v in result.violations if v.rule == "IMP010"]
        assert len(imp010) == 1
        assert "nonexistent.sql" in imp010[0].message

    def test_existing_file_passes(self, tmp_path: Path, monkeypatch: "pytest.MonkeyPatch") -> None:
        monkeypatch.chdir(tmp_path)
        # Create the referenced file
        func_dir = tmp_path / "db" / "schema" / "functions"
        func_dir.mkdir(parents=True)
        (func_dir / "my_func.sql").write_text("CREATE FUNCTION my_func();")

        _write_migration(tmp_path, "20260426140001_ref.py", EXECUTE_FILE_VALID_REF)

        result = ImportChecker(tmp_path).check()

        imp010 = [v for v in result.violations if v.rule == "IMP010"]
        assert imp010 == []

    def test_dynamic_path_imp011(self, tmp_path: Path) -> None:
        _write_migration(tmp_path, "20260426140002_dyn.py", EXECUTE_FILE_DYNAMIC_PATH)

        result = ImportChecker(tmp_path).check()

        imp011 = [v for v in result.violations if v.rule == "IMP011"]
        assert len(imp011) == 1

    def test_fstring_path_imp011(self, tmp_path: Path) -> None:
        _write_migration(tmp_path, "20260426140003_fstr.py", EXECUTE_FILE_FSTRING)

        result = ImportChecker(tmp_path).check()

        imp011 = [v for v in result.violations if v.rule == "IMP011"]
        assert len(imp011) == 1

    def test_imp010_is_error_imp011_is_warning(
        self, tmp_path: Path, monkeypatch: "pytest.MonkeyPatch"
    ) -> None:
        """IMP010 should cause failure, IMP011 should not."""
        monkeypatch.chdir(tmp_path)
        # Dynamic path only → warning, not failure
        _write_migration(tmp_path, "20260426140002_dyn.py", EXECUTE_FILE_DYNAMIC_PATH)

        result = ImportChecker(tmp_path).check()

        # IMP011 is a warning — doesn't cause failure
        assert result.success
        assert any(v.rule == "IMP011" for v in result.violations)
