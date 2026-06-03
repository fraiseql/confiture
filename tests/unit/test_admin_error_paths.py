"""Error-path tests for admin commands after the fail() conversion.

Locks the contract that the converted failure paths emit the registry-derived
exit code (and the unified envelope where a JSON mode exists), rather than the
old ad-hoc literals. The exit-2 collision in `validate-config --format` is the
headline fix: an invalid format value is a config error (5), never "tracking
table absent" (2).
"""

from __future__ import annotations

import json

from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()


def test_validate_config_invalid_format_is_config_error() -> None:
    result = runner.invoke(app, ["validate-config", "--format", "xml"])
    # Exit 2 is reserved (tracking table absent); a bad --format is a config error.
    assert result.exit_code == 5


def test_validate_profile_missing_file_is_config_error(tmp_path) -> None:
    missing = tmp_path / "nope.yaml"
    result = runner.invoke(app, ["validate-profile", str(missing)])
    assert result.exit_code == 5
    assert "not found" in result.output.lower()


def test_restore_missing_backup_is_restore_error(tmp_path) -> None:
    missing = tmp_path / "nope.pgdump"
    result = runner.invoke(app, ["restore", str(missing), "--database", "db"])
    # Backup-not-found → RESTORE_001 → exit 5 (was the generic 1).
    assert result.exit_code == 5
    assert "not found" in result.output.lower()


def test_validate_config_json_report_still_emits_report_not_envelope(tmp_path) -> None:
    """validate-config emits its #144 report (valid/issues[]), not an error envelope.

    The report-with-signal pattern is intentional: a structurally invalid config
    exits 5 but the JSON payload is the validation report, so the `raise
    typer.Exit(exit_code)` sites there are not failure-boundary bypasses.
    """
    cfg = tmp_path / "bad.yaml"
    cfg.write_text("database_url: not-a-valid-dsn\n")
    result = runner.invoke(app, ["validate-config", "--config", str(cfg), "--format", "json"])
    data = json.loads(result.stdout)
    # It is a report (has the validate-config keys), not an {ok:false} envelope.
    assert "valid" in data
    assert "issues" in data
