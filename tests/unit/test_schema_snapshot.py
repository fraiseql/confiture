"""Unit tests for SchemaSnapshotGenerator."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from confiture.core.schema_snapshot import SchemaSnapshotGenerator


class TestSchemaSnapshotGenerator:
    """Tests for SchemaSnapshotGenerator."""

    def test_write_snapshot_creates_correct_filename(self, tmp_path: Path) -> None:
        snapshots_dir = tmp_path / "schema_history"
        gen = SchemaSnapshotGenerator(snapshots_dir=snapshots_dir)

        with patch("confiture.core.schema_snapshot.SchemaBuilder") as mock_builder_cls:
            mock_builder = MagicMock()
            mock_builder.build.return_value = "CREATE TABLE tb_users (id bigint);"
            mock_builder_cls.return_value = mock_builder

            path = gen.write_snapshot("local", "007", "add_payments", Path("/project"))

        assert path == snapshots_dir / "007_add_payments.sql"

    def test_write_snapshot_creates_directory(self, tmp_path: Path) -> None:
        snapshots_dir = tmp_path / "new" / "snapshots"
        gen = SchemaSnapshotGenerator(snapshots_dir=snapshots_dir)

        with patch("confiture.core.schema_snapshot.SchemaBuilder") as mock_builder_cls:
            mock_builder = MagicMock()
            mock_builder.build.return_value = "-- schema"
            mock_builder_cls.return_value = mock_builder

            gen.write_snapshot("local", "001", "init", None)

        assert snapshots_dir.exists()

    def test_write_snapshot_writes_schema_content(self, tmp_path: Path) -> None:
        snapshots_dir = tmp_path / "schema_history"
        gen = SchemaSnapshotGenerator(snapshots_dir=snapshots_dir)
        expected_sql = "CREATE TABLE tb_orders (id bigint NOT NULL);"

        with patch("confiture.core.schema_snapshot.SchemaBuilder") as mock_builder_cls:
            mock_builder = MagicMock()
            mock_builder.build.return_value = expected_sql
            mock_builder_cls.return_value = mock_builder

            path = gen.write_snapshot("local", "003", "add_orders", Path("/project"))

        assert path.read_text() == expected_sql

    def test_write_snapshot_delegates_to_schema_builder(self, tmp_path: Path) -> None:
        snapshots_dir = tmp_path / "schema_history"
        gen = SchemaSnapshotGenerator(snapshots_dir=snapshots_dir)
        project_dir = Path("/my/project")

        with patch("confiture.core.schema_snapshot.SchemaBuilder") as mock_builder_cls:
            mock_builder = MagicMock()
            mock_builder.build.return_value = "SELECT 1;"
            mock_builder_cls.return_value = mock_builder

            gen.write_snapshot("production", "010", "upgrade_pks", project_dir)

        mock_builder_cls.assert_called_once_with(env="production", project_dir=project_dir)
        mock_builder.build.assert_called_once_with(schema_only=True)

    def test_write_snapshot_overwrites_existing_file(self, tmp_path: Path) -> None:
        snapshots_dir = tmp_path / "schema_history"
        snapshots_dir.mkdir()
        existing = snapshots_dir / "005_migration.sql"
        existing.write_text("old content")
        gen = SchemaSnapshotGenerator(snapshots_dir=snapshots_dir)

        with patch("confiture.core.schema_snapshot.SchemaBuilder") as mock_builder_cls:
            mock_builder = MagicMock()
            mock_builder.build.return_value = "new content"
            mock_builder_cls.return_value = mock_builder

            gen.write_snapshot("local", "005", "migration", None)

        assert existing.read_text() == "new content"
