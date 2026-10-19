"""``confiture seed drift``'s exits and its ``--against``, with no database (#743)."""

import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from tests._helpers import strip_ansi
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.cli.seed_drift import exit_code
from confiture.config.environment import Environment
from confiture.core.seed import drift
from confiture.core.seed.drift import SeedDriftReport, TableDrift
from confiture.core.seed.drift_scope import NotCompared, SeedScope
from confiture.error_codes import FINDINGS, NOT_RUN, SUCCESS
from confiture.exceptions import ConfigurationError

runner = CliRunner()

_TUNNELLED = """database_url: postgresql://app@localhost:${TUNNEL_LOCAL_PORT}/app
include_dirs:
  - path: db/schema
ssh_tunnel:
  host: bastion.invalid
  user: deploy
  remote_host: db.internal
  remote_port: 5432
"""


@pytest.fixture
def in_tmp(tmp_path: Path) -> Iterator[Path]:
    (tmp_path / "db" / "schema").mkdir(parents=True)
    (tmp_path / "db" / "environments").mkdir(parents=True)
    (tmp_path / "db" / "schema" / "t.sql").write_text("CREATE TABLE app.t (k text PRIMARY KEY);\n")
    (tmp_path / "db" / "environments" / "local.yaml").write_text(
        "database_url: postgresql://127.0.0.1:1/confiture_no_such_server\n"
        "include_dirs:\n  - path: db/schema\n"
    )
    old = Path.cwd()
    os.chdir(tmp_path)
    try:
        yield tmp_path
    finally:
        os.chdir(old)


def _report(**overrides: Any) -> SeedDriftReport:
    return SeedDriftReport(seed_side="database", against="x", scope=SeedScope(), **overrides)


class TestExitCodes:
    def test_nothing_to_report(self) -> None:
        assert exit_code(_report()) == SUCCESS

    def test_drift(self) -> None:
        drifted = TableDrift("app.t", ("k",), "primary_key", "full", 1, 0, seed_only=(("a",),))
        assert exit_code(_report(tables=(drifted,))) == FINDINGS

    def test_an_unused_opt_out_is_a_finding_not_an_unfinished_run(self) -> None:
        assert (
            exit_code(_report(unused=("seed_drift.tables.app.gone matches nothing",))) == FINDINGS
        )

    def test_a_table_not_compared(self) -> None:
        assert exit_code(_report(not_compared=(NotCompared("app.t", "why"),))) == NOT_RUN

    def test_an_incomplete_run_is_not_run_even_with_drift(self) -> None:
        """``NOT_RUN`` wins over ``FINDINGS``, as the registry says."""
        drifted = TableDrift("app.t", ("k",), "primary_key", "full", 1, 0, seed_only=(("a",),))
        report = _report(tables=(drifted,), not_compared=(NotCompared("app.u", "why"),))

        assert exit_code(report) == NOT_RUN


def test_against_is_required_unless_listing_the_scope(in_tmp: Path) -> None:
    """A usage error, not a connection one: the flag is missing."""
    result = runner.invoke(app, ["seed", "drift", "--format", "json"])

    output = " ".join(strip_ansi(result.output).split())
    assert result.exit_code == 2, output
    assert "--against" in output
    assert "Cannot reach" not in output


def test_a_mistyped_url_is_refused_without_echoing_its_password(in_tmp: Path) -> None:
    result = runner.invoke(
        app,
        [
            "seed",
            "drift",
            "--against",
            "postgresql+psycopg://app:SQLASECRET@db.internal/prod",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 5, result.output
    assert "SQLASECRET" not in result.output
    assert json.loads(result.stdout)["error"]["code"] == "CONFIG_003"


def test_output_writes_the_json_whatever_the_format(in_tmp: Path) -> None:
    out = in_tmp / "report.json"

    result = runner.invoke(app, ["seed", "drift", "--list-scope", "--output", str(out)])

    assert result.exit_code == 2, result.output  # nothing seeded: nothing compared
    assert json.loads(out.read_text())["compared"] is False


def test_against_an_environment_opens_it_with_its_ssh_tunnel(
    in_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (in_tmp / "db" / "environments" / "production.yaml").write_text(_TUNNELLED)
    opened: list[Any] = []

    def refuse(config: Any, **_kwargs: Any) -> Any:
        opened.append(config)
        raise ConfigurationError("no tunnel in a unit test", error_code="CONFIG_006")

    monkeypatch.setattr(drift, "open_connection", refuse)

    result = runner.invoke(app, ["seed", "drift", "--against", "production", "--format", "json"])

    assert result.exit_code == 3, result.output
    [config] = opened
    assert isinstance(config, Environment)
    assert config.ssh_tunnel is not None


def test_build_without_a_scratch_server_says_how_to_give_one(in_tmp: Path) -> None:
    result = runner.invoke(
        app,
        ["seed", "drift", "--against", "postgresql://127.0.0.1:1/x", "--build", "--format", "json"],
    )

    assert result.exit_code == 5, result.output
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "CONFIG_001"
    assert "--scratch-url" in json.dumps(error)
