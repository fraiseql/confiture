"""Connections and cursors are released on the failure paths (Phase 03, Cycle 7)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from confiture.config.environment import DatabaseConfig
from confiture.core.migration_verifier import MigrationVerifier
from confiture.core.migrator import MigratorSession
from confiture.core.syncer import ProductionSyncer
from confiture.exceptions import ConfigurationError
from tests.unit._doubles import connection_double


def test_syncer_closes_source_when_target_connect_fails() -> None:
    source = connection_double("source")
    syncer = ProductionSyncer(DatabaseConfig(), DatabaseConfig())
    with (
        patch(
            "confiture.core.syncer.create_connection",
            side_effect=[source, ConfigurationError("target unreachable")],
        ),
        pytest.raises(ConfigurationError, match="target unreachable"),
    ):
        syncer.__enter__()
    source.close.assert_called_once()


def test_session_closes_connection_on_bad_tracking_table(tmp_path: Path) -> None:
    conn = connection_double()
    session = MigratorSession(
        None,
        tmp_path,
        database_url_override="postgresql://localhost/x",
        migration_table_override="tb; DROP TABLE users",
    )
    with (
        patch("confiture.core.migrator.create_connection", return_value=conn),
        pytest.raises((ValueError, ConfigurationError)),
    ):
        session.__enter__()
    conn.close.assert_called_once()


def _verifier(tmp_path: Path, *, fail: bool = False) -> tuple[MigrationVerifier, MagicMock, Path]:
    conn = MagicMock()
    cursor = MagicMock()
    cursor.__enter__.return_value = cursor
    conn.cursor.return_value = cursor
    if fail:
        cursor.execute.side_effect = lambda sql, *a: (
            (_ for _ in ()).throw(RuntimeError("boom")) if "SELECT" in str(sql) else None
        )
    else:
        cursor.fetchone.return_value = (True,)
    verify_file = tmp_path / "001_x.verify.sql"
    verify_file.write_text("SELECT true;\n")
    return MigrationVerifier(connection=conn, migrations_dir=tmp_path), cursor, verify_file


def _statements(cursor: MagicMock) -> list[str]:
    return [" ".join(str(c.args[0]).split()) for c in cursor.execute.call_args_list]


@pytest.mark.parametrize("fail", [False, True], ids=["verified", "query-error"])
def test_verifier_releases_savepoint_and_closes_cursor(tmp_path: Path, fail: bool) -> None:
    verifier, cursor, verify_file = _verifier(tmp_path, fail=fail)

    result = verifier.run_verify("001", "x", verify_file)

    statements = _statements(cursor)
    assert "SAVEPOINT verify_check" in statements
    assert "ROLLBACK TO SAVEPOINT verify_check" in statements
    assert statements[-1] == "RELEASE SAVEPOINT verify_check", statements
    assert cursor.__exit__.called, "cursor was not used as a context manager"
    assert result.status == ("failed" if fail else "verified")
