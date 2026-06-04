"""Tests for "looks unusual" hints on quiet successes (Phase 05, issue #123).

When a command technically succeeds (exit 0) but the success state is
also consistent with a configuration error, the CLI emits an advisory
hint pointing at the most likely root cause. Hints are:

- Written to ``error_console`` (stderr) in text mode.
- Appended to ``payload["hints"]`` (and *not* stderr) in JSON mode.

Hints never change the exit code.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from rich.console import Console
from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()


def _make_empty_dir(tmp_path: Path) -> Path:
    d = tmp_path / "migrations"
    d.mkdir()
    return d


class TestValidateIdempotentZeroFiles:
    """`migrate validate --idempotent` against an empty directory hints."""

    def test_json_mode_emits_hint_in_payload(self, tmp_path: Path) -> None:
        empty_dir = _make_empty_dir(tmp_path)
        result = runner.invoke(
            app,
            [
                "migrate",
                "validate",
                "--idempotent",
                "--migrations-dir",
                str(empty_dir),
                "--format",
                "json",
            ],
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert isinstance(payload["hints"], list)
        assert any("exists but contains no files" in h for h in payload["hints"]), payload

    def test_json_mode_does_not_emit_stderr_hint(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        empty_dir = _make_empty_dir(tmp_path)

        import confiture.cli.helpers as helpers

        err_buf = io.StringIO()
        monkeypatch.setattr(helpers, "error_console", Console(file=err_buf))

        result = runner.invoke(
            app,
            [
                "migrate",
                "validate",
                "--idempotent",
                "--migrations-dir",
                str(empty_dir),
                "--format",
                "json",
            ],
        )
        assert result.exit_code == 0
        # JSON mode never writes hints to stderr.
        assert "Hint:" not in err_buf.getvalue()

    def test_text_mode_emits_stderr_hint(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        empty_dir = _make_empty_dir(tmp_path)

        # Patch the module-level error_console to capture into a buffer
        # — CliRunner's stderr redirect doesn't catch Rich's direct
        # writes to sys.stderr.
        import confiture.cli.helpers as helpers

        err_buf = io.StringIO()
        monkeypatch.setattr(helpers, "error_console", Console(file=err_buf))

        result = runner.invoke(
            app,
            [
                "migrate",
                "validate",
                "--idempotent",
                "--migrations-dir",
                str(empty_dir),
            ],
        )
        assert result.exit_code == 0
        text = err_buf.getvalue()
        assert "Hint:" in text
        # Rich wraps the hint at the (non-TTY) console width, which can split the
        # phrase across a newline; normalize whitespace so the check is width-independent.
        assert "exists but contains no files" in " ".join(text.split())


class TestValidateUnaffectedCommandsStillEmitEmptyHints:
    """Commands without a triggering condition still emit ``"hints": []``."""

    def test_validate_idempotent_with_files_emits_empty_hints(self, tmp_path: Path) -> None:
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        (migrations_dir / "001_init.up.sql").write_text(
            "CREATE TABLE IF NOT EXISTS users (id INT);"
        )

        result = runner.invoke(
            app,
            [
                "migrate",
                "validate",
                "--idempotent",
                "--migrations-dir",
                str(migrations_dir),
                "--format",
                "json",
            ],
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert payload["hints"] == []


class TestEmitHintHelper:
    """The shared ``_emit_hint`` helper dispatches on format."""

    def test_text_mode_writes_to_stderr_only(self) -> None:
        from confiture.cli.helpers import _emit_hint

        err_buf = io.StringIO()
        err_console = Console(file=err_buf)
        hints: list[str] = []
        _emit_hint(
            "Migration directory exists but contains no files.",
            hints_list=hints,
            format_="text",
            error_console=err_console,
        )
        text = err_buf.getvalue()
        assert "Migration directory exists but contains no files." in text
        assert hints == []

    def test_json_mode_appends_to_list_only(self) -> None:
        from confiture.cli.helpers import _emit_hint

        err_buf = io.StringIO()
        err_console = Console(file=err_buf)
        hints: list[str] = []
        _emit_hint(
            "Migration directory exists but contains no files.",
            hints_list=hints,
            format_="json",
            error_console=err_console,
        )
        assert hints == ["Migration directory exists but contains no files."]
        assert err_buf.getvalue() == ""

    @pytest.mark.parametrize("fmt", ["csv", "yaml"])
    def test_non_json_machine_modes_also_use_payload(self, fmt: str) -> None:
        from confiture.cli.helpers import _emit_hint

        err_buf = io.StringIO()
        err_console = Console(file=err_buf)
        hints: list[str] = []
        _emit_hint("x", hints_list=hints, format_=fmt, error_console=err_console)
        assert hints == ["x"]
        assert err_buf.getvalue() == ""
