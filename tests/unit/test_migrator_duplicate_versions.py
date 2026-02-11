"""Unit tests for duplicate migration version detection."""

from pathlib import Path
from unittest.mock import Mock

from confiture.core.migrator import Migrator


class TestFindDuplicateVersions:
    """Test Migrator.find_duplicate_versions()."""

    def _make_migrator(self) -> Migrator:
        return Migrator(connection=Mock())

    def test_no_duplicates_returns_empty_dict(self, tmp_path: Path):
        """Should return empty dict when all versions are unique."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        (migrations_dir / "001_create_users.py").write_text("# migration")
        (migrations_dir / "002_add_email.up.sql").write_text("SELECT 1;")

        migrator = self._make_migrator()
        result = migrator.find_duplicate_versions(migrations_dir)

        assert result == {}

    def test_detect_duplicate_py_files(self, tmp_path: Path):
        """Should detect two .py files with the same version prefix."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        (migrations_dir / "001_create_users.py").write_text("# migration a")
        (migrations_dir / "001_backfill_data.py").write_text("# migration b")

        migrator = self._make_migrator()
        result = migrator.find_duplicate_versions(migrations_dir)

        assert "001" in result
        assert len(result["001"]) == 2
        names = sorted(p.name for p in result["001"])
        assert names == ["001_backfill_data.py", "001_create_users.py"]

    def test_detect_duplicate_sql_files(self, tmp_path: Path):
        """Should detect two .up.sql files with the same version prefix."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        (migrations_dir / "003_add_index.up.sql").write_text("CREATE INDEX;")
        (migrations_dir / "003_add_column.up.sql").write_text("ALTER TABLE;")

        migrator = self._make_migrator()
        result = migrator.find_duplicate_versions(migrations_dir)

        assert "003" in result
        assert len(result["003"]) == 2

    def test_detect_cross_type_duplicates(self, tmp_path: Path):
        """Should detect duplicate when .py and .up.sql share the same version."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        (migrations_dir / "001_create_users.py").write_text("# migration")
        (migrations_dir / "001_backfill_data.up.sql").write_text("INSERT INTO;")

        migrator = self._make_migrator()
        result = migrator.find_duplicate_versions(migrations_dir)

        assert "001" in result
        assert len(result["001"]) == 2
        names = sorted(p.name for p in result["001"])
        assert names == ["001_backfill_data.up.sql", "001_create_users.py"]

    def test_multiple_duplicated_versions(self, tmp_path: Path):
        """Should detect duplicates across multiple version numbers."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        (migrations_dir / "001_a.py").write_text("")
        (migrations_dir / "001_b.py").write_text("")
        (migrations_dir / "002_c.py").write_text("")
        (migrations_dir / "003_d.up.sql").write_text("")
        (migrations_dir / "003_e.up.sql").write_text("")

        migrator = self._make_migrator()
        result = migrator.find_duplicate_versions(migrations_dir)

        assert len(result) == 2
        assert "001" in result
        assert "003" in result
        assert "002" not in result

    def test_three_way_duplicate(self, tmp_path: Path):
        """Should detect when three files share the same version."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        (migrations_dir / "001_a.py").write_text("")
        (migrations_dir / "001_b.py").write_text("")
        (migrations_dir / "001_c.up.sql").write_text("")

        migrator = self._make_migrator()
        result = migrator.find_duplicate_versions(migrations_dir)

        assert "001" in result
        assert len(result["001"]) == 3

    def test_empty_directory(self, tmp_path: Path):
        """Should return empty dict for empty directory."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        migrator = self._make_migrator()
        result = migrator.find_duplicate_versions(migrations_dir)

        assert result == {}

    def test_nonexistent_directory(self, tmp_path: Path):
        """Should return empty dict for nonexistent directory."""
        migrations_dir = tmp_path / "nonexistent"

        migrator = self._make_migrator()
        result = migrator.find_duplicate_versions(migrations_dir)

        assert result == {}

    def test_ignores_down_sql(self, tmp_path: Path):
        """A .down.sql file should not cause a duplicate with its .up.sql counterpart."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        (migrations_dir / "001_create_users.up.sql").write_text("CREATE TABLE;")
        (migrations_dir / "001_create_users.down.sql").write_text("DROP TABLE;")

        migrator = self._make_migrator()
        result = migrator.find_duplicate_versions(migrations_dir)

        assert result == {}

    def test_ignores_init_and_private_files(self, tmp_path: Path):
        """Should ignore __init__.py and _private.py files."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        (migrations_dir / "__init__.py").write_text("")
        (migrations_dir / "_helper.py").write_text("")
        (migrations_dir / "001_create_users.py").write_text("")

        migrator = self._make_migrator()
        result = migrator.find_duplicate_versions(migrations_dir)

        assert result == {}
