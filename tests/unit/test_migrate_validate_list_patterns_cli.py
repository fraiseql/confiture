"""CLI tests for ``confiture migrate validate --list-patterns``.

Read-only catalog flag: no DB connection, no config file, no migrations
directory. Mutually exclusive with check-mode flags (``--idempotent``).
"""

from __future__ import annotations

import json
import re

from typer.testing import CliRunner

from confiture.cli.main import app


def _strip_ansi(text: str) -> str:
    """Strip ANSI escape codes (Rich forces them under GITHUB_ACTIONS)."""
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


class TestListPatternsExitCode:
    """Read-only query: always exits 0."""

    def test_exits_zero_with_no_other_flags(self):
        runner = CliRunner()
        result = runner.invoke(app, ["migrate", "validate", "--list-patterns"])
        assert result.exit_code == 0, _strip_ansi(result.output)

    def test_exits_zero_with_format_json(self):
        runner = CliRunner()
        result = runner.invoke(
            app, ["migrate", "validate", "--list-patterns", "--format", "json"]
        )
        assert result.exit_code == 0, _strip_ansi(result.output)


class TestListPatternsTextOutput:
    """Text format: pattern IDs land in stdout."""

    def test_lists_create_table_id(self):
        runner = CliRunner()
        result = runner.invoke(app, ["migrate", "validate", "--list-patterns"])
        out = _strip_ansi(result.output)
        assert "CREATE_TABLE" in out

    def test_lists_drop_sequence_id(self):
        """DROP_SEQUENCE — one of the formerly under-dispatched patterns."""
        runner = CliRunner()
        result = runner.invoke(app, ["migrate", "validate", "--list-patterns"])
        out = _strip_ansi(result.output)
        assert "DROP_SEQUENCE" in out


class TestListPatternsJsonOutput:
    """JSON format: valid, machine-readable shape."""

    def test_emits_valid_json(self):
        runner = CliRunner()
        result = runner.invoke(
            app, ["migrate", "validate", "--list-patterns", "--format", "json"]
        )
        # Parse — must not raise.
        payload = json.loads(result.stdout)
        assert isinstance(payload, dict)

    def test_emits_versioned_envelope(self):
        runner = CliRunner()
        result = runner.invoke(
            app, ["migrate", "validate", "--list-patterns", "--format", "json"]
        )
        payload = json.loads(result.stdout)
        assert payload["version"] == "1"
        assert "patterns" in payload
        assert isinstance(payload["patterns"], list)
        assert len(payload["patterns"]) > 0

    def test_entries_carry_required_fields(self):
        runner = CliRunner()
        result = runner.invoke(
            app, ["migrate", "validate", "--list-patterns", "--format", "json"]
        )
        payload = json.loads(result.stdout)
        for entry in payload["patterns"]:
            assert set(entry.keys()) == {
                "id",
                "description",
                "severity",
                "has_skip_regex",
                "skip_hint",
                "has_auto_fix",
            }


class TestListPatternsMutualExclusion:
    """``--list-patterns`` is a query, not a check — collides with check flags."""

    def test_rejects_combination_with_idempotent(self):
        runner = CliRunner()
        result = runner.invoke(
            app, ["migrate", "validate", "--list-patterns", "--idempotent"]
        )
        assert result.exit_code == 2, _strip_ansi(result.output)


class TestListPatternsIsReadOnly:
    """No DB / config / migrations directory required."""

    def test_runs_outside_a_project_directory(self, tmp_path, monkeypatch):
        """Run with cwd that has no confiture.yaml and no db/migrations."""
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(app, ["migrate", "validate", "--list-patterns"])
        assert result.exit_code == 0, _strip_ansi(result.output)
        # The catalog should still render.
        assert "CREATE_TABLE" in _strip_ansi(result.output)
