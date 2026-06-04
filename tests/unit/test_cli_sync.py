"""Unit tests for the ``confiture sync`` CLI (Medium 3, Production Data Sync).

The ``ProductionSyncer`` is mocked at the ``_build_syncer`` factory seam so the
command runs without a database; everything *around* the core — ``--from``/
``--to`` resolution, the anonymization-YAML loader, the warn-when-plaintext
safety posture, output formatting, exit codes, and the #145 JSON envelope — is
exercised for real.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.config.environment import DatabaseConfig

runner = CliRunner()

_RESOLVE = "confiture.cli.sync._resolve_database"
_BUILD = "confiture.cli.sync._build_syncer"


def _mock_syncer(results: dict[str, int] | None = None) -> MagicMock:
    """A ProductionSyncer mock usable as a context manager."""
    m = MagicMock()
    m.__enter__.return_value = m
    m.__exit__.return_value = False
    m.sync.return_value = {"users": 10, "posts": 5} if results is None else results
    return m


def test_sync_basic_runs_and_reports() -> None:
    """`confiture sync --from … --to …` drives ProductionSyncer.sync and reports rows."""
    m = _mock_syncer({"users": 10})
    with (
        patch(_RESOLVE, return_value=DatabaseConfig()),
        patch(_BUILD, return_value=m),
    ):
        r = runner.invoke(app, ["sync", "--from", "production", "--to", "local"])
    assert r.exit_code == 0, r.output
    m.sync.assert_called_once()
    assert "users" in r.output


def test_sync_warns_about_plaintext_when_not_anonymized() -> None:
    """Without --anonymize, the JSON payload carries a PII warning (warn posture)."""
    m = _mock_syncer({"users": 10})
    with patch(_RESOLVE, return_value=DatabaseConfig()), patch(_BUILD, return_value=m):
        r = runner.invoke(
            app, ["sync", "--from", "production", "--to", "local", "--format", "json"]
        )
    assert r.exit_code == 0, r.output
    payload = json.loads(r.output)
    assert payload["ok"] is True
    assert payload["anonymized"] is False
    assert payload["warnings"], "expected a plaintext-PII warning"
    assert any("PII" in w for w in payload["warnings"])


def test_sync_anonymize_loads_rules_from_yaml(tmp_path) -> None:
    """--anonymize parses db/sync/anonymization.yaml into the syncer's rules."""
    cfg = tmp_path / "anon.yaml"
    cfg.write_text(
        "users:\n"
        "  - column: email\n"
        "    strategy: email\n"
        "    seed: 7\n"
        "  - column: ssn\n"
        "    strategy: redact\n"
    )
    m = _mock_syncer({"users": 10})
    with patch(_RESOLVE, return_value=DatabaseConfig()), patch(_BUILD, return_value=m):
        r = runner.invoke(
            app,
            [
                "sync", "--from", "p", "--to", "l",
                "--anonymize", "--anonymization-config", str(cfg),
                "--format", "json",
            ],
        )
    assert r.exit_code == 0, r.output
    sync_config = m.sync.call_args.args[0]
    rules = sync_config.anonymization["users"]
    assert [(rule.column, rule.strategy, rule.seed) for rule in rules] == [
        ("email", "email", 7),
        ("ssn", "redact", None),
    ]
    payload = json.loads(r.output)
    assert payload["anonymized"] is True
    assert payload["warnings"] == []


def test_sync_anonymize_missing_config_fails_config_004(tmp_path) -> None:
    """--anonymize with a missing config file → CONFIG_004 envelope, exit 5."""
    missing = tmp_path / "nope.yaml"
    with patch(_RESOLVE, return_value=DatabaseConfig()):
        r = runner.invoke(
            app,
            [
                "sync", "--from", "p", "--to", "l",
                "--anonymize", "--anonymization-config", str(missing),
                "--format", "json",
            ],
        )
    assert r.exit_code == 5, r.output
    payload = json.loads(r.output)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "CONFIG_004"


def test_sync_unknown_env_fails_with_envelope() -> None:
    """An unresolvable --from env routes through fail() with a config envelope."""
    r = runner.invoke(
        app,
        ["sync", "--from", "does-not-exist-env", "--to", "local", "--format", "json"],
    )
    assert r.exit_code == 5, r.output
    payload = json.loads(r.output)
    assert payload["ok"] is False
    assert payload["error"]["code"].startswith("CONFIG_")


def test_sync_table_selection_include_exclude() -> None:
    """--tables / --exclude become the syncer's TableSelection."""
    m = _mock_syncer({"users": 10})
    with patch(_RESOLVE, return_value=DatabaseConfig()), patch(_BUILD, return_value=m):
        r = runner.invoke(
            app,
            ["sync", "--from", "p", "--to", "l", "--tables", "users, posts", "--exclude", "logs"],
        )
    assert r.exit_code == 0, r.output
    sync_config = m.sync.call_args.args[0]
    assert sync_config.tables.include == ["users", "posts"]
    assert sync_config.tables.exclude == ["logs"]


def test_sync_dsn_resolution_builds_configs() -> None:
    """A raw DSN for --from/--to is parsed into a DatabaseConfig."""
    captured: dict[str, DatabaseConfig] = {}

    def fake_build(source: DatabaseConfig, target: DatabaseConfig) -> MagicMock:
        captured["source"] = source
        captured["target"] = target
        return _mock_syncer({"users": 1})

    with patch(_BUILD, side_effect=fake_build):
        r = runner.invoke(
            app,
            [
                "sync",
                "--from", "postgresql://u:pw@dbhost:5432/prod",
                "--to", "postgresql://u:pw@localhost:5432/dev",
            ],
        )
    assert r.exit_code == 0, r.output
    assert captured["source"].host == "dbhost"
    assert captured["source"].database == "prod"
    assert captured["target"].host == "localhost"
    assert captured["target"].database == "dev"


def test_sync_help_is_reachable() -> None:
    """`confiture sync --help` exits 0 (registered + imports cleanly)."""
    r = runner.invoke(app, ["sync", "--help"])
    assert r.exit_code == 0, r.output
    assert "--anonymize" in r.output
