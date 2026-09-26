"""``lint --require-complete``: a run that covered less than it was asked to fails (#431).

A rule that ran without the database it resolves against (``build_003`` when no
server answers) reports what it can and says so in ``degraded[]``; a skipped rule
says so in ``skipped[]``. A CI gate that counts findings still passes such a run —
with fewer findings, because the missing half contributed nothing. With
``--require-complete`` the run exits 2 (``NOT_RUN``) and names each rule and why.
"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.error_codes import NOT_RUN

runner = CliRunner()


def _project(tmp_path: Path, database_url: str) -> Path:
    (tmp_path / "db" / "schema").mkdir(parents=True)
    (tmp_path / "db" / "schema" / "10_t.sql").write_text(
        "CREATE TABLE public.t (id bigint PRIMARY KEY);\n"
        # A reference no file creates: build_003 asks the database whether it exists.
        "CREATE FUNCTION public.f() RETURNS int LANGUAGE sql\n"
        "    AS $$ SELECT count(*)::int FROM public.created_by_a_migration $$;\n"
    )
    (tmp_path / "db" / "environments").mkdir(parents=True)
    (tmp_path / "db" / "environments" / "local.yaml").write_text(
        f"name: local\ndatabase_url: {database_url}\n"
        f"include_dirs:\n  - {tmp_path / 'db' / 'schema'}\n"
    )
    return tmp_path


#: Nothing listens on port 1: the connection is refused at once.
_NO_SERVER = "postgresql://localhost:1/app"


def _lint(project: Path, *extra: str):
    return runner.invoke(
        app,
        ["lint", "--env", "local", "--project-dir", str(project), "--select", "build_003", *extra],
    )


def test_a_degraded_run_exits_not_run_and_names_the_rule(tmp_path: Path) -> None:
    result = _lint(_project(tmp_path, _NO_SERVER), "--require-complete")

    assert result.exit_code == NOT_RUN, result.output
    assert "build_003" in result.output
    assert "degraded" in result.output


def test_the_json_payload_is_still_written_and_carries_why(tmp_path: Path) -> None:
    report = tmp_path / "lint.json"

    result = _lint(
        _project(tmp_path, _NO_SERVER),
        "--require-complete",
        "--format",
        "json",
        "--output",
        str(report),
    )

    assert result.exit_code == NOT_RUN, result.output
    payload = json.loads(report.read_text())
    assert [d["code"] for d in payload["degraded"]] == ["build_003"]


def test_without_the_flag_a_degraded_run_keeps_its_exit(tmp_path: Path) -> None:
    result = _lint(_project(tmp_path, _NO_SERVER))

    assert result.exit_code != NOT_RUN, result.output
