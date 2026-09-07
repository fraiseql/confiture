"""The desired-state source: what ``migrate diff --to`` reads (issue #196).

A FraiseQL ``compile --emit-ddl`` artifact is a directory of DDL files, one per
type; a hand-written target is one file; a pipeline hands it over on stdin. The
source yields the DDL text the differ already parses — the differ never learns
what an artifact is.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from confiture.core.desired_state import SqlFileSource, load_desired_state
from confiture.exceptions import SchemaError

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "desired_state" / "emit_ddl"


class TestSqlFileSource:
    def test_a_directory_is_its_sql_files_in_name_order(self) -> None:
        source = load_desired_state(str(FIXTURE))

        assert isinstance(source, SqlFileSource)
        text = source.read()
        assert text.index("tb_post") < text.index("tb_user")  # post.sql before user.sql
        assert text.count("CREATE TABLE") == 2

    def test_a_directory_ignores_non_sql_files(self, tmp_path: Path) -> None:
        (tmp_path / "b.sql").write_text("CREATE TABLE b (id int);\n")
        (tmp_path / "a.sql").write_text("CREATE TABLE a (id int);\n")
        (tmp_path / "notes.md").write_text("CREATE TABLE nope (id int);\n")

        text = load_desired_state(str(tmp_path)).read()

        assert "nope" not in text
        assert text.index("CREATE TABLE a") < text.index("CREATE TABLE b")

    def test_a_file_is_read_as_is(self, tmp_path: Path) -> None:
        f = tmp_path / "target.sql"
        f.write_text("CREATE TABLE t (id int);\n")

        assert load_desired_state(str(f)).read() == "CREATE TABLE t (id int);\n"

    def test_dash_reads_stdin(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO("CREATE TABLE s (id int);\n"))

        source = load_desired_state("-")

        assert source.read() == "CREATE TABLE s (id int);\n"
        assert source.describe() == {"kind": "sql", "path": "-"}

    def test_describe_names_the_kind_and_the_path(self) -> None:
        assert load_desired_state(str(FIXTURE)).describe() == {"kind": "sql", "path": str(FIXTURE)}

    def test_a_missing_path_is_schema_201(self, tmp_path: Path) -> None:
        with pytest.raises(SchemaError) as excinfo:
            load_desired_state(str(tmp_path / "absent.sql")).read()
        assert excinfo.value.error_code == "SCHEMA_201"

    def test_an_empty_directory_is_schema_201(self, tmp_path: Path) -> None:
        with pytest.raises(SchemaError) as excinfo:
            load_desired_state(str(tmp_path)).read()
        assert excinfo.value.error_code == "SCHEMA_201"
