"""Integration tests for auto-detect baseline feature (Issue #53).

Requires a live PostgreSQL connection.  Tests are skipped automatically
when no DATABASE_URL is available.
"""

from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest

pytestmark = pytest.mark.integration


@pytest.fixture
def own_db(fresh_database: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[psycopg.Connection]:
    """A connection to a database this test created, with no DSN in the environment.

    `--auto-detect-baseline` reads the whole database: a ledger anywhere in it, a
    ledger in another schema, every object it compares with a snapshot. On the
    worker's shared database another module, or another run on the same server,
    can leave any of these behind (#710); a database of its own cannot.
    """
    monkeypatch.delenv("CONFITURE_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with psycopg.connect(fresh_database) as conn:
        yield conn


class TestTrackingTableExists:
    """Tests for Migrator.tracking_table_exists."""

    def test_returns_false_when_table_absent(self, own_db) -> None:
        from confiture.core.migrator import Migrator

        migrator = Migrator(connection=own_db)
        assert migrator.tracking_table_exists() is False

    def test_returns_true_after_initialize(self, own_db) -> None:
        from confiture.core.migrator import Migrator

        migrator = Migrator(connection=own_db)
        migrator.initialize()
        assert migrator.tracking_table_exists() is True


class TestBaselineThrough:
    """Tests for Migrator.baseline_through."""

    def test_marks_migrations_through_version(self, own_db, tmp_path: Path) -> None:
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

        migrator = Migrator(connection=own_db)
        migrator.initialize()
        newly_marked = migrator.baseline_through("002", mig_dir)

        assert "001" in newly_marked
        assert "002" in newly_marked
        assert "003" not in newly_marked
        assert "004" not in newly_marked

    def test_does_not_clear_existing_entries(self, own_db, tmp_path: Path) -> None:
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

        migrator = Migrator(connection=own_db)
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

    def test_raises_if_version_not_found(self, own_db, tmp_path: Path) -> None:
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

        migrator = Migrator(connection=own_db)
        migrator.initialize()

        with pytest.raises(MigrationError, match="not found on disk"):
            migrator.baseline_through("999", mig_dir)


class TestAutoDetectBaselineCLI:
    """Integration test for migrate up --auto-detect-baseline CLI flag."""

    def test_auto_detect_proceeds_when_no_snapshot_matches(
        self, own_db, fresh_database: str, tmp_path: Path
    ) -> None:
        """No snapshot describes the database: says so and proceeds without baselining.

        It once passed by reading the repository's own `db/schema_history`, which test
        runs had filled; the history is the test's own now.
        """
        from confiture.core.schema_read import read_text

        history = tmp_path / "db" / "schema_history"
        history.mkdir(parents=True)
        (history / "001_elsewhere.json").write_text(
            read_text("CREATE TABLE tb_never_built (id bigint PRIMARY KEY);").catalogued.to_json()
        )
        from typer.testing import CliRunner

        from confiture.cli.main import app

        # Write a minimal config
        env_dir = tmp_path / "db" / "environments"
        env_dir.mkdir(parents=True)
        (env_dir / "local.yaml").write_text(
            f"database_url: {fresh_database}\ninclude_dirs:\n  - {tmp_path / 'db' / 'schema'}\n"
        )
        schema_dir = tmp_path / "db" / "schema"
        schema_dir.mkdir()
        mig_dir = tmp_path / "db" / "migrations"
        mig_dir.mkdir()

        # What the detector will read: no ledger anywhere, else the policy refuses or skips.
        from confiture.core.ledger import find_ledger_relations

        stray = find_ledger_relations(own_db, "tb_confiture")
        assert not stray, f"a database created for this test holds {stray}: is template1 clean?"

        runner = CliRunner()
        result = runner.invoke(
            app,
            [
                "migrate",
                "up",
                "--auto-detect-baseline",
                "--migrations-dir",
                str(mig_dir),
                "--snapshots-dir",
                str(tmp_path / "db" / "schema_history"),
                "--config",
                str(env_dir / "local.yaml"),
            ],
        )

        # No matching snapshot: says so and proceeds with an empty baseline → exit 0.
        assert result.exit_code == 0, result.output
        said = " ".join(result.output.split())  # however the console wrapped it
        assert "auto-detect baseline" in said
        assert "empty baseline" in said
