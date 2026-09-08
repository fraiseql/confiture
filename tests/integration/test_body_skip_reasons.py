"""The other two ways the ``body`` family does not run, each against a real server.

``tests/unit/linting/test_body_skip_contract.py`` covers the reason that needs no
server at all — one that does not answer. The remaining two need one that does:

- a server that answers and carries no ``plpgsql_check``, which is every stock
  PostgreSQL and therefore every CI leg but one;
- a server that answers, carries it, and cannot build the DDL — the only reason
  that can be discovered solely by trying.

Each skips where its precondition is the other one's, so between the two legs
both are exercised.
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

WORKS = """CREATE SCHEMA IF NOT EXISTS app;
CREATE TABLE app.tb_widget (pk_widget BIGINT PRIMARY KEY);
"""

#: Parses, and does not apply: no file creates ``app.tb_absent``. A build that
#: fails here is a build that would fail anywhere.
WILL_NOT_BUILD = """CREATE SCHEMA IF NOT EXISTS app;
CREATE TABLE app.tb_widget (
    pk_widget BIGINT PRIMARY KEY,
    fk_absent BIGINT NOT NULL REFERENCES app.tb_absent (pk_absent)
);
"""


@pytest.fixture
def in_tmp(tmp_path: Path) -> Iterator[Path]:
    old = Path.cwd()
    os.chdir(tmp_path)
    try:
        yield tmp_path
    finally:
        os.chdir(old)


@pytest.fixture
def server_without_the_extension(test_db_url: str) -> str:
    """A server that answers and has no ``plpgsql_check`` — the common case."""
    if plpgsql_check_url() is not None:
        pytest.skip(
            "this server carries plpgsql_check; the missing-extension path needs one without"
        )
    return test_db_url


@pytest.fixture(scope="session")
def check_server() -> str:
    url = plpgsql_check_url()
    if url is None:
        pytest.skip("no server carrying plpgsql_check: set CONFITURE_TEST_DB_URL to one")
    return url


def _project(root: Path, url: str, schema: str) -> None:
    (root / "db" / "schema").mkdir(parents=True, exist_ok=True)
    (root / "db" / "environments").mkdir(parents=True, exist_ok=True)
    (root / "db" / "environments" / "local.yaml").write_text(
        f"database_url: {url}\ninclude_dirs:\n  - path: db/schema\n"
    )
    (root / "db" / "schema" / "010.sql").write_text(schema)


def _skip_reason(server: str) -> str:
    result = runner.invoke(
        app,
        [
            "lint",
            "--select",
            "body_001",
            "--format",
            "json",
            "--fail-on",
            "never",
            "--server-url",
            server,
        ],
    )
    assert result.exit_code == 0, result.output
    skipped = json.loads(result.stdout)["skipped"]
    assert [s["code"] for s in skipped] == ["body_001"], skipped
    return skipped[0]["reason"]


def test_a_server_without_the_extension_says_how_to_get_it(
    in_tmp: Path, server_without_the_extension: str
) -> None:
    _project(in_tmp, server_without_the_extension, WORKS)

    reason = _skip_reason(server_without_the_extension)

    assert "plpgsql_check is not available" in reason
    assert "plpgsql-check" in reason


def test_ddl_that_will_not_apply_is_a_skip_and_not_a_clean_run(
    in_tmp: Path, check_server: str
) -> None:
    """The one reason only an attempt can find: the scratch database would not build."""
    _project(in_tmp, check_server, WILL_NOT_BUILD)

    reason = _skip_reason(check_server)

    assert "scratch database could not be built" in reason


def test_that_skip_does_not_pass_the_gate(in_tmp: Path, check_server: str) -> None:
    _project(in_tmp, check_server, WILL_NOT_BUILD)

    result = runner.invoke(
        app, ["lint", "--select", "body_001", "--fail-on", "warning", "--server-url", check_server]
    )

    assert result.exit_code == 1, result.output
