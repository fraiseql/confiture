"""The experimental commands, each run once by its command line against a database.

``debug cte`` and ``mcp`` promise nothing about their interface
(``tests/unit/test_experimental_commands.py``), which is not the same as promising
nothing: each still starts, connects, and answers the one question it exists for.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app

pytestmark = pytest.mark.integration

runner = CliRunner()

_QUERY = "WITH a AS (SELECT 1 AS x), b AS (SELECT x + 1 AS y FROM a) SELECT y FROM b"


def test_debug_cte_runs_each_step_of_a_query(test_db_url: str) -> None:
    result = runner.invoke(
        app, ["debug", "cte", "-d", test_db_url, "--sql", _QUERY, "--format", "json"]
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert [step["cte_name"] for step in payload["steps"]] == ["a", "b"]
    assert payload["steps"][1]["rows"] == [[2]]


def test_debug_cte_names_the_step_that_fails(test_db_url: str) -> None:
    query = "WITH a AS (SELECT 1 AS x), b AS (SELECT x / 0 AS y FROM a) SELECT y FROM b"

    result = runner.invoke(
        app, ["debug", "cte", "-d", test_db_url, "--sql", query, "--format", "json"]
    )

    assert result.exit_code == 1, result.output
    payload = json.loads(result.stdout)
    assert (payload["failed_at"], payload["steps"][1]["error"]) == ("b", "division by zero")


def test_mcp_answers_over_stdio(test_db_url: str) -> None:
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    ]

    result = runner.invoke(
        app,
        ["mcp", "-d", test_db_url, "--stdio"],
        input="".join(json.dumps(request) + "\n" for request in requests),
    )

    assert result.exit_code == 0, result.output
    responses = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    assert [response["id"] for response in responses] == [1, 2]
    assert responses[0]["result"]["serverInfo"]["name"]
    assert responses[1]["result"]["tools"], "the built-in confiture tools are listed"
