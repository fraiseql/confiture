"""Unit tests for --live-snapshot flag on migrate generate."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()


def _make_config(tmp_path: Path, *, live_snapshot: bool = False) -> Path:
    """Create a minimal valid environment config that Environment.load accepts."""
    schema_dir = tmp_path / "db" / "schema"
    schema_dir.mkdir(parents=True, exist_ok=True)
    (schema_dir / "01_init.sql").write_text("-- empty schema\n")

    config_dir = tmp_path / "db" / "environments"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / "local.yaml"

    live_line = f"  live_snapshot: {str(live_snapshot).lower()}\n" if live_snapshot else ""
    config_file.write_text(
        "database_url: postgresql://localhost/testdb\n"
        "include_dirs:\n"
        "  - db/schema\n"
        "migration:\n"
        "  snapshot_history: true\n"
        f"{live_line}"
    )
    return config_file


class TestMigrateGenerateLiveSnapshot:
    """Tests for the --live-snapshot flag on migrate generate."""

    def test_live_snapshot_flag_passes_database_url(self, tmp_path: Path) -> None:
        """--live-snapshot passes database_url to write_snapshot."""
        migrations_dir = tmp_path / "migrations"
        config_file = _make_config(tmp_path)

        with patch("confiture.core.schema_snapshot.SchemaSnapshotGenerator") as mock_snap_cls:
            mock_snap = MagicMock()
            mock_snap.write_snapshot.return_value = tmp_path / "snapshot.sql"
            mock_snap_cls.return_value = mock_snap

            result = runner.invoke(
                app,
                [
                    "migrate",
                    "generate",
                    "add_partitions",
                    "--migrations-dir",
                    str(migrations_dir),
                    "--config",
                    str(config_file),
                    "--live-snapshot",
                ],
            )

        assert result.exit_code == 0, result.output
        call_kwargs = mock_snap.write_snapshot.call_args
        assert call_kwargs.kwargs.get("database_url") == "postgresql://localhost/testdb"

    def test_no_live_snapshot_flag_uses_static(self, tmp_path: Path) -> None:
        """Without --live-snapshot, database_url should not be passed."""
        migrations_dir = tmp_path / "migrations"
        config_file = _make_config(tmp_path)

        with patch("confiture.core.schema_snapshot.SchemaSnapshotGenerator") as mock_snap_cls:
            mock_snap = MagicMock()
            mock_snap.write_snapshot.return_value = tmp_path / "snapshot.sql"
            mock_snap_cls.return_value = mock_snap

            result = runner.invoke(
                app,
                [
                    "migrate",
                    "generate",
                    "add_stuff",
                    "--migrations-dir",
                    str(migrations_dir),
                    "--config",
                    str(config_file),
                ],
            )

        assert result.exit_code == 0, result.output
        # write_snapshot should have been called without database_url kwarg
        call_kwargs = mock_snap.write_snapshot.call_args
        assert "database_url" not in (call_kwargs.kwargs or {})

    def test_live_snapshot_fallback_on_failure(self, tmp_path: Path) -> None:
        """When live snapshot fails, fallback to static with warning."""
        migrations_dir = tmp_path / "migrations"
        config_file = _make_config(tmp_path)

        with patch("confiture.core.schema_snapshot.SchemaSnapshotGenerator") as mock_snap_cls:
            mock_snap = MagicMock()
            mock_snap.write_snapshot.side_effect = [
                RuntimeError("connection refused"),
                tmp_path / "snapshot.sql",
            ]
            mock_snap_cls.return_value = mock_snap

            result = runner.invoke(
                app,
                [
                    "migrate",
                    "generate",
                    "add_partitions",
                    "--migrations-dir",
                    str(migrations_dir),
                    "--config",
                    str(config_file),
                    "--live-snapshot",
                ],
            )

        assert result.exit_code == 0, result.output
        assert "Live snapshot failed" in result.output or "falling back to static" in result.output
        assert mock_snap.write_snapshot.call_count == 2

    def test_json_output_includes_snapshot_mode_live(self, tmp_path: Path) -> None:
        """JSON output includes snapshot_mode: live when --live-snapshot is used."""
        migrations_dir = tmp_path / "migrations"
        config_file = _make_config(tmp_path)

        with patch("confiture.core.schema_snapshot.SchemaSnapshotGenerator") as mock_snap_cls:
            mock_snap = MagicMock()
            mock_snap.write_snapshot.return_value = tmp_path / "snapshot.sql"
            mock_snap_cls.return_value = mock_snap

            result = runner.invoke(
                app,
                [
                    "migrate",
                    "generate",
                    "add_partitions",
                    "--migrations-dir",
                    str(migrations_dir),
                    "--config",
                    str(config_file),
                    "--live-snapshot",
                    "--format",
                    "json",
                ],
            )

        assert result.exit_code == 0, result.output
        output = json.loads(result.output)
        assert output["snapshot_mode"] == "live"

    def test_json_output_includes_snapshot_mode_static(self, tmp_path: Path) -> None:
        """JSON output includes snapshot_mode: static when no --live-snapshot."""
        migrations_dir = tmp_path / "migrations"
        config_file = _make_config(tmp_path)

        with patch("confiture.core.schema_snapshot.SchemaSnapshotGenerator") as mock_snap_cls:
            mock_snap = MagicMock()
            mock_snap.write_snapshot.return_value = tmp_path / "snapshot.sql"
            mock_snap_cls.return_value = mock_snap

            result = runner.invoke(
                app,
                [
                    "migrate",
                    "generate",
                    "add_stuff",
                    "--migrations-dir",
                    str(migrations_dir),
                    "--config",
                    str(config_file),
                    "--format",
                    "json",
                ],
            )

        assert result.exit_code == 0, result.output
        output = json.loads(result.output)
        assert output["snapshot_mode"] == "static"

    def test_config_live_snapshot_default(self, tmp_path: Path) -> None:
        """Config-level live_snapshot: true makes --live-snapshot the default."""
        migrations_dir = tmp_path / "migrations"
        config_file = _make_config(tmp_path, live_snapshot=True)

        with patch("confiture.core.schema_snapshot.SchemaSnapshotGenerator") as mock_snap_cls:
            mock_snap = MagicMock()
            mock_snap.write_snapshot.return_value = tmp_path / "snapshot.sql"
            mock_snap_cls.return_value = mock_snap

            result = runner.invoke(
                app,
                [
                    "migrate",
                    "generate",
                    "add_partitions",
                    "--migrations-dir",
                    str(migrations_dir),
                    "--config",
                    str(config_file),
                ],
            )

        assert result.exit_code == 0, result.output
        call_kwargs = mock_snap.write_snapshot.call_args
        assert call_kwargs.kwargs.get("database_url") == "postgresql://localhost/testdb"
