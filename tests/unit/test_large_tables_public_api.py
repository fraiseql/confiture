"""Tests for large_tables public API exposure (Phase 03)."""

from unittest.mock import MagicMock, patch


def test_batched_migration_importable():
    """BatchedMigration is importable from the public API."""
    from confiture import BatchedMigration, BatchConfig, OnlineIndexBuilder

    assert BatchedMigration is not None
    assert BatchConfig().batch_size == 10000
    assert OnlineIndexBuilder is not None


def test_table_size_estimator_importable():
    """TableSizeEstimator is importable from the public API."""
    from confiture import TableSizeEstimator

    assert TableSizeEstimator is not None


def test_batch_progress_importable():
    """BatchProgress is importable from the public API."""
    from confiture import BatchProgress

    assert BatchProgress is not None


def test_migrate_up_accepts_batched_flag():
    """--batched and --batch-size flags are accepted by migrate up."""
    from typer.testing import CliRunner

    from confiture.cli.main import app

    runner = CliRunner()

    # With a non-existent config, the command should exit early but accept the flags
    result = runner.invoke(
        app,
        [
            "migrate",
            "up",
            "--batched",
            "--batch-size",
            "5000",
            "--batch-sleep",
            "0.05",
            "--config",
            "/nonexistent/confiture.yaml",
        ],
    )
    # Should fail because config not found, not because flags are unknown
    assert result.exit_code != 0
    assert "Error: No such option" not in (result.output or "")
    assert "Error: No such option" not in str(result.exception or "")


def test_migrate_estimate_command_registered():
    """migrate estimate command is registered in the CLI."""
    from typer.testing import CliRunner

    from confiture.cli.main import app

    runner = CliRunner()
    result = runner.invoke(app, ["migrate", "estimate", "--help"])
    assert result.exit_code == 0
    assert "estimate" in result.output.lower() or "row" in result.output.lower()


def test_batch_config_default_values():
    """BatchConfig has correct default values."""
    from confiture.core.large_tables import BatchConfig

    config = BatchConfig()
    assert config.batch_size == 10000
    assert config.sleep_between_batches == 0.1
    assert config.progress_callback is None


def test_migrate_estimate_with_mock_db(tmp_path):
    """migrate estimate runs and outputs table size info."""
    import json

    from typer.testing import CliRunner

    from confiture.cli.main import app

    runner = CliRunner()

    config_file = tmp_path / "confiture.yaml"
    config_file.write_text("database:\n  url: postgresql://localhost/test\n")

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
    mock_cursor.__exit__ = MagicMock(return_value=False)
    mock_cursor.fetchall.return_value = [("users",), ("orders",)]
    mock_conn.cursor.return_value = mock_cursor

    mock_estimator = MagicMock()
    mock_estimator.get_row_count_estimate.return_value = 1_000_000
    mock_estimator.should_use_batched_operation.return_value = True

    with (
        patch("confiture.core.connection.load_config", return_value=MagicMock()),
        patch("confiture.core.connection.create_connection", return_value=mock_conn),
        patch(
            "confiture.core.large_tables.TableSizeEstimator",
            return_value=mock_estimator,
        ),
    ):
        result = runner.invoke(
            app,
            ["migrate", "estimate", "--config", str(config_file), "--format", "json"],
        )

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert isinstance(data, list)
    assert data[0]["table"] in ("users", "orders")
