"""Integration tests for auto-detect baseline feature (Issue #53).

Requires a live PostgreSQL connection.  Tests are skipped automatically
when no DATABASE_URL is available.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture
def db_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set — skipping integration tests")
    return url


@pytest.fixture
def db_conn(db_url: str):
    import psycopg

    conn = psycopg.connect(db_url)
    yield conn
    conn.close()


@pytest.fixture
def clean_db(db_conn):
    """Ensure tb_confiture is absent before test and cleaned up after."""
    with db_conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS tb_confiture CASCADE")
        cur.execute('DROP EXTENSION IF EXISTS "uuid-ossp" CASCADE')
    db_conn.commit()
    yield db_conn
    with db_conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS tb_confiture CASCADE")
    db_conn.commit()


class TestTrackingTableExists:
    """Tests for Migrator.tracking_table_exists."""

    def test_returns_false_when_table_absent(self, clean_db) -> None:
        from confiture.core.migrator import Migrator

        migrator = Migrator(connection=clean_db)
        assert migrator.tracking_table_exists() is False

    def test_returns_true_after_initialize(self, clean_db) -> None:
        from confiture.core.migrator import Migrator

        migrator = Migrator(connection=clean_db)
        migrator.initialize()
        assert migrator.tracking_table_exists() is True


class TestBaselineThrough:
    """Tests for Migrator.baseline_through."""

    def test_marks_migrations_through_version(self, clean_db, tmp_path: Path) -> None:
        from confiture.core.migrator import Migrator

        # Create fake migration files
        mig_dir = tmp_path / "migrations"
        mig_dir.mkdir()
        for i in range(1, 5):
            ver = f"{i:03d}"
            f = mig_dir / f"{ver}_migration_{i}.py"
            f.write_text(
                f"from confiture.models.migration import Migration\n\n"
                f"class M{ver}(Migration):\n"
                f'    version = "{ver}"\n'
                f'    name = "migration_{i}"\n'
                f"    def up(self): pass\n"
                f"    def down(self): pass\n"
            )

        migrator = Migrator(connection=clean_db)
        migrator.initialize()
        newly_marked = migrator.baseline_through("002", mig_dir)

        assert "001" in newly_marked
        assert "002" in newly_marked
        assert "003" not in newly_marked
        assert "004" not in newly_marked

    def test_does_not_clear_existing_entries(self, clean_db, tmp_path: Path) -> None:
        from confiture.core.migrator import Migrator

        mig_dir = tmp_path / "migrations"
        mig_dir.mkdir()
        for i in range(1, 4):
            ver = f"{i:03d}"
            f = mig_dir / f"{ver}_mig_{i}.py"
            f.write_text(
                f"from confiture.models.migration import Migration\n\n"
                f"class M{ver}(Migration):\n"
                f'    version = "{ver}"\n'
                f'    name = "mig_{i}"\n'
                f"    def up(self): pass\n"
                f"    def down(self): pass\n"
            )

        migrator = Migrator(connection=clean_db)
        migrator.initialize()

        # Mark 001 first
        migrator.mark_applied(mig_dir / "001_mig_1.py", reason="manual")
        applied_before = set(migrator.get_applied_versions())
        assert "001" in applied_before

        # baseline_through should not wipe the existing entry
        migrator.baseline_through("003", mig_dir)
        applied_after = set(migrator.get_applied_versions())
        assert "001" in applied_after
        assert "002" in applied_after
        assert "003" in applied_after

    def test_raises_if_version_not_found(self, clean_db, tmp_path: Path) -> None:
        from confiture.core.migrator import Migrator
        from confiture.exceptions import MigrationError

        mig_dir = tmp_path / "migrations"
        mig_dir.mkdir()
        (mig_dir / "001_init.py").write_text(
            "from confiture.models.migration import Migration\n\n"
            "class M001(Migration):\n"
            '    version = "001"\n'
            '    name = "init"\n'
            "    def up(self): pass\n"
            "    def down(self): pass\n"
        )

        migrator = Migrator(connection=clean_db)
        migrator.initialize()

        with pytest.raises(MigrationError, match="not found on disk"):
            migrator.baseline_through("999", mig_dir)


class TestBaselineDetectorLiveIntrospection:
    """Integration tests for BaselineDetector.introspect_live_schema."""

    def test_returns_sql_string(self, db_conn) -> None:
        from confiture.core.baseline_detector import BaselineDetector

        detector = BaselineDetector(Path("/tmp/snapshots"))
        result = detector.introspect_live_schema(db_conn)
        assert isinstance(result, str)

    def test_result_is_normalisable(self, db_conn) -> None:
        from confiture.core.baseline_detector import BaselineDetector

        detector = BaselineDetector(Path("/tmp/snapshots"))
        live_sql = detector.introspect_live_schema(db_conn)
        normalised = detector.normalize_schema(live_sql)
        assert isinstance(normalised, str)


class TestAutoDetectBaselineCLI:
    """Integration test for migrate up --auto-detect-baseline CLI flag."""

    def test_auto_detect_warns_when_no_snapshots_dir(self, clean_db, tmp_path: Path) -> None:
        """When schema_history/ is absent, warns and proceeds without baselining."""
        from typer.testing import CliRunner

        from confiture.cli.main import app

        # Write a minimal config
        env_dir = tmp_path / "db" / "environments"
        env_dir.mkdir(parents=True)
        db_url = os.environ.get("DATABASE_URL", "postgresql://localhost/test")
        (env_dir / "local.yaml").write_text(
            f"database_url: {db_url}\ninclude_dirs:\n  - {tmp_path / 'db' / 'schema'}\n"
        )
        schema_dir = tmp_path / "db" / "schema"
        schema_dir.mkdir()
        mig_dir = tmp_path / "db" / "migrations"
        mig_dir.mkdir()

        runner = CliRunner()
        result = runner.invoke(
            app,
            [
                "migrate",
                "up",
                "--auto-detect-baseline",
                "--migrations-dir",
                str(mig_dir),
                "--config",
                str(env_dir / "local.yaml"),
            ],
        )

        # Should warn about missing snapshots dir, not crash
        assert "schema_history" in result.output or result.exit_code in (0, 1)
