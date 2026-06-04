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


# ---------------------------------------------------------------------------
# DB-gated e2e (SEC-M3): drive the *real* ``confiture sync`` CLI — no syncer
# mock — against the source/target test databases, so the whole wire from the
# command down to anonymized rows in the target is exercised. Skips when no
# Postgres (the ``source_db``/``target_db`` fixtures call ``pytest.skip``).
# ---------------------------------------------------------------------------

_PII_DDL = """
    CREATE TABLE users (
        id SERIAL PRIMARY KEY,
        email VARCHAR(255) NOT NULL,
        ssn VARCHAR(11)
    )
"""


def _seed_source(source_db) -> None:
    """Create the PII table on source and insert real-looking rows."""
    with source_db.cursor() as cur:
        cur.execute(_PII_DDL)
        cur.execute(
            """
            INSERT INTO users (email, ssn) VALUES
                ('john.doe@example.com', '123-45-6789'),
                ('jane.smith@company.org', '987-65-4321')
            """
        )


def test_sync_cli_anonymizes_real_data_deterministically(
    source_db, target_db, source_db_url, target_db_url, tmp_path
) -> None:
    """`confiture sync --anonymize` masks PII in the target, deterministically.

    Drives the actual Typer command against two real databases (DSN form of
    ``--from``/``--to``), so the CLI → ``ProductionSyncer`` → target path is
    covered end to end — not just the plumbing around a mocked syncer.
    """
    _seed_source(source_db)
    # The syncer copies *data*, not schema — the target table must pre-exist.
    with target_db.cursor() as cur:
        cur.execute(_PII_DDL)

    anon = tmp_path / "anonymization.yaml"
    anon.write_text(
        "users:\n"
        "  - column: email\n"
        "    strategy: email\n"
        "    seed: 12345\n"
        "  - column: ssn\n"
        "    strategy: redact\n"
    )
    argv = [
        "sync",
        "--from", source_db_url,
        "--to", target_db_url,
        "--anonymize",
        "--anonymization-config", str(anon),
    ]

    r = runner.invoke(app, argv)
    assert r.exit_code == 0, r.output

    def target_rows() -> dict[int, tuple[str, str]]:
        with target_db.cursor() as cur:
            cur.execute("SELECT id, email, ssn FROM users ORDER BY id")
            return {row[0]: (row[1], row[2]) for row in cur.fetchall()}

    first = target_rows()
    assert len(first) == 2
    emails = {email for email, _ in first.values()}
    # Email is transformed (no source value survives) but stays email-shaped.
    assert "john.doe@example.com" not in emails
    assert "jane.smith@company.org" not in emails
    assert all("@" in email for email in emails)
    # SSN is redacted outright.
    assert all(ssn == "[REDACTED]" for _, ssn in first.values())

    # Determinism: a second run with the same seed reproduces the same masking.
    r2 = runner.invoke(app, argv)
    assert r2.exit_code == 0, r2.output
    assert target_rows() == first


def test_sync_cli_verbatim_warns_and_copies_unmasked(
    source_db, target_db, source_db_url, target_db_url
) -> None:
    """Without --anonymize the CLI copies verbatim and warns about plaintext PII.

    This is the Phase-05 *warn* posture, asserted end to end: the data lands
    unmasked AND the JSON envelope carries a non-empty ``warnings`` array.
    """
    _seed_source(source_db)
    with target_db.cursor() as cur:
        cur.execute(_PII_DDL)

    r = runner.invoke(
        app,
        ["sync", "--from", source_db_url, "--to", target_db_url, "--format", "json"],
    )
    assert r.exit_code == 0, r.output
    payload = json.loads(r.output)
    assert payload["ok"] is True
    assert payload["anonymized"] is False
    assert payload["warnings"], "verbatim sync must surface a plaintext-PII warning"

    # Data copied verbatim — the source PII is present, unmasked, in the target.
    with target_db.cursor() as cur:
        cur.execute("SELECT email, ssn FROM users ORDER BY id")
        rows = cur.fetchall()
    assert ("john.doe@example.com", "123-45-6789") in rows
