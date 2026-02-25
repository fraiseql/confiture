"""Integration tests for Migrator.reinit() and related methods.

These tests require a running PostgreSQL database.
Set CONFITURE_TEST_DB_URL environment variable to configure.
"""

import os

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.migrator import Migrator
from confiture.exceptions import MigrationError
from confiture.models.results import MigrateReinitResult

runner = CliRunner()


def _make_migration_file(migrations_dir, filename, version, name):
    """Create a Python migration file."""
    class_name = "".join(word.capitalize() for word in name.split("_"))
    (migrations_dir / filename).write_text(f"""
from confiture.models.migration import Migration

class {class_name}(Migration):
    version = "{version}"
    name = "{name}"

    def up(self):
        pass

    def down(self):
        pass
""")


@pytest.mark.integration
class TestMarkAppliedSlug:
    """Test that mark_applied() uses the reason parameter in the slug."""

    def test_mark_applied_baseline_slug(self, test_db_connection, tmp_path):
        """mark_applied with reason='baseline' produces slug ending in _baseline."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        _make_migration_file(migrations_dir, "001_create_users.py", "001", "create_users")

        migrator = Migrator(connection=test_db_connection)
        migrator.initialize()

        # Ensure clean state
        with test_db_connection.cursor() as cursor:
            cursor.execute("DELETE FROM tb_confiture")
        test_db_connection.commit()

        migrator.mark_applied(migrations_dir / "001_create_users.py", reason="baseline")

        with test_db_connection.cursor() as cursor:
            cursor.execute("SELECT slug FROM tb_confiture WHERE version = '001'")
            slug = cursor.fetchone()[0]
            assert slug.endswith("_baseline")

        # Cleanup
        with test_db_connection.cursor() as cursor:
            cursor.execute("DELETE FROM tb_confiture")
        test_db_connection.commit()

    def test_mark_applied_reinit_slug(self, test_db_connection, tmp_path):
        """mark_applied with reason='reinit' produces slug ending in _reinit."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        _make_migration_file(migrations_dir, "001_create_users.py", "001", "create_users")

        migrator = Migrator(connection=test_db_connection)
        migrator.initialize()
        migrator.mark_applied(migrations_dir / "001_create_users.py", reason="reinit")

        with test_db_connection.cursor() as cursor:
            cursor.execute("SELECT slug FROM tb_confiture WHERE version = '001'")
            slug = cursor.fetchone()[0]
            assert slug.endswith("_reinit")

        # Cleanup
        with test_db_connection.cursor() as cursor:
            cursor.execute("DELETE FROM tb_confiture")
        test_db_connection.commit()


@pytest.mark.integration
class TestClearTrackingTable:
    """Test _clear_tracking_table() private method."""

    def test_clear_removes_all_entries(self, test_db_connection, tmp_path):
        """_clear_tracking_table() removes all rows and returns count."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        _make_migration_file(migrations_dir, "001_create_users.py", "001", "create_users")
        _make_migration_file(migrations_dir, "002_add_posts.py", "002", "add_posts")

        migrator = Migrator(connection=test_db_connection)
        migrator.initialize()
        migrator.mark_applied(migrations_dir / "001_create_users.py")
        migrator.mark_applied(migrations_dir / "002_add_posts.py")

        deleted = migrator._clear_tracking_table()
        test_db_connection.commit()

        assert deleted == 2

        with test_db_connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM tb_confiture")
            assert cursor.fetchone()[0] == 0

    def test_clear_empty_table_returns_zero(self, test_db_connection):
        """_clear_tracking_table() returns 0 when table is already empty."""
        migrator = Migrator(connection=test_db_connection)
        migrator.initialize()

        # Ensure table is empty
        with test_db_connection.cursor() as cursor:
            cursor.execute("DELETE FROM tb_confiture")
        test_db_connection.commit()

        deleted = migrator._clear_tracking_table()
        test_db_connection.commit()

        assert deleted == 0


@pytest.mark.integration
class TestReinit:
    """Test Migrator.reinit() method."""

    def test_reinit_through_marks_correct_versions(self, test_db_connection, tmp_path):
        """reinit(through='002') clears table and marks 001-002."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        _make_migration_file(migrations_dir, "001_create_users.py", "001", "create_users")
        _make_migration_file(migrations_dir, "002_add_posts.py", "002", "add_posts")
        _make_migration_file(migrations_dir, "003_add_comments.py", "003", "add_comments")

        migrator = Migrator(connection=test_db_connection)
        migrator.initialize()

        result = migrator.reinit(through="002", migrations_dir=migrations_dir)

        assert isinstance(result, MigrateReinitResult)
        assert result.success is True
        assert len(result.migrations_marked) == 2
        assert result.migrations_marked[0].version == "001"
        assert result.migrations_marked[1].version == "002"

        # Verify DB state
        with test_db_connection.cursor() as cursor:
            cursor.execute("SELECT version FROM tb_confiture ORDER BY applied_at")
            versions = [row[0] for row in cursor.fetchall()]
            assert versions == ["001", "002"]

        # Cleanup
        with test_db_connection.cursor() as cursor:
            cursor.execute("DELETE FROM tb_confiture")
        test_db_connection.commit()

    def test_reinit_all_marks_every_file(self, test_db_connection, tmp_path):
        """reinit() with no through marks all migration files."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        _make_migration_file(migrations_dir, "001_create_users.py", "001", "create_users")
        _make_migration_file(migrations_dir, "002_add_posts.py", "002", "add_posts")
        _make_migration_file(migrations_dir, "003_add_comments.py", "003", "add_comments")

        migrator = Migrator(connection=test_db_connection)
        migrator.initialize()

        result = migrator.reinit(migrations_dir=migrations_dir)

        assert result.success is True
        assert len(result.migrations_marked) == 3
        assert [m.version for m in result.migrations_marked] == ["001", "002", "003"]

        # Cleanup
        with test_db_connection.cursor() as cursor:
            cursor.execute("DELETE FROM tb_confiture")
        test_db_connection.commit()

    def test_reinit_through_unknown_version_raises(self, test_db_connection, tmp_path):
        """reinit(through='999') raises MigrationError."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        _make_migration_file(migrations_dir, "001_create_users.py", "001", "create_users")

        migrator = Migrator(connection=test_db_connection)
        migrator.initialize()

        with pytest.raises(MigrationError, match="999"):
            migrator.reinit(through="999", migrations_dir=migrations_dir)

        # Cleanup
        with test_db_connection.cursor() as cursor:
            cursor.execute("DELETE FROM tb_confiture")
        test_db_connection.commit()

    def test_reinit_returns_correct_result_fields(self, test_db_connection, tmp_path):
        """reinit result has all expected fields."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        _make_migration_file(migrations_dir, "001_create_users.py", "001", "create_users")

        migrator = Migrator(connection=test_db_connection)
        migrator.initialize()

        # Pre-populate to verify deleted_count
        migrator.mark_applied(migrations_dir / "001_create_users.py", reason="baseline")

        result = migrator.reinit(through="001", migrations_dir=migrations_dir)

        assert result.success is True
        assert result.deleted_count == 1
        assert result.dry_run is False
        assert result.total_execution_time_ms >= 0
        assert result.warnings == []
        assert result.error is None

        # Cleanup
        with test_db_connection.cursor() as cursor:
            cursor.execute("DELETE FROM tb_confiture")
        test_db_connection.commit()

    def test_reinit_slugs_end_with_reinit(self, test_db_connection, tmp_path):
        """reinit marks migrations with _reinit slug suffix."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        _make_migration_file(migrations_dir, "001_create_users.py", "001", "create_users")
        _make_migration_file(migrations_dir, "002_add_posts.py", "002", "add_posts")

        migrator = Migrator(connection=test_db_connection)
        migrator.initialize()

        migrator.reinit(through="002", migrations_dir=migrations_dir)

        with test_db_connection.cursor() as cursor:
            cursor.execute("SELECT slug FROM tb_confiture ORDER BY applied_at")
            slugs = [row[0] for row in cursor.fetchall()]
            assert all(s.endswith("_reinit") for s in slugs)

        # Cleanup
        with test_db_connection.cursor() as cursor:
            cursor.execute("DELETE FROM tb_confiture")
        test_db_connection.commit()

    def test_reinit_dry_run_no_side_effects(self, test_db_connection, tmp_path):
        """reinit(dry_run=True) returns result but doesn't modify tb_confiture."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        _make_migration_file(migrations_dir, "001_create_users.py", "001", "create_users")
        _make_migration_file(migrations_dir, "002_add_posts.py", "002", "add_posts")

        migrator = Migrator(connection=test_db_connection)
        migrator.initialize()

        # Pre-populate with baseline entries
        migrator.mark_applied(migrations_dir / "001_create_users.py", reason="baseline")

        result = migrator.reinit(through="002", dry_run=True, migrations_dir=migrations_dir)

        assert result.success is True
        assert result.dry_run is True
        assert result.deleted_count == 1
        assert len(result.migrations_marked) == 2

        # Verify DB is unchanged — still has original baseline entry
        with test_db_connection.cursor() as cursor:
            cursor.execute("SELECT version, slug FROM tb_confiture")
            rows = cursor.fetchall()
            assert len(rows) == 1
            assert rows[0][0] == "001"
            assert rows[0][1].endswith("_baseline")

        # Cleanup
        with test_db_connection.cursor() as cursor:
            cursor.execute("DELETE FROM tb_confiture")
        test_db_connection.commit()

    def test_reinit_result_to_dict(self, test_db_connection, tmp_path):
        """MigrateReinitResult.to_dict() serializes correctly."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        _make_migration_file(migrations_dir, "001_create_users.py", "001", "create_users")

        migrator = Migrator(connection=test_db_connection)
        migrator.initialize()

        # Ensure clean state
        with test_db_connection.cursor() as cursor:
            cursor.execute("DELETE FROM tb_confiture")
        test_db_connection.commit()

        result = migrator.reinit(through="001", migrations_dir=migrations_dir)
        d = result.to_dict()

        assert d["success"] is True
        assert d["deleted_count"] == 0
        assert d["count"] == 1
        assert d["dry_run"] is False
        assert isinstance(d["migrations_marked"], list)
        assert d["migrations_marked"][0]["version"] == "001"

        # Cleanup
        with test_db_connection.cursor() as cursor:
            cursor.execute("DELETE FROM tb_confiture")
        test_db_connection.commit()


def _make_config_file(tmp_path):
    """Create a minimal config file pointing to test database."""
    config_dir = tmp_path / "db" / "environments"
    config_dir.mkdir(parents=True)
    config_file = config_dir / "local.yaml"
    db_url = os.getenv("CONFITURE_TEST_DB_URL", "postgresql://localhost/confiture_test")
    config_file.write_text(f"name: local\ndatabase_url: {db_url}\n")
    return config_file


@pytest.mark.integration
class TestMigrateReinitCLI:
    """Integration tests for the CLI reinit command with real database."""

    def _clean_tracking(self, conn):
        """Helper to ensure clean tracking table state."""
        migrator = Migrator(connection=conn)
        migrator.initialize()
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM tb_confiture")
        conn.commit()

    def test_cli_reinit_through_success(self, tmp_path, test_db_connection):
        """CLI reinit --through with --yes succeeds."""
        config_file = _make_config_file(tmp_path)
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)
        _make_migration_file(migrations_dir, "001_create_users.py", "001", "create_users")
        _make_migration_file(migrations_dir, "002_add_posts.py", "002", "add_posts")

        self._clean_tracking(test_db_connection)

        result = runner.invoke(
            app,
            [
                "migrate",
                "reinit",
                "--through",
                "002",
                "--config",
                str(config_file),
                "--migrations-dir",
                str(migrations_dir),
                "--yes",
            ],
        )
        assert result.exit_code == 0
        assert "Reinit complete" in result.output
        assert "re-marked 2" in result.output

        self._clean_tracking(test_db_connection)

    def test_cli_reinit_all_files(self, tmp_path, test_db_connection):
        """CLI reinit without --through marks all files."""
        config_file = _make_config_file(tmp_path)
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)
        _make_migration_file(migrations_dir, "001_create_users.py", "001", "create_users")
        _make_migration_file(migrations_dir, "002_add_posts.py", "002", "add_posts")
        _make_migration_file(migrations_dir, "003_add_comments.py", "003", "add_comments")

        self._clean_tracking(test_db_connection)

        result = runner.invoke(
            app,
            [
                "migrate",
                "reinit",
                "--config",
                str(config_file),
                "--migrations-dir",
                str(migrations_dir),
                "--yes",
            ],
        )
        assert result.exit_code == 0
        assert "re-marked 3" in result.output

        self._clean_tracking(test_db_connection)

    def test_cli_reinit_dry_run(self, tmp_path, test_db_connection):
        """CLI reinit --dry-run shows preview without changes."""
        config_file = _make_config_file(tmp_path)
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)
        _make_migration_file(migrations_dir, "001_create_users.py", "001", "create_users")

        self._clean_tracking(test_db_connection)

        result = runner.invoke(
            app,
            [
                "migrate",
                "reinit",
                "--through",
                "001",
                "--config",
                str(config_file),
                "--migrations-dir",
                str(migrations_dir),
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        assert "DRY RUN" in result.output
        assert "Would delete" in result.output

        # Verify DB unchanged
        with test_db_connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM tb_confiture")
            assert cursor.fetchone()[0] == 0

    def test_cli_reinit_version_not_found(self, tmp_path, test_db_connection):
        """CLI reinit --through with unknown version exits 1."""
        config_file = _make_config_file(tmp_path)
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)
        _make_migration_file(migrations_dir, "001_create_users.py", "001", "create_users")

        self._clean_tracking(test_db_connection)

        result = runner.invoke(
            app,
            [
                "migrate",
                "reinit",
                "--through",
                "999",
                "--config",
                str(config_file),
                "--migrations-dir",
                str(migrations_dir),
                "--yes",
            ],
        )
        assert result.exit_code == 1
        assert "999" in result.output

    def test_cli_reinit_confirmation_declined(self, tmp_path, test_db_connection):
        """CLI reinit without --yes prompts and respects decline."""
        config_file = _make_config_file(tmp_path)
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)
        _make_migration_file(migrations_dir, "001_create_users.py", "001", "create_users")

        self._clean_tracking(test_db_connection)

        result = runner.invoke(
            app,
            [
                "migrate",
                "reinit",
                "--through",
                "001",
                "--config",
                str(config_file),
                "--migrations-dir",
                str(migrations_dir),
            ],
            input="n\n",
        )
        assert result.exit_code == 0
        assert "Aborted" in result.output

        # Verify DB unchanged (confirmation declined)
        with test_db_connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM tb_confiture")
            assert cursor.fetchone()[0] == 0


@pytest.mark.integration
class TestReinitScenarios:
    """End-to-end scenarios testing reinit in realistic workflows."""

    def _clean_tracking(self, conn):
        """Helper to ensure clean tracking table state."""
        migrator = Migrator(connection=conn)
        migrator.initialize()
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM tb_confiture")
        conn.commit()

    def test_reinit_after_consolidation_scenario(self, test_db_connection, tmp_path):
        """Simulate the exact Issue #47 scenario.

        1. Mark 5 migrations as applied (baseline)
        2. Simulate consolidation: replace files on disk with 3 consolidated files
        3. Run reinit(through="003")
        4. Verify clean state: 3 entries with _reinit slugs
        """
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        migrator = Migrator(connection=test_db_connection)
        migrator.initialize()
        self._clean_tracking(test_db_connection)

        # Step 1: Create and baseline 5 migrations
        for i in range(1, 6):
            ver = f"00{i}"
            name = f"migration_{i}"
            _make_migration_file(migrations_dir, f"{ver}_{name}.py", ver, name)

        for i in range(1, 6):
            ver = f"00{i}"
            name = f"migration_{i}"
            migrator.mark_applied(migrations_dir / f"{ver}_{name}.py", reason="baseline")

        # Verify: 5 entries with _baseline slugs
        with test_db_connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM tb_confiture")
            assert cursor.fetchone()[0] == 5

        # Step 2: Simulate consolidation — replace files with 3 consolidated files
        import shutil

        for f in migrations_dir.iterdir():
            if f.is_dir():
                shutil.rmtree(f)
            else:
                f.unlink()
        for i in range(1, 4):
            ver = f"00{i}"
            name = f"consolidated_{i}"
            _make_migration_file(migrations_dir, f"{ver}_{name}.py", ver, name)

        # Step 3: Reinit
        result = migrator.reinit(through="003", migrations_dir=migrations_dir)

        # Step 4: Verify clean state
        assert result.success is True
        assert result.deleted_count == 5
        assert len(result.migrations_marked) == 3

        with test_db_connection.cursor() as cursor:
            cursor.execute("SELECT version, slug FROM tb_confiture ORDER BY version")
            rows = cursor.fetchall()
            assert len(rows) == 3
            assert [r[0] for r in rows] == ["001", "002", "003"]
            assert all(r[1].endswith("_reinit") for r in rows)

        self._clean_tracking(test_db_connection)

    def test_migrate_up_works_after_reinit(self, test_db_connection, tmp_path):
        """After reinit(through='002'), migrate up should apply 003+.

        This tests that reinit leaves the tracking table in a valid state
        that allows normal migration flow to continue.
        """
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        # Create 3 migrations — 003 creates a real table
        _make_migration_file(migrations_dir, "001_create_users.py", "001", "create_users")
        _make_migration_file(migrations_dir, "002_add_posts.py", "002", "add_posts")

        # 003 creates an actual table so we can verify it ran
        class_content = """
from confiture.models.migration import Migration

class AddReinitTestTable(Migration):
    version = "003"
    name = "add_reinit_test_table"

    def up(self):
        self.execute("CREATE TABLE IF NOT EXISTS reinit_test_table (id SERIAL PRIMARY KEY)")

    def down(self):
        self.execute("DROP TABLE IF EXISTS reinit_test_table")
"""
        (migrations_dir / "003_add_reinit_test_table.py").write_text(class_content)

        migrator = Migrator(connection=test_db_connection)
        migrator.initialize()
        self._clean_tracking(test_db_connection)

        # Reinit through 002 — marks 001 and 002 without executing
        migrator.reinit(through="002", migrations_dir=migrations_dir)

        # Now migrate up should apply only 003
        applied_versions = migrator.migrate_up(migrations_dir=migrations_dir)

        assert applied_versions == ["003"]

        # Verify table was actually created
        with test_db_connection.cursor() as cursor:
            cursor.execute("""
                SELECT EXISTS (
                    SELECT FROM pg_tables
                    WHERE schemaname = 'public'
                    AND tablename = 'reinit_test_table'
                )
            """)
            assert cursor.fetchone()[0] is True

        # Verify tracking table has all 3
        with test_db_connection.cursor() as cursor:
            cursor.execute("SELECT version, slug FROM tb_confiture ORDER BY version")
            rows = cursor.fetchall()
            assert len(rows) == 3
            # 001, 002 have _reinit slugs; 003 was actually executed
            assert rows[0][1].endswith("_reinit")
            assert rows[1][1].endswith("_reinit")

        # Cleanup
        with test_db_connection.cursor() as cursor:
            cursor.execute("DROP TABLE IF EXISTS reinit_test_table")
        self._clean_tracking(test_db_connection)
