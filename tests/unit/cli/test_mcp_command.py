"""``confiture mcp --port`` serves tools that run migrations, so it needs a bearer token.

The token comes from ``--token`` or ``CONFITURE_MCP_TOKEN``; HTTP mode without one is
a usage error (exit 2) naming both, and nothing is served. None is generated: a
token nobody chose is one nobody holds, and printing it would put it in a log.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core import mcp_http

runner = CliRunner()
URL = "postgresql://localhost/whatever"


@pytest.fixture
def served(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(mcp_http, "serve", lambda **kwargs: calls.append(kwargs))
    monkeypatch.delenv("CONFITURE_MCP_TOKEN", raising=False)
    return calls


def test_http_mode_without_a_token_exits_2(served: list[dict[str, object]]) -> None:
    result = runner.invoke(app, ["mcp", "-d", URL, "--port", "8080"], env={"COLUMNS": "200"})

    assert result.exit_code == 2, result.output
    assert "--token" in result.output
    assert "CONFITURE_MCP_TOKEN" in result.output
    assert served == []


def test_http_mode_reads_the_token_from_the_environment(
    served: list[dict[str, object]],
) -> None:
    result = runner.invoke(
        app, ["mcp", "-d", URL, "--port", "8080"], env={"CONFITURE_MCP_TOKEN": "from-env"}
    )

    assert result.exit_code == 0, result.output
    assert [call["token"] for call in served] == ["from-env"]


def test_http_mode_takes_the_token_option(served: list[dict[str, object]]) -> None:
    result = runner.invoke(app, ["mcp", "-d", URL, "--port", "8080", "--token", "given"])

    assert result.exit_code == 0, result.output
    assert [call["token"] for call in served] == ["given"]
