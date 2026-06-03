"""Error-path tests for `confiture debug cte` after the fail() conversion.

The command emits the unified ``{ok: false, error: {...}}`` envelope in
``--format json`` mode and exits with the registry-derived code: a connection
failure is CONFIG_006 (exit 3), a missing input is CONFIG_001 (exit 5). A
failing CTE in the user's query is a success-signal (exit 1) and is covered by
the table/json rendering tests elsewhere — it is intentionally not an error
envelope.
"""

from __future__ import annotations

import json
from unittest.mock import patch

from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()


def test_debug_cte_no_input_exits_config_error() -> None:
    result = runner.invoke(app, ["debug", "cte", "-d", "postgresql://x/y"])
    assert result.exit_code == 5
    assert "Provide --sql or --file" in result.output


def test_debug_cte_no_input_json_envelope() -> None:
    result = runner.invoke(app, ["debug", "cte", "-d", "postgresql://x/y", "--format", "json"])
    assert result.exit_code == 5
    data = json.loads(result.output)
    assert data["ok"] is False
    assert data["error"]["code"] == "CONFIG_001"


def test_debug_cte_missing_file_exits_config_error(tmp_path) -> None:
    missing = tmp_path / "nope.sql"
    result = runner.invoke(app, ["debug", "cte", "-d", "postgresql://x/y", "--file", str(missing)])
    assert result.exit_code == 5
    assert "not found" in result.output.lower()


def test_debug_cte_connection_failure_is_config_006() -> None:
    with patch("psycopg.connect", side_effect=RuntimeError("boom")):
        result = runner.invoke(app, ["debug", "cte", "-d", "postgresql://x/y", "--sql", "SELECT 1"])
    assert result.exit_code == 3


def test_debug_cte_connection_failure_json_envelope() -> None:
    with patch("psycopg.connect", side_effect=RuntimeError("boom")):
        result = runner.invoke(
            app,
            ["debug", "cte", "-d", "postgresql://x/y", "--sql", "SELECT 1", "--format", "json"],
        )
    assert result.exit_code == 3
    data = json.loads(result.output)
    assert data["ok"] is False
    assert data["error"]["code"] == "CONFIG_006"
