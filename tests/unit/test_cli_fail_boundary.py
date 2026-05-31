"""Tests for the JSON-aware CLI error boundary fail() (issue #145).

Uses capsys for real FD-level stdout/stderr separation, per
.phases/.../test-conventions.md (CliRunner cannot separate the streams).
"""

from __future__ import annotations

import json

import pytest
import typer

from confiture.cli.error_json import fail
from confiture.exceptions import ConfigurationError, MigrationConflictError


def test_fail_emits_json_to_stdout_and_exits_with_code(capsys) -> None:
    with pytest.raises(typer.Exit) as exc:
        fail(
            MigrationConflictError("dup", conflicting_files=["a", "b"]),
            json_mode=True,
            output_file=None,
        )
    assert exc.value.exit_code == 3  # MIGR_106 → 3 (#146)
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "MIGR_106"
    assert payload["error"]["details"] == {"conflicting_files": ["a", "b"]}
    assert captured.err == ""  # nothing on stderr in JSON mode


def test_fail_human_mode_writes_stderr_not_stdout(capsys) -> None:
    with pytest.raises(typer.Exit) as exc:
        fail(
            ConfigurationError("bad config", error_code="CONFIG_006"),
            json_mode=False,
            output_file=None,
        )
    assert exc.value.exit_code == 3  # CONFIG_006 → 3 (#146)
    captured = capsys.readouterr()
    assert captured.out == ""  # nothing on stdout in human mode
    assert "bad config" in captured.err


def test_fail_json_exit_code_for_config_invalid(capsys) -> None:
    with pytest.raises(typer.Exit) as exc:
        fail(
            ConfigurationError("missing field", error_code="CONFIG_001"),
            json_mode=True,
            output_file=None,
        )
    assert exc.value.exit_code == 5  # CONFIG_001 → 5 (#146)
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "CONFIG_001"


def test_fail_wraps_non_confiture_exception(capsys) -> None:
    with pytest.raises(typer.Exit) as exc:
        fail(RuntimeError("unexpected"), json_mode=True, output_file=None)
    assert exc.value.exit_code == 1  # generic
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "INTERNAL_ERROR"
    assert "unexpected" in payload["error"]["message"]
