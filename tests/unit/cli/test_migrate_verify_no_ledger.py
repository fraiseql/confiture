"""`migrate verify` against a database with no migration ledger (#182b).

The reporter hit this via `verify-checksums`; `migrate verify` is an
independent crash site — it calls `migrator.get_applied_versions()`, which is
unguarded on an absent tracking table.

⚠️ BREAKING: exit 2 from `migrate verify` previously fell into the adapter
contract's `InvalidConfig` row.  The contract row was widened in the same
commit as this change.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml
from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()

RAW_PSYCOPG_MARKERS = ('relation "', "LINE 1:")


@pytest.fixture
def cfg(tmp_path: Path) -> Path:
    p = tmp_path / "env.yaml"
    p.write_text(
        yaml.safe_dump(
            {
                "name": "test",
                "database_url": "postgresql://localhost/nonexistent_for_test",
                "include_dirs": ["db/schema"],
            }
        )
    )
    return p


@pytest.fixture
def migrations_dir(tmp_path: Path) -> Path:
    d = tmp_path / "migrations"
    d.mkdir()
    (d / "20260101000000_init.up.sql").write_text("CREATE TABLE t (id int);")
    return d


def _invoke(
    cfg: Path,
    migrations_dir: Path,
    *extra: str,
    ledger: bool,
    applied: list[str] | None = None,
):
    """Invoke `migrate verify` with the ledger probe forced to `ledger`."""
    with (
        patch("confiture.core.connection.create_connection", return_value=MagicMock()),
        patch(
            "confiture.core.migrator.Migrator.tracking_table_exists",
            return_value=ledger,
        ),
        patch(
            "confiture.core.migrator.Migrator.get_applied_versions",
            return_value=applied or [],
        ),
    ):
        return runner.invoke(
            app,
            [
                "migrate",
                "verify",
                "-c",
                str(cfg),
                "--migrations-dir",
                str(migrations_dir),
                *extra,
            ],
        )


class TestAbsentLedgerText:
    def test_absent_ledger_text_exits_2(self, cfg: Path, migrations_dir: Path) -> None:
        result = _invoke(cfg, migrations_dir, ledger=False)

        assert result.exit_code == 2
        assert "is not present in this database" in result.output
        for marker in RAW_PSYCOPG_MARKERS:
            assert marker not in result.output

    def test_absent_ledger_message_is_actionable(self, cfg: Path, migrations_dir: Path) -> None:
        result = _invoke(cfg, migrations_dir, ledger=False)

        assert "migrate up" in result.output
        assert "baseline" in result.output
        assert "--allow-uninitialized" in result.output


class TestAllowUninitialized:
    def test_allow_uninitialized_text_exits_0(self, cfg: Path, migrations_dir: Path) -> None:
        result = _invoke(cfg, migrations_dir, "--allow-uninitialized", ledger=False)

        assert result.exit_code == 0
        assert "no migration ledger" in result.output.lower()

    def test_allow_uninitialized_json_is_valid_verify_payload(
        self, cfg: Path, migrations_dir: Path
    ) -> None:
        result = _invoke(
            cfg, migrations_dir, "--allow-uninitialized", "--format", "json", ledger=False
        )

        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["failed_count"] == 0
        assert payload["total_applied"] == 0
        assert payload["results"] == []
        assert payload["ledger_present"] is False


class TestLedgerPresentField:
    def test_ledger_present_true_on_normal_path(self, cfg: Path, migrations_dir: Path) -> None:
        with patch(
            "confiture.core.migration_verifier.MigrationVerifier.verify_all",
            return_value=[],
        ):
            result = _invoke(
                cfg,
                migrations_dir,
                "--format",
                "json",
                ledger=True,
                applied=["20260101000000"],
            )

        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["ledger_present"] is True
        assert payload["total_applied"] == 1


class TestAbsentIsNotEmpty:
    """A present-but-empty ledger is a different state — it must not degrade."""

    def test_present_but_empty_ledger_unchanged(self, cfg: Path, migrations_dir: Path) -> None:
        with patch(
            "confiture.core.migration_verifier.MigrationVerifier.verify_all",
            return_value=[],
        ):
            result = _invoke(cfg, migrations_dir, "--format", "json", ledger=True, applied=[])

        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["total_applied"] == 0
        assert payload["ledger_present"] is True
        # The guard branch was not taken.
        assert "no migration ledger" not in result.output.lower()
