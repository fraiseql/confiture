"""`sec_002` and `replica_001` are findings, not console decoration.

Both rules printed straight to the console and contributed nothing to the report
the formatter reads, so `lint --format json` reported `violations.items: []`
while the terminal showed the finding — and worse, the console block landed *in*
the JSON stream, so the payload would not parse at all. `--baseline` could not
see them either. They go through the same report as every other rule now, which
is also what lets the gate read them (LINT-03).
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()

_ENV = (
    "database_url: postgresql://localhost/test\n"
    "include_dirs:\n  - path: db/schema\n"
    "security_lint:\n  enabled: true\n"
)
_UNPINNED_DEFINER = """CREATE SCHEMA IF NOT EXISTS app;

CREATE FUNCTION app.fn_widget() RETURNS int
LANGUAGE sql SECURITY DEFINER AS $$ SELECT 1 $$;
"""


@pytest.fixture
def definer_project(tmp_path: Path) -> Iterator[Path]:
    (tmp_path / "db" / "schema").mkdir(parents=True)
    (tmp_path / "db" / "environments").mkdir(parents=True)
    (tmp_path / "db" / "environments" / "local.yaml").write_text(_ENV)
    (tmp_path / "db" / "schema" / "010_widget.sql").write_text(_UNPINNED_DEFINER)

    old_cwd = Path.cwd()
    os.chdir(tmp_path)
    try:
        yield tmp_path
    finally:
        os.chdir(old_cwd)


@pytest.fixture
def replica_project(tmp_path: Path) -> Iterator[Path]:
    (tmp_path / "db" / "schema").mkdir(parents=True)
    (tmp_path / "db" / "schema" / "010_t.sql").write_text(
        "CREATE TABLE tb_t (id INT PRIMARY KEY, c INT);\n"
    )
    (tmp_path / "db" / "environments").mkdir(parents=True)
    (tmp_path / "db" / "environments" / "local.yaml").write_text(
        "database_url: postgresql://localhost/test\ninclude_dirs:\n  - path: db/schema\n"
    )
    (tmp_path / "db" / "migrations").mkdir(parents=True)
    (tmp_path / "db" / "migrations" / "20260908_1200_drop.up.sql").write_text(
        "ALTER TABLE tb_t DROP COLUMN c;"
    )

    old_cwd = Path.cwd()
    os.chdir(tmp_path)
    try:
        yield tmp_path
    finally:
        os.chdir(old_cwd)


def _items(*args: str) -> list[dict]:
    result = runner.invoke(app, ["lint", "--format", "json", "--fail-on", "never", *args])
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)["violations"]["items"]


class TestSecurityDefiner:
    def test_the_finding_is_in_the_json_report(self, definer_project: Path) -> None:
        findings = [i for i in _items("--check-security-definer") if i["rule_id"] == "sec_002"]

        assert len(findings) == 1
        assert findings[0]["location"] == "app.fn_widget"

    def test_the_finding_carries_its_file_and_line(self, definer_project: Path) -> None:
        finding = next(i for i in _items("--check-security-definer") if i["rule_id"] == "sec_002")

        assert finding["file"] == "db/schema/010_widget.sql"
        assert finding["line"] == 3

    def test_it_is_counted_like_any_other_rule(self, definer_project: Path) -> None:
        result = runner.invoke(
            app, ["lint", "--format", "json", "--fail-on", "never", "--check-security-definer"]
        )
        payload = json.loads(result.stdout)

        assert payload["violations"]["warnings"] >= 1

    def test_a_baseline_can_absorb_it(self, definer_project: Path) -> None:
        base = ["--check-security-definer", "--baseline", "lint-baseline.json"]
        assert runner.invoke(app, ["lint", *base, "--write-baseline"]).exit_code == 0

        stored = json.loads((definer_project / "lint-baseline.json").read_text())
        assert stored["rules"]["sec_002"] == ["sec_002:function:app.fn_widget"]
        assert runner.invoke(app, ["lint", *base]).exit_code == 0


class TestReplica:
    def test_the_finding_is_in_the_json_report(self, replica_project: Path) -> None:
        findings = [i for i in _items("--replica-safe") if i["rule_id"] == "replica_001"]

        assert findings, "replica_001 reported nothing"
        assert findings[0]["file"].endswith("20260908_1200_drop.up.sql")


class TestTheTable:
    def test_a_located_finding_shows_its_file_and_line(self, definer_project: Path) -> None:
        result = runner.invoke(
            app,
            ["lint", "--check-security-definer", "--fail-on", "never"],
            env={"COLUMNS": "200"},
        )

        assert "db/schema/010_widget.sql:3" in result.output


def test_the_help_no_longer_sends_users_elsewhere_for_json() -> None:
    """Read from the declaration, not the rendered help, which wraps and truncates."""
    from typer.main import get_command

    option = next(
        p for p in get_command(app).commands["lint"].params if "--check-security-definer" in p.opts
    )

    assert "lint --format json" not in (option.help or "")
