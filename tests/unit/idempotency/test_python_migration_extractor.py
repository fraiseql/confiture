"""Tests for the Python-migration SQL extractor."""

from __future__ import annotations

from pathlib import Path

from confiture.core.idempotency.python_migration_extractor import (
    ExtractionKind,
    ExtractionResult,
    WarningKind,
    extract_sql_from_python_migration,
)


def _write(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


# Cycle 1: skeleton + happy-path constant string
class TestSingleConstantExecute:
    def test_extracts_single_constant_execute(self, tmp_path: Path) -> None:
        migration = _write(
            tmp_path,
            "20260101000000_demo.py",
            "from confiture.models.migration import Migration\n\n"
            "class Demo(Migration):\n"
            '    version = "20260101000000"\n'
            '    name = "demo"\n'
            "    def up(self) -> None:\n"
            '        self.execute("CREATE TABLE foo (id int);")\n'
            "    def down(self) -> None:\n"
            "        pass\n",
        )

        result = extract_sql_from_python_migration(migration, project_root=tmp_path)

        assert isinstance(result, ExtractionResult)
        assert result.warnings == []
        assert len(result.snippets) == 1
        snippet = result.snippets[0]
        assert snippet.sql == "CREATE TABLE foo (id int);"
        assert snippet.kind == ExtractionKind.INLINE
        assert snippet.source_file == migration
        assert snippet.source_line == 7
        assert snippet.sql_file is None


# Cycle 2: multiple statements in one file, deterministic ordering
class TestMultipleStatementOrdering:
    def test_extracts_multiple_executes_sorted_by_line(self, tmp_path: Path) -> None:
        migration = _write(
            tmp_path,
            "20260101000001_multi.py",
            "from confiture.models.migration import Migration\n"
            "\n"
            "class Multi(Migration):\n"
            '    version = "20260101000001"\n'
            '    name = "multi"\n'
            "    def up(self) -> None:\n"
            '        self.execute("CREATE TABLE a (id int);")\n'
            '        self.execute("CREATE TABLE b (id int);")\n'
            '        self.execute("CREATE TABLE c (id int);")\n'
            "    def down(self) -> None:\n"
            '        self.execute("DROP TABLE a;")\n',
        )

        result = extract_sql_from_python_migration(migration, project_root=tmp_path)

        assert result.warnings == []
        assert [s.sql for s in result.snippets] == [
            "CREATE TABLE a (id int);",
            "CREATE TABLE b (id int);",
            "CREATE TABLE c (id int);",
            "DROP TABLE a;",
        ]
        assert [s.source_line for s in result.snippets] == [7, 8, 9, 11]


# Cycle 3: f-strings with only static parts
class TestStaticFString:
    def test_extracts_static_fstring(self, tmp_path: Path) -> None:
        migration = _write(
            tmp_path,
            "20260101000002_fstring.py",
            "from confiture.models.migration import Migration\n"
            "\n"
            "class FStr(Migration):\n"
            '    version = "20260101000002"\n'
            '    name = "fstring"\n'
            "    def up(self) -> None:\n"
            '        self.execute(f"CREATE TABLE foo (id int);")\n'
            "    def down(self) -> None:\n"
            "        pass\n",
        )

        result = extract_sql_from_python_migration(migration, project_root=tmp_path)

        assert result.warnings == []
        assert len(result.snippets) == 1
        assert result.snippets[0].sql == "CREATE TABLE foo (id int);"
        assert result.snippets[0].kind == ExtractionKind.INLINE_FSTRING

    def test_extracts_concatenated_static_fstring_parts(self, tmp_path: Path) -> None:
        migration = _write(
            tmp_path,
            "20260101000003_fstring_concat.py",
            "from confiture.models.migration import Migration\n"
            "\n"
            "class FStrC(Migration):\n"
            '    version = "20260101000003"\n'
            '    name = "fstring_concat"\n'
            "    def up(self) -> None:\n"
            '        self.execute(f"CREATE TABLE foo (" f"id int);")\n'
            "    def down(self) -> None:\n"
            "        pass\n",
        )

        result = extract_sql_from_python_migration(migration, project_root=tmp_path)

        # Implicit string concatenation collapses at parse time into a single
        # JoinedStr / Constant — extractor should accept it.
        assert result.warnings == []
        assert len(result.snippets) == 1
        assert "CREATE TABLE foo (id int);" in result.snippets[0].sql


# Cycle 4: dynamic f-string emits warning
class TestDynamicFStringWarning:
    def test_dynamic_fstring_emits_unresolved_warning(self, tmp_path: Path) -> None:
        migration = _write(
            tmp_path,
            "20260101000004_dyn_fstring.py",
            "from confiture.models.migration import Migration\n"
            "\n"
            "class Dyn(Migration):\n"
            '    version = "20260101000004"\n'
            '    name = "dyn_fstring"\n'
            "    def up(self) -> None:\n"
            '        table = "foo"\n'
            '        self.execute(f"CREATE TABLE {table} (id int);")\n'
            "    def down(self) -> None:\n"
            "        pass\n",
        )

        result = extract_sql_from_python_migration(migration, project_root=tmp_path)

        assert result.snippets == []
        assert len(result.warnings) == 1
        warn = result.warnings[0]
        assert warn.kind == WarningKind.UNRESOLVED_FSTRING
        assert warn.source_file == migration
        assert warn.source_line == 8


# Cycle 5: dynamic variable execute emits warning
class TestDynamicExecuteWarning:
    def test_variable_execute_emits_dynamic_warning(self, tmp_path: Path) -> None:
        migration = _write(
            tmp_path,
            "20260101000005_dyn_var.py",
            "from confiture.models.migration import Migration\n"
            "\n"
            "class DynVar(Migration):\n"
            '    version = "20260101000005"\n'
            '    name = "dyn_var"\n'
            "    def up(self) -> None:\n"
            '        sql = open("x.sql").read()\n'
            "        self.execute(sql)\n"
            "    def down(self) -> None:\n"
            "        pass\n",
        )

        result = extract_sql_from_python_migration(migration, project_root=tmp_path)

        assert result.snippets == []
        assert len(result.warnings) == 1
        warn = result.warnings[0]
        assert warn.kind == WarningKind.DYNAMIC_EXECUTE
        assert warn.source_line == 8


# Cycle 6: constant string concatenation via `+`
class TestConstantConcatenation:
    def test_extracts_constant_plus_constant(self, tmp_path: Path) -> None:
        migration = _write(
            tmp_path,
            "20260101000006_concat.py",
            "from confiture.models.migration import Migration\n"
            "\n"
            "class C(Migration):\n"
            '    version = "20260101000006"\n'
            '    name = "concat"\n'
            "    def up(self) -> None:\n"
            '        self.execute("CREATE " + "TABLE foo (id int);")\n'
            "    def down(self) -> None:\n"
            "        pass\n",
        )

        result = extract_sql_from_python_migration(migration, project_root=tmp_path)

        assert result.warnings == []
        assert len(result.snippets) == 1
        assert result.snippets[0].sql == "CREATE TABLE foo (id int);"

    def test_dynamic_concatenation_emits_warning(self, tmp_path: Path) -> None:
        migration = _write(
            tmp_path,
            "20260101000007_dyn_concat.py",
            "from confiture.models.migration import Migration\n"
            "\n"
            "class DC(Migration):\n"
            '    version = "20260101000007"\n'
            '    name = "dyn_concat"\n'
            "    def up(self) -> None:\n"
            '        suffix = " (id int);"\n'
            '        self.execute("CREATE TABLE foo" + suffix)\n'
            "    def down(self) -> None:\n"
            "        pass\n",
        )

        result = extract_sql_from_python_migration(migration, project_root=tmp_path)

        assert result.snippets == []
        assert len(result.warnings) == 1
        assert result.warnings[0].kind == WarningKind.DYNAMIC_EXECUTE


# Cycle 7: self.execute_file(constant_path) — bounded to project root
class TestExecuteFileConstantPath:
    def test_execute_file_reads_referenced_sql(self, tmp_path: Path) -> None:
        (tmp_path / "db" / "migrations").mkdir(parents=True)
        (tmp_path / "db" / "schema" / "functions").mkdir(parents=True)
        sql_path = tmp_path / "db" / "schema" / "functions" / "foo.sql"
        sql_path.write_text("CREATE TABLE foo (id int);\n", encoding="utf-8")

        migration = _write(
            tmp_path / "db" / "migrations",
            "20260101000008_uses_file.py",
            "from confiture.models.migration import Migration\n"
            "\n"
            "class UsesFile(Migration):\n"
            '    version = "20260101000008"\n'
            '    name = "uses_file"\n'
            "    def up(self) -> None:\n"
            '        self.execute_file("db/schema/functions/foo.sql")\n'
            "    def down(self) -> None:\n"
            "        pass\n",
        )

        import os

        prev_cwd = Path.cwd()
        try:
            os.chdir(tmp_path)
            result = extract_sql_from_python_migration(migration, project_root=tmp_path)
        finally:
            os.chdir(prev_cwd)

        assert result.warnings == []
        assert len(result.snippets) == 1
        snippet = result.snippets[0]
        assert snippet.kind == ExtractionKind.FILE
        assert snippet.sql == "CREATE TABLE foo (id int);\n"
        assert snippet.sql_file is not None
        assert snippet.sql_file.resolve() == sql_path.resolve()
        assert snippet.source_line == 7


# Cycle 7b: execute_file("../../../escapes") emits EXECUTE_FILE_ESCAPED
class TestExecuteFileEscape:
    def test_path_outside_project_root_is_rejected(self, tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        # Two sibling directories. The project root contains a `db/` anchor;
        # the secret file lives outside the project root. Even with an
        # absolute traversal, the extractor must refuse to read it.
        project = tmp_path / "project"
        outside = tmp_path / "outside"
        (project / "db" / "migrations").mkdir(parents=True)
        outside.mkdir(parents=True)
        secret = outside / "secret.sql"
        secret.write_text("SECRET CONTENTS", encoding="utf-8")

        migration = _write(
            project / "db" / "migrations",
            "20260101000009_escape.py",
            "from confiture.models.migration import Migration\n"
            "\n"
            "class E(Migration):\n"
            '    version = "20260101000009"\n'
            '    name = "escape"\n'
            "    def up(self) -> None:\n"
            '        self.execute_file("../../../outside/secret.sql")\n'
            "    def down(self) -> None:\n"
            "        pass\n",
        )

        # Confirm the file would resolve if we allowed it
        assert secret.is_file()

        # Sentinel: blow up the test if anyone tries to read the secret.
        original_read_text = Path.read_text

        def _guarded_read_text(self_path: Path, *args, **kwargs):  # type: ignore[no-untyped-def]
            if self_path.resolve() == secret.resolve():
                raise AssertionError(f"Extractor read forbidden file {self_path!r}")
            return original_read_text(self_path, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", _guarded_read_text)
        monkeypatch.chdir(project)

        result = extract_sql_from_python_migration(migration, project_root=project)

        assert result.snippets == []
        assert len(result.warnings) == 1
        warn = result.warnings[0]
        assert warn.kind == WarningKind.EXECUTE_FILE_ESCAPED
        assert warn.source_line == 7


# Cycle 8: execute_file(missing_file) emits warning
class TestExecuteFileMissing:
    def test_missing_constant_path_emits_warning(self, tmp_path: Path) -> None:
        (tmp_path / "db" / "migrations").mkdir(parents=True)

        migration = _write(
            tmp_path / "db" / "migrations",
            "20260101000010_missing.py",
            "from confiture.models.migration import Migration\n"
            "\n"
            "class M(Migration):\n"
            '    version = "20260101000010"\n'
            '    name = "missing"\n'
            "    def up(self) -> None:\n"
            '        self.execute_file("db/schema/does_not_exist.sql")\n'
            "    def down(self) -> None:\n"
            "        pass\n",
        )

        import os

        prev = Path.cwd()
        try:
            os.chdir(tmp_path)
            result = extract_sql_from_python_migration(migration, project_root=tmp_path)
        finally:
            os.chdir(prev)

        assert result.snippets == []
        assert len(result.warnings) == 1
        assert result.warnings[0].kind == WarningKind.EXECUTE_FILE_MISSING


# Cycle 9: execute_file(var) emits DYNAMIC_EXECUTE_FILE
class TestDynamicExecuteFile:
    def test_dynamic_path_emits_warning(self, tmp_path: Path) -> None:
        migration = _write(
            tmp_path,
            "20260101000011_dyn_file.py",
            "from confiture.models.migration import Migration\n"
            "\n"
            "class DF(Migration):\n"
            '    version = "20260101000011"\n'
            '    name = "dyn_file"\n'
            "    def up(self) -> None:\n"
            "        path = self._compute_path()\n"
            "        self.execute_file(path)\n"
            "    def down(self) -> None:\n"
            "        pass\n",
        )

        result = extract_sql_from_python_migration(migration, project_root=tmp_path)

        assert result.snippets == []
        # Two dynamic warnings: the self._compute_path() call is not an execute,
        # but self.execute_file(path) is dynamic. We expect 1 warning for the
        # execute_file call only.
        kinds = [w.kind for w in result.warnings]
        assert WarningKind.DYNAMIC_EXECUTE_FILE in kinds


# Cycle 10: syntactically invalid .py
class TestSyntaxError:
    def test_invalid_syntax_returns_warning_not_exception(self, tmp_path: Path) -> None:
        migration = _write(
            tmp_path,
            "20260101000012_broken.py",
            "def up(self:\n    pass\n",  # broken signature
        )

        result = extract_sql_from_python_migration(migration, project_root=tmp_path)

        assert result.snippets == []
        assert len(result.warnings) == 1
        assert result.warnings[0].kind == WarningKind.SYNTAX_ERROR
        assert result.warnings[0].source_file == migration


# Cycle 11: ignore non-self attribute calls
class TestNonSelfReceiverIgnored:
    def test_logger_and_other_object_executes_are_ignored(self, tmp_path: Path) -> None:
        migration = _write(
            tmp_path,
            "20260101000013_other_recv.py",
            "from confiture.models.migration import Migration\n"
            "import logging\n"
            "\n"
            "class O(Migration):\n"
            '    version = "20260101000013"\n'
            '    name = "other_recv"\n'
            "    def up(self) -> None:\n"
            '        logging.info("CREATE TABLE foo (id int);")\n'
            "        other = object()\n"
            '        other.execute("CREATE TABLE bar (id int);")\n'
            "    def down(self) -> None:\n"
            "        pass\n",
        )

        result = extract_sql_from_python_migration(migration, project_root=tmp_path)

        assert result.snippets == []
        assert result.warnings == []


# Cycle 12: positional-only first arg, plus sql= keyword form
class TestKeywordSqlArgument:
    def test_positional_arg_extracted_kwargs_ignored(self, tmp_path: Path) -> None:
        migration = _write(
            tmp_path,
            "20260101000014_pos_kw.py",
            "from confiture.models.migration import Migration\n"
            "\n"
            "class PK(Migration):\n"
            '    version = "20260101000014"\n'
            '    name = "pos_kw"\n'
            "    def up(self) -> None:\n"
            '        self.execute("CREATE TABLE pos (id int);", ("x",))\n'
            "    def down(self) -> None:\n"
            "        pass\n",
        )

        result = extract_sql_from_python_migration(migration, project_root=tmp_path)

        assert result.warnings == []
        assert [s.sql for s in result.snippets] == ["CREATE TABLE pos (id int);"]

    def test_keyword_sql_argument_is_extracted(self, tmp_path: Path) -> None:
        migration = _write(
            tmp_path,
            "20260101000015_kw_only.py",
            "from confiture.models.migration import Migration\n"
            "\n"
            "class KW(Migration):\n"
            '    version = "20260101000015"\n'
            '    name = "kw_only"\n'
            "    def up(self) -> None:\n"
            '        self.execute(sql="CREATE TABLE kw (id int);")\n'
            "    def down(self) -> None:\n"
            "        pass\n",
        )

        result = extract_sql_from_python_migration(migration, project_root=tmp_path)

        assert result.warnings == []
        assert [s.sql for s in result.snippets] == ["CREATE TABLE kw (id int);"]


# Edge-case coverage
class TestEdgeCases:
    def test_non_string_constant_argument_emits_dynamic_warning(self, tmp_path: Path) -> None:
        migration = _write(
            tmp_path,
            "20260101000016_int_arg.py",
            "from confiture.models.migration import Migration\n"
            "\n"
            "class I(Migration):\n"
            '    version = "20260101000016"\n'
            '    name = "int_arg"\n'
            "    def up(self) -> None:\n"
            "        self.execute(123)\n"
            "    def down(self) -> None:\n"
            "        pass\n",
        )

        result = extract_sql_from_python_migration(migration, project_root=tmp_path)

        assert result.snippets == []
        assert [w.kind for w in result.warnings] == [WarningKind.DYNAMIC_EXECUTE]

    def test_bare_execute_call_is_skipped(self, tmp_path: Path) -> None:
        migration = _write(
            tmp_path,
            "20260101000017_bare.py",
            "from confiture.models.migration import Migration\n"
            "\n"
            "class B(Migration):\n"
            '    version = "20260101000017"\n'
            '    name = "bare"\n'
            "    def up(self) -> None:\n"
            "        self.execute()\n"
            "        self.execute(notsql='hi')\n"
            "    def down(self) -> None:\n"
            "        pass\n",
        )

        result = extract_sql_from_python_migration(migration, project_root=tmp_path)

        assert result.snippets == []
        assert result.warnings == []

    def test_default_project_root_uses_db_anchor(self, tmp_path: Path) -> None:
        # No project_root passed: extractor walks up until it finds an anchor.
        (tmp_path / "project" / "db" / "migrations").mkdir(parents=True)
        sql_path = tmp_path / "project" / "db" / "schema" / "foo.sql"
        sql_path.parent.mkdir(parents=True)
        sql_path.write_text("CREATE TABLE x (id int);", encoding="utf-8")

        migration = _write(
            tmp_path / "project" / "db" / "migrations",
            "20260101000018_default_root.py",
            "from confiture.models.migration import Migration\n"
            "\n"
            "class D(Migration):\n"
            '    version = "20260101000018"\n'
            '    name = "default_root"\n'
            "    def up(self) -> None:\n"
            '        self.execute_file("db/schema/foo.sql")\n'
            "    def down(self) -> None:\n"
            "        pass\n",
        )

        import os

        prev = Path.cwd()
        try:
            os.chdir(tmp_path / "project")
            result = extract_sql_from_python_migration(migration)  # project_root=None
        finally:
            os.chdir(prev)

        assert result.warnings == []
        assert len(result.snippets) == 1
        assert result.snippets[0].sql == "CREATE TABLE x (id int);"
