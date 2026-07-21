"""`MigratorSession.preflight()` on a ledger-less database (#182b, third site).

Not CLI-reachable, but it is the documented library idiom — and precisely what
#182's reporter is building.  Unlike its siblings `status()` and
`current_revision()`, `preflight()` called `verifier.verify_all()` with no
existence probe, so it raised psycopg's `UndefinedTable`.

`preflight` is an advisory aggregator rather than a gate, so it degrades:
checksum verification is skipped and the reason reported, no exception.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from confiture.config.environment import Environment
from confiture.core.migrator import Migrator


@pytest.fixture
def migrations_dir(tmp_path: Path) -> Path:
    d = tmp_path / "migrations"
    d.mkdir()
    (d / "20260101000000_init.up.sql").write_text("CREATE TABLE t (id int);")
    (d / "20260101000000_init.down.sql").write_text("DROP TABLE t;")
    return d


def _session(migrations_dir: Path, *, ledger: bool):
    """A session with a connected mock DB whose ledger presence is forced."""
    session = Migrator.from_config(
        Environment.model_validate({"database_url": "postgresql://localhost/x"}),
        migrations_dir=migrations_dir,
    )
    session._conn = MagicMock()
    session._migrator = MagicMock()
    session._migrator.migration_table = "tb_confiture"
    session._migrator.tracking_table_exists.return_value = ledger
    return session


class TestPreflightAbsentLedger:
    def test_preflight_does_not_raise_without_ledger(self, migrations_dir: Path) -> None:
        session = _session(migrations_dir, ledger=False)

        result = session.preflight(versions=["20260101000000"])

        assert result.checksum_verified is False
        assert result.checksum_mismatches == []

    def test_preflight_reports_why_checksums_were_skipped(self, migrations_dir: Path) -> None:
        session = _session(migrations_dir, ledger=False)

        result = session.preflight(versions=["20260101000000"])

        assert result.checksum_skipped_reason is not None
        assert "ledger" in result.checksum_skipped_reason.lower()

    def test_preflight_never_builds_a_verifier_without_ledger(self, migrations_dir: Path) -> None:
        session = _session(migrations_dir, ledger=False)

        with patch("confiture.core.checksum.MigrationChecksumVerifier.verify_all") as verify_all:
            session.preflight(versions=["20260101000000"])

        verify_all.assert_not_called()


class TestPreflightPresentLedger:
    """Absent != empty: a present ledger still verifies, even with no rows."""

    def test_preflight_verifies_when_ledger_present(self, migrations_dir: Path) -> None:
        session = _session(migrations_dir, ledger=True)

        with patch(
            "confiture.core.checksum.MigrationChecksumVerifier.verify_all",
            return_value=[],
        ) as verify_all:
            result = session.preflight(versions=["20260101000000"])

        verify_all.assert_called_once()
        assert result.checksum_verified is True
        assert result.checksum_skipped_reason is None
