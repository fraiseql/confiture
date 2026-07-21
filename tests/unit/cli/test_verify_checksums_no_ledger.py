"""`verify-checksums` against a database with no migration ledger (#182a).

0.36.0 crashed with a raw psycopg `relation "tb_confiture" does not exist` at
exit 1 — the same code the command uses for "checksum mismatches found", so the
two states were indistinguishable.  It now exits 2 (`PRECON_1001`), or 0 under
`--allow-uninitialized`.

CliRunner merges stdout/stderr, so these assert on exit codes and combined
output substrings only — never on stream identity.
"""

from __future__ import annotations

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
    cfg: Path, migrations_dir: Path, *extra: str, ledger: bool, argv0: str = "verify-checksums"
):
    """Invoke the command with the ledger probe forced to `ledger`.

    `verify_checksums` imports both names inside the function body, so the
    patch targets are the source modules, not `commands.admin`.
    """
    with (
        patch("confiture.core.connection.create_connection", return_value=MagicMock()),
        patch("confiture.core.ledger.ledger_exists", return_value=ledger),
    ):
        return runner.invoke(
            app,
            [argv0, "-c", str(cfg), "--migrations-dir", str(migrations_dir), *extra],
        )


class TestAbsentLedger:
    def test_absent_ledger_exits_2(self, cfg: Path, migrations_dir: Path) -> None:
        result = _invoke(cfg, migrations_dir, ledger=False)

        assert result.exit_code == 2
        assert "tb_confiture" in result.output
        for marker in RAW_PSYCOPG_MARKERS:
            assert marker not in result.output

    def test_absent_ledger_message_is_actionable(self, cfg: Path, migrations_dir: Path) -> None:
        result = _invoke(cfg, migrations_dir, ledger=False)

        assert "is not present in this database" in result.output
        # The three ways forward, per _NO_LEDGER_HINT.
        assert "migrate up" in result.output
        assert "baseline" in result.output
        assert "--allow-uninitialized" in result.output


class TestAllowUninitialized:
    def test_allow_uninitialized_exits_0(self, cfg: Path, migrations_dir: Path) -> None:
        result = _invoke(cfg, migrations_dir, "--allow-uninitialized", ledger=False)

        assert result.exit_code == 0
        assert "no migration ledger" in result.output.lower()
        for marker in RAW_PSYCOPG_MARKERS:
            assert marker not in result.output

    def test_allow_uninitialized_reports_zero_recorded(
        self, cfg: Path, migrations_dir: Path
    ) -> None:
        result = _invoke(cfg, migrations_dir, "--allow-uninitialized", ledger=False)

        assert "0 migrations recorded" in result.output


class TestAbsentIsNotEmpty:
    """A present-but-empty ledger is a different state and still succeeds.

    If this fails, the probe is in the wrong place — it is conflating "no
    table" with "no rows", which is the bug this phase exists to fix.
    """

    def test_present_but_empty_ledger_still_succeeds(self, cfg: Path, migrations_dir: Path) -> None:
        with patch(
            "confiture.core.checksum.MigrationChecksumVerifier._get_stored_checksums",
            return_value={},
        ):
            result = _invoke(cfg, migrations_dir, ledger=True)

        assert result.exit_code == 0
        assert "All migration checksums verified" in result.output
        assert "no migration ledger" not in result.output.lower()


class TestDeprecatedAliasParity:
    def test_deprecated_verify_alias_inherits_no_ledger_handling(
        self, cfg: Path, migrations_dir: Path
    ) -> None:
        result = _invoke(cfg, migrations_dir, ledger=False, argv0="verify")

        assert result.exit_code == 2
        assert "is not present in this database" in result.output
        # The deprecation warning still fires (combined-stream assertion).
        assert "deprecated" in result.output.lower()

    def test_deprecated_alias_accepts_allow_uninitialized(
        self, cfg: Path, migrations_dir: Path
    ) -> None:
        result = _invoke(cfg, migrations_dir, "--allow-uninitialized", ledger=False, argv0="verify")

        assert result.exit_code == 0
        assert "no migration ledger" in result.output.lower()
