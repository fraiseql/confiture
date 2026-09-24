"""``build_004``: a statement needs, when it is created, an object the build creates later (#383).

``build_003`` asks whether the build creates what a body names at all; this asks
whether it creates it *first*. A view, a ``LANGUAGE sql`` body, a trigger's
function, a default, a check, an index expression and a foreign key are
resolved when their statement runs, so the object has to exist by then; a
PL/pgSQL body is resolved when it first runs, and may name anything the build
creates. Each row of ``forward_reference_rows`` is a tree and PostgreSQL's
verdict on it (``tests/integration/test_forward_reference_oracle.py`` applies
every bundle); the rule reports a row exactly when PostgreSQL refuses it.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from tests.unit.linting.forward_reference_rows import ROWS, Row
from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()


def _project(root: Path, files: tuple[tuple[str, str], ...], *, two_pass: bool = False) -> None:
    schema = root / "db" / "schema"
    schema.mkdir(parents=True, exist_ok=True)
    (root / "db" / "environments").mkdir(parents=True, exist_ok=True)
    (root / "db" / "environments" / "local.yaml").write_text(
        "database_url: postgresql://127.0.0.1:1/lintdemo\n"
        "include_dirs:\n  - path: db/schema\n"
        f"build:\n  two_pass: {'true' if two_pass else 'false'}\n"
    )
    for name, sql in files:
        (schema / name).parent.mkdir(parents=True, exist_ok=True)
        (schema / name).write_text(sql)


@pytest.fixture
def in_tmp(tmp_path: Path) -> Iterator[Path]:
    old = Path.cwd()
    os.chdir(tmp_path)
    try:
        yield tmp_path
    finally:
        os.chdir(old)


def _findings(*args: str) -> list[dict]:
    result = runner.invoke(
        app, ["lint", "--select", "build_004", "--format", "json", "--fail-on", "never", *args]
    )
    assert result.exit_code == 0, result.output
    items = json.loads(result.stdout)["violations"]["items"]
    return [i for i in items if i["rule_id"] == "build_004"]


@pytest.mark.parametrize("row", ROWS, ids=[row.name for row in ROWS])
def test_the_rule_reports_exactly_what_postgresql_refuses(in_tmp: Path, row: Row) -> None:
    _project(in_tmp, row.files, two_pass=row.two_pass)
    found = _findings()
    if not row.refused:
        assert found == []
        return
    (finding,) = found
    assert f"'{row.needs}'" in finding["message"]
    assert finding["severity"] == "error"


ISSUE_SQL = """CREATE OR REPLACE FUNCTION public.first_continent() RETURNS text
LANGUAGE sql STABLE AS $$
  SELECT name FROM catalog.tb_continent ORDER BY id LIMIT 1
$$;
"""
ISSUE_PLPGSQL = """CREATE OR REPLACE FUNCTION public.first_continent() RETURNS text
LANGUAGE plpgsql STABLE AS $$
BEGIN
  RETURN (SELECT name FROM catalog.tb_continent ORDER BY id LIMIT 1);
END;
$$;
"""
CONTINENT = "CREATE SCHEMA catalog;\n\n\nCREATE TABLE catalog.tb_continent (id int, name text);\n"


def test_the_issues_sql_function_names_both_files(in_tmp: Path) -> None:
    _project(
        in_tmp,
        (
            ("0_schema/00_common/0072_first_continent.sql", ISSUE_SQL),
            ("0_schema/01_write_side/010211_tb_continent.sql", CONTINENT),
        ),
    )
    (finding,) = _findings()
    assert finding["file"].endswith("0_schema/00_common/0072_first_continent.sql")
    assert finding["line"] == 3  # the statement in the body that names the table
    message = finding["message"]
    assert "'catalog.tb_continent'" in message
    assert "0_schema/01_write_side/010211_tb_continent.sql:4" in message
    assert "LANGUAGE sql" in message


def test_the_issues_plpgsql_function_is_silent(in_tmp: Path) -> None:
    _project(
        in_tmp,
        (
            ("0_schema/00_common/0072_first_continent.sql", ISSUE_PLPGSQL),
            ("0_schema/01_write_side/010211_tb_continent.sql", CONTINENT),
        ),
    )
    assert _findings() == []


def test_an_object_the_build_never_creates_is_build_003s(in_tmp: Path) -> None:
    _project(in_tmp, (("10.sql", "CREATE VIEW v AS SELECT 1 FROM app.tb_nowhere;\n"),))
    assert _findings() == []


def test_the_rule_is_on_by_default_at_error(in_tmp: Path) -> None:
    _project(in_tmp, ROWS[0].files)
    result = runner.invoke(app, ["lint", "--format", "json"])
    items = json.loads(result.stdout)["violations"]["items"]
    assert [i["severity"] for i in items if i["rule_id"] == "build_004"] == ["error"]
    assert result.exit_code != 0


def test_a_name_used_twice_in_one_statement_is_one_finding(in_tmp: Path) -> None:
    view = "CREATE VIEW app.v AS SELECT a.id FROM app.tb_x a JOIN app.tb_x b USING (id);\n"
    _project(
        in_tmp,
        (("00.sql", "CREATE SCHEMA app;\n"), ("10.sql", view), ("20.sql", ROWS[0].files[-1][1])),
    )
    assert len(_findings()) == 1
