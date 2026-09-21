"""Tests for large_tables public API exposure."""


def test_batched_migration_importable():
    """BatchedMigration is importable from the public API."""
    from confiture import BatchConfig, BatchedMigration, OnlineIndexBuilder

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


def test_migrate_up_accepts_batched_flag(monkeypatch):
    """--batched and --batch-size flags are accepted by migrate up."""
    from typer.testing import CliRunner

    from confiture.cli.main import app

    # Clear ambient DSN env vars so a missing --config genuinely errors (this
    # test is about flag *parsing*, not the #140 env-var fallback precedence).
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("CONFITURE_DATABASE_URL", raising=False)

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


def test_batch_config_default_values():
    """BatchConfig has correct default values."""
    from confiture.core.large_tables import BatchConfig

    config = BatchConfig()
    assert config.batch_size == 10000
    assert config.sleep_between_batches == 0.1
    assert config.progress_callback is None
