"""The parser is named everywhere its verdicts appear.

A standard install classified with a regex backend while ``confiture --version``
and every JSON payload looked exactly like an AST-capable one (#210). The
version output now carries a second line naming pglast and the PostgreSQL
grammar it embeds, and every JSON envelope — payload or error — carries
``parser: {"pglast": "<x.y>", "pg_major": <N>}``.
"""

from __future__ import annotations

import json
import re
from importlib import metadata
from pathlib import Path

import pytest
import typer
from rich.console import Console
from typer.testing import CliRunner

from confiture.cli.error_json import fail
from confiture.cli.helpers import _output_json
from confiture.cli.main import app
from confiture.exceptions import ConfigurationError

runner = CliRunner()
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
PARSER_LINE = re.compile(r"^parser: pglast (\d+\.\d+(?:\.\d+)?) \(PostgreSQL (\d+) grammar\)$")


def _expected_stamp() -> dict:
    from pglast import parser

    return {"pglast": metadata.version("pglast"), "pg_major": parser.get_postgresql_version()[0]}


def test_version_has_a_second_line_naming_the_parser() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0, result.output
    lines = _ANSI.sub("", result.output).strip().splitlines()
    assert lines[0].split()[0] == "confiture"  # the adapter reads this line only
    assert lines[0].split()[-1][0].isdigit()
    assert len(lines) == 3, lines  # version, parser, native extension
    assert lines[2].startswith("native extension: "), lines[2]
    m = PARSER_LINE.match(lines[1])
    assert m, lines[1]
    assert m.group(1) == metadata.version("pglast")
    assert int(m.group(2)) == _expected_stamp()["pg_major"]


def test_output_json_stamps_the_parser(capsys: pytest.CaptureFixture[str]) -> None:
    _output_json({"ok": True}, None, Console())
    data = json.loads(capsys.readouterr().out)
    assert data["parser"] == _expected_stamp()
    assert data["ok"] is True


def test_output_json_stamps_the_parser_into_a_file(tmp_path: Path) -> None:
    target = tmp_path / "out.json"
    _output_json({"ok": True}, target, Console(file=(tmp_path / "log").open("w")))
    assert json.loads(target.read_text())["parser"] == _expected_stamp()


def test_error_envelope_carries_the_parser(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(typer.Exit):
        fail(ConfigurationError("boom", error_code="CONFIG_001"), json_mode=True)
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is False
    assert data["parser"] == _expected_stamp()


def test_a_command_envelope_carries_the_parser() -> None:
    result = runner.invoke(app, ["lint", "--list-rules", "--format", "json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["parser"] == _expected_stamp()
