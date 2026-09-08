"""``body_001`` as a finding: the routine, the file, the line, PostgreSQL's words (#245).

The three shapes #245 names are all the same failure — a body PostgreSQL stored
without resolving — and all three deploy clean. What makes the finding usable is
not that it exists but that it points somewhere: the routine's identity as the
catalog spells it, the DDL file the routine is written in, and the line inside
that file, converted out of the body's own frame.

The diagnosis itself is PostgreSQL's, quoted rather than paraphrased. confiture
knows the body is wrong because PostgreSQL said so, and has nothing to add to
what it said.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from tests._helpers import plpgsql_check_url
from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()

_TABLES = """CREATE SCHEMA IF NOT EXISTS app;
CREATE TABLE app.tb_widget (pk_widget BIGINT PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE app.tb_target (id uuid PRIMARY KEY);
"""

#: The issue's own reproduction. The `SELECT … INTO` is on line 8 of this file.
SELECT_INTO = """CREATE FUNCTION app.fn_widget_pk(p_name TEXT) RETURNS uuid
LANGUAGE plpgsql AS $$
DECLARE
    v_pk UUID;
BEGIN
    SELECT pk_widget INTO v_pk FROM app.tb_widget WHERE name = p_name;
    RETURN v_pk;
END;
$$;
"""

RETURNS_TABLE = """CREATE FUNCTION app.fn_widgets() RETURNS TABLE(id uuid)
LANGUAGE plpgsql AS $$
BEGIN
    RETURN QUERY SELECT pk_widget FROM app.tb_widget;
END;
$$;
"""

INSERT_SELECT = """CREATE FUNCTION app.fn_copy() RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO app.tb_target (id) SELECT pk_widget FROM app.tb_widget;
END;
$$;
"""

CORRECT = """CREATE FUNCTION app.fn_widget_pk(p_name TEXT) RETURNS bigint
LANGUAGE plpgsql AS $$
DECLARE
    v_pk BIGINT;
BEGIN
    SELECT pk_widget INTO v_pk FROM app.tb_widget WHERE name = p_name;
    RETURN v_pk;
END;
$$;
"""


@pytest.fixture(scope="session")
def check_server() -> str:
    url = plpgsql_check_url()
    if url is None:
        pytest.skip(
            "no server carrying plpgsql_check: set CONFITURE_TEST_DB_URL to one "
            "(the extension is in no stock PostgreSQL)"
        )
    return url


@pytest.fixture
def in_tmp(tmp_path: Path) -> Iterator[Path]:
    old = Path.cwd()
    os.chdir(tmp_path)
    try:
        yield tmp_path
    finally:
        os.chdir(old)


def _project(root: Path, url: str, routine: str) -> None:
    (root / "db" / "schema").mkdir(parents=True, exist_ok=True)
    (root / "db" / "environments").mkdir(parents=True, exist_ok=True)
    (root / "db" / "environments" / "local.yaml").write_text(
        f"database_url: {url}\ninclude_dirs:\n  - path: db/schema\n"
    )
    (root / "db" / "schema" / "010_tables.sql").write_text(_TABLES)
    (root / "db" / "schema" / "020_routine.sql").write_text(routine)


def _findings(server: str, code: str = "body_001") -> list[dict]:
    result = runner.invoke(
        app,
        [
            "lint",
            "--select",
            code,
            "--format",
            "json",
            "--fail-on",
            "never",
            "--server-url",
            server,
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["skipped"] == [], payload["skipped"]
    return [i for i in payload["violations"]["items"] if i["rule_id"] == code]


class TestTheThreeShapes:
    """Each is a body that deploys clean and raises on its first call."""

    def test_a_select_into_a_variable_of_another_type(self, in_tmp: Path, check_server) -> None:
        _project(in_tmp, check_server, SELECT_INTO)

        assert len(_findings(check_server)) == 1

    def test_a_returns_table_fed_from_a_mismatched_column(self, in_tmp: Path, check_server) -> None:
        _project(in_tmp, check_server, RETURNS_TABLE)

        assert len(_findings(check_server)) == 1

    def test_an_insert_select_whose_source_type_mismatches(
        self, in_tmp: Path, check_server
    ) -> None:
        _project(in_tmp, check_server, INSERT_SELECT)

        assert len(_findings(check_server)) == 1

    def test_a_correct_routine_is_silent(self, in_tmp: Path, check_server) -> None:
        _project(in_tmp, check_server, CORRECT)

        assert _findings(check_server) == []


class TestWhereTheFindingPoints:
    def test_it_names_the_routine_the_way_the_catalog_does(
        self, in_tmp: Path, check_server
    ) -> None:
        _project(in_tmp, check_server, SELECT_INTO)

        assert _findings(check_server)[0]["location"] == "app.fn_widget_pk(text)"

    def test_it_names_the_ddl_file_the_routine_is_written_in(
        self, in_tmp: Path, check_server
    ) -> None:
        _project(in_tmp, check_server, SELECT_INTO)

        assert _findings(check_server)[0]["file"] == "db/schema/020_routine.sql"

    def test_the_line_is_the_statement_s_line_in_that_file(
        self, in_tmp: Path, check_server
    ) -> None:
        """``plpgsql_check`` counts from the body's first line; the report counts from the file's."""
        _project(in_tmp, check_server, SELECT_INTO)

        assert _findings(check_server)[0]["line"] == 6


class TestPostgreSQLsOwnDiagnosis:
    def test_the_message_is_quoted_rather_than_paraphrased(
        self, in_tmp: Path, check_server
    ) -> None:
        _project(in_tmp, check_server, SELECT_INTO)

        assert (
            "target type is different type than source type"
            in _findings(check_server)[0]["message"]
        )

    def test_the_sqlstate_is_carried(self, in_tmp: Path, check_server) -> None:
        _project(in_tmp, check_server, SELECT_INTO)

        assert "42804" in _findings(check_server)[0]["message"]
