"""The session verifies checksums; ``checksums_verified`` means the verifier ran.

``MigratorSession.up(verify_checksums=True)`` used to set ``checksums_verified``
on the result and never call the verifier — a tampered applied file was
reported as verified. The CLI carried its own copy of the check; the library
path had none.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from confiture.core.checksum import ChecksumVerificationError
from confiture.core.migrator import MigratorSession


def _write(migrations: Path) -> Path:
    migrations.mkdir(parents=True, exist_ok=True)
    up = migrations / "20260906000002_create_gadgets.up.sql"
    up.write_text("CREATE TABLE gadgets (id INT PRIMARY KEY);\n")
    (migrations / "20260906000002_create_gadgets.down.sql").write_text("DROP TABLE gadgets;\n")
    return up


@pytest.fixture
def applied(clean_test_db, test_db_url: str, tmp_path: Path) -> tuple[Path, Path]:
    migrations = tmp_path / "migrations"
    up = _write(migrations)
    with MigratorSession(None, migrations, database_url_override=test_db_url) as s:
        result = s.up()
    assert result.success and [m.version for m in result.migrations_applied] == ["20260906000002"]
    return migrations, up


@pytest.mark.integration
def test_tampered_applied_file_raises(applied, test_db_url: str) -> None:
    migrations, up = applied
    up.write_text(up.read_text() + "-- edited after it was applied\n")

    with MigratorSession(None, migrations, database_url_override=test_db_url) as s:
        with pytest.raises(ChecksumVerificationError) as excinfo:
            s.up(verify_checksums=True)
    assert [m.version for m in excinfo.value.mismatches] == ["20260906000002"]


@pytest.mark.integration
def test_verification_off_reports_it(applied, test_db_url: str) -> None:
    migrations, up = applied
    up.write_text(up.read_text() + "-- edited after it was applied\n")

    with MigratorSession(None, migrations, database_url_override=test_db_url) as s:
        result = s.up(verify_checksums=False)
    assert result.success is True
    assert result.checksums_verified is False


@pytest.mark.integration
def test_clean_files_verify(applied, test_db_url: str) -> None:
    migrations, _ = applied
    with MigratorSession(None, migrations, database_url_override=test_db_url) as s:
        result = s.up(verify_checksums=True)
    assert result.success is True
    assert result.checksums_verified is True


@pytest.mark.integration
def test_force_skips_verification_and_says_so(applied, test_db_url: str) -> None:
    """``force`` re-applies everything and skips the verifier; the result must not claim otherwise."""
    migrations, up = applied
    up.write_text("CREATE TABLE IF NOT EXISTS gadgets (id INT PRIMARY KEY);\n")

    with MigratorSession(None, migrations, database_url_override=test_db_url) as s:
        result = s.up(verify_checksums=True, force=True)
    assert result.success is True, result.errors
    assert result.checksums_verified is False


@pytest.mark.integration
def test_warn_behaviour_reports_mismatch_as_warning(applied, test_db_url: str) -> None:
    migrations, up = applied
    up.write_text(up.read_text() + "-- edited after it was applied\n")

    with MigratorSession(None, migrations, database_url_override=test_db_url) as s:
        result = s.up(verify_checksums=True, on_checksum_mismatch="warn")
    assert result.success is True
    assert result.checksums_verified is False
    assert any("20260906000002" in w for w in result.warnings)
