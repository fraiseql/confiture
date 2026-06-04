"""End-to-end happy-path for the ``confiture sync`` workflow (Medium 3).

Drives the production-sync command through the real Typer ``app`` (the same
entrypoint the ``confiture`` console script invokes). The ``ProductionSyncer`` is
mocked at the ``_build_syncer`` factory seam so the workflow runs without a
database; everything *around* the core — ``--from``/``--to`` resolution, the
anonymization-YAML loader, the warn-when-plaintext posture, output formatting,
exit codes, and the JSON envelope — is exercised for real.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.config.environment import DatabaseConfig

runner = CliRunner()

CONN = ["--from", "production", "--to", "local"]


def _fake_syncer(results: dict[str, int]) -> MagicMock:
    """A ProductionSyncer mock (context manager) reporting a clean sync."""
    m = MagicMock()
    m.__enter__.return_value = m
    m.__exit__.return_value = False
    m.sync.return_value = results
    return m


def test_sync_workflow_basic_then_anonymized(tmp_path) -> None:
    """A verbatim sync (warned) then an anonymized sync both succeed end to end."""
    with patch("confiture.cli.sync._resolve_database", return_value=DatabaseConfig()):
        # 1. Basic verbatim sync — runs, reports rows, exit 0.
        m1 = _fake_syncer({"users": 1_000, "posts": 250})
        with patch("confiture.cli.sync._build_syncer", return_value=m1):
            r = runner.invoke(app, ["sync", *CONN])
        assert r.exit_code == 0, r.output
        assert "users" in r.output and "posts" in r.output
        m1.sync.assert_called_once()

        # 2. Anonymized sync against a real rules file (real YAML parse).
        anon = tmp_path / "anonymization.yaml"
        anon.write_text(
            "users:\n"
            "  - column: email\n"
            "    strategy: email\n"
            "    seed: 12345\n"
            "  - column: ssn\n"
            "    strategy: redact\n"
        )
        m2 = _fake_syncer({"users": 1_000})
        with patch("confiture.cli.sync._build_syncer", return_value=m2):
            r = runner.invoke(
                app,
                ["sync", *CONN, "--anonymize", "--anonymization-config", str(anon)],
            )
        assert r.exit_code == 0, r.output
        passed_config = m2.sync.call_args.args[0]
        assert passed_config.anonymization["users"][0].strategy == "email"
        assert passed_config.anonymization["users"][0].seed == 12345


def test_sync_workflow_json_envelopes_are_well_formed(tmp_path) -> None:
    """Both the verbatim and anonymized JSON outputs are valid envelopes."""
    with patch("confiture.cli.sync._resolve_database", return_value=DatabaseConfig()):
        # Verbatim → ok:true, anonymized:false, a plaintext warning present.
        m1 = _fake_syncer({"users": 10})
        with patch("confiture.cli.sync._build_syncer", return_value=m1):
            r = runner.invoke(app, ["sync", *CONN, "--format", "json"])
        assert r.exit_code == 0, r.output
        payload = json.loads(r.output)
        assert payload["ok"] is True
        assert payload["command"] == "sync"
        assert payload["anonymized"] is False
        assert payload["total_rows"] == 10
        assert payload["warnings"]

        # Anonymized → no warning, anonymized:true.
        anon = tmp_path / "a.yaml"
        anon.write_text("users:\n  - column: email\n    strategy: email\n")
        m2 = _fake_syncer({"users": 10})
        with patch("confiture.cli.sync._build_syncer", return_value=m2):
            r = runner.invoke(
                app,
                ["sync", *CONN, "--anonymize", "--anonymization-config", str(anon), "--format", "json"],
            )
        assert r.exit_code == 0, r.output
        payload = json.loads(r.output)
        assert payload["anonymized"] is True
        assert payload["warnings"] == []


def test_sync_workflow_table_selection(tmp_path) -> None:
    """--tables / --exclude flow through to the syncer's selection."""
    m = _fake_syncer({"users": 5})
    with (
        patch("confiture.cli.sync._resolve_database", return_value=DatabaseConfig()),
        patch("confiture.cli.sync._build_syncer", return_value=m),
    ):
        r = runner.invoke(
            app, ["sync", *CONN, "--tables", "users,posts", "--exclude", "audit_log"]
        )
    assert r.exit_code == 0, r.output
    selection = m.sync.call_args.args[0].tables
    assert selection.include == ["users", "posts"]
    assert selection.exclude == ["audit_log"]
