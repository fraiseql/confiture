"""Integration tests for ProductionSyncer progress reporting and resume support.

Tests:
1. Progress reporting with rich progress bars
2. Resume from interruption with checkpoints
3. Performance metrics (rows/sec, ETA)
4. Incremental sync after interruption
"""

import pytest
from pathlib import Path
from confiture.core.syncer import ProductionSyncer, SyncConfig, TableSelection
from confiture.config.environment import DatabaseConfig
from unittest.mock import MagicMock, patch
import time


@pytest.fixture
def populated_source_db(source_db, target_db, source_config, target_config):
    """Populate source database with test data and create schema in target."""
    # Create tables in both source and target
    table_ddl = [
        """
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username VARCHAR(255) NOT NULL,
            email VARCHAR(255) NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS posts (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            title VARCHAR(255) NOT NULL,
            content TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS comments (
            id SERIAL PRIMARY KEY,
            post_id INTEGER REFERENCES posts(id),
            content TEXT NOT NULL
        )
        """,
    ]

    # Create in source
    with source_db.cursor() as cur:
        for ddl in table_ddl:
            cur.execute(ddl)

    # Create in target
    with target_db.cursor() as cur:
        for ddl in table_ddl:
            cur.execute(ddl)

    # Insert test data in source only
    with source_db.cursor() as cur:
        cur.execute("""
            INSERT INTO users (username, email)
            SELECT 'user_' || i, 'user' || i || '@test.com'
            FROM generate_series(1, 1000) i
        """)
        cur.execute("""
            INSERT INTO posts (user_id, title, content)
            SELECT (i % 1000) + 1, 'Post ' || i, 'Content ' || i
            FROM generate_series(1, 5000) i
        """)
        cur.execute("""
            INSERT INTO comments (post_id, content)
            SELECT (i % 5000) + 1, 'Comment ' || i
            FROM generate_series(1, 15000) i
        """)

    yield source_db


@pytest.mark.asyncio
async def test_progress_reporting_single_table(
    source_config,
    target_config,
    populated_source_db,
):
    """Test progress reporting for single table sync."""
    # Create syncer with progress tracking enabled
    config = SyncConfig(
        tables=TableSelection(include=["users"]),
        show_progress=True,
    )

    with patch("confiture.core.syncer.Progress") as mock_progress:
        # Setup mock progress bar
        mock_progress_instance = MagicMock()
        mock_task = MagicMock()
        mock_progress.return_value.__enter__.return_value = mock_progress_instance
        mock_progress_instance.add_task.return_value = mock_task

        with ProductionSyncer(source_config, target_config) as syncer:
            results = syncer.sync(config)

        # Verify progress bar was created
        mock_progress_instance.add_task.assert_called_once()
        call_args = mock_progress_instance.add_task.call_args
        assert "users" in call_args[0][0]  # Task description includes table name

        # Verify progress was updated (should have total set)
        assert mock_progress_instance.update.called
        # Find the update call that set the total
        update_calls = [call for call in mock_progress_instance.update.call_args_list
                       if 'total' in call[1]]
        assert len(update_calls) > 0
        assert update_calls[0][1]['total'] == 1000

        assert results["users"] == 1000


@pytest.mark.asyncio
async def test_progress_metrics_calculation(
    source_config,
    target_config,
    populated_source_db,
):
    """Test that performance metrics are calculated correctly."""
    config = SyncConfig(
        tables=TableSelection(include=["users"]),
        show_progress=True,
    )

    with ProductionSyncer(source_config, target_config) as syncer:
        start_time = time.time()
        results = syncer.sync(config)
        elapsed = time.time() - start_time

        # Get metrics
        metrics = syncer.get_metrics()

        assert "users" in metrics
        user_metrics = metrics["users"]

        # Verify metrics structure
        assert "rows_synced" in user_metrics
        assert "elapsed_seconds" in user_metrics
        assert "rows_per_second" in user_metrics

        # Verify calculations
        assert user_metrics["rows_synced"] == 1000
        assert user_metrics["elapsed_seconds"] > 0
        assert user_metrics["rows_per_second"] > 0
        assert user_metrics["rows_per_second"] == pytest.approx(
            1000 / user_metrics["elapsed_seconds"], rel=0.1
        )


@pytest.mark.asyncio
async def test_resume_from_checkpoint(
    source_config,
    target_config,
    populated_source_db,
    tmp_path: Path,
):
    """Test resuming sync from checkpoint after interruption."""
    checkpoint_file = tmp_path / "sync_checkpoint.json"

    config = SyncConfig(
        tables=TableSelection(include=["users", "posts"]),
        checkpoint_file=checkpoint_file,
    )

    # First sync - complete users, interrupt before posts
    with ProductionSyncer(source_config, target_config) as syncer:
        # Sync users successfully
        syncer.sync_table("users")

        # Save checkpoint
        syncer.save_checkpoint(checkpoint_file)

    # Verify checkpoint file exists
    assert checkpoint_file.exists()

    # Second sync - should resume from checkpoint (enable resume in config)
    config_with_resume = SyncConfig(
        tables=TableSelection(include=["users", "posts"]),
        checkpoint_file=checkpoint_file,
        resume=True,
    )

    with ProductionSyncer(source_config, target_config) as syncer:
        # Sync with resume enabled - should skip users and only sync posts
        results = syncer.sync(config_with_resume)

        # Verify users was skipped (not in results)
        assert "users" not in results

        # Verify posts was synced
        assert "posts" in results
        assert results["posts"] == 5000


@pytest.mark.asyncio
async def test_checkpoint_structure(
    source_config,
    target_config,
    populated_source_db,
    tmp_path: Path,
):
    """Test checkpoint file structure and content."""
    checkpoint_file = tmp_path / "sync_checkpoint.json"

    with ProductionSyncer(source_config, target_config) as syncer:
        syncer.sync_table("users")
        syncer.save_checkpoint(checkpoint_file)

    # Read and verify checkpoint content
    import json

    with open(checkpoint_file) as f:
        checkpoint = json.load(f)

    # Verify structure
    assert "version" in checkpoint
    assert "timestamp" in checkpoint
    assert "completed_tables" in checkpoint
    assert "source_database" in checkpoint
    assert "target_database" in checkpoint

    # Verify content
    assert checkpoint["version"] == "1.0"
    assert "users" in checkpoint["completed_tables"]
    assert checkpoint["completed_tables"]["users"]["rows_synced"] == 1000
    assert "synced_at" in checkpoint["completed_tables"]["users"]


@pytest.mark.asyncio
async def test_incremental_sync_large_table(
    source_config,
    target_config,
    source_db,
    target_db,
    tmp_path: Path,
):
    """Test incremental sync with progress for large table."""
    # Create large table in both databases
    table_ddl = """
        CREATE TABLE IF NOT EXISTS large_table (
            id SERIAL PRIMARY KEY,
            data TEXT
        )
    """

    with source_db.cursor() as cur:
        cur.execute(table_ddl)
        # Insert 10,000 rows
        cur.execute("""
            INSERT INTO large_table (data)
            SELECT 'data_' || generate_series(1, 10000)
        """)

    with target_db.cursor() as cur:
        cur.execute(table_ddl)

    checkpoint_file = tmp_path / "large_sync_checkpoint.json"

    config = SyncConfig(
        tables=TableSelection(include=["large_table"]),
        checkpoint_file=checkpoint_file,
        show_progress=True,
    )

    with ProductionSyncer(source_config, target_config) as syncer:
        results = syncer.sync(config)

        # Verify all rows synced
        assert results["large_table"] == 10000

        # Verify checkpoint was saved
        assert checkpoint_file.exists()

        # Verify metrics
        metrics = syncer.get_metrics()
        assert "large_table" in metrics
        assert metrics["large_table"]["rows_synced"] == 10000
        assert metrics["large_table"]["rows_per_second"] > 0


@pytest.mark.asyncio
async def test_resume_skips_completed_tables(
    source_config,
    target_config,
    populated_source_db,
    tmp_path: Path,
):
    """Test that resume correctly skips already completed tables."""
    checkpoint_file = tmp_path / "resume_checkpoint.json"

    # First sync - complete users and posts
    with ProductionSyncer(source_config, target_config) as syncer:
        syncer.sync_table("users")
        syncer.sync_table("posts")
        syncer.save_checkpoint(checkpoint_file)

    # Second sync - should skip users and posts (using resume)
    config = SyncConfig(
        tables=TableSelection(include=["users", "posts", "comments"]),
        checkpoint_file=checkpoint_file,
        resume=True,  # Enable resume
    )

    with ProductionSyncer(source_config, target_config) as syncer:
        results = syncer.sync(config)

        # Verify only comments was synced (users and posts skipped)
        assert "comments" in results
        assert "users" not in results
        assert "posts" not in results


@pytest.mark.asyncio
async def test_progress_multiple_tables(
    source_config,
    target_config,
    populated_source_db,
):
    """Test progress reporting for multiple tables."""
    config = SyncConfig(
        tables=TableSelection(include=["users", "posts", "comments"]),
        show_progress=True,
    )

    with patch("confiture.core.syncer.Progress") as mock_progress:
        mock_progress_instance = MagicMock()
        mock_progress.return_value.__enter__.return_value = mock_progress_instance

        # Track task IDs for each table
        task_ids = {}
        mock_progress_instance.add_task.side_effect = (
            lambda desc, **kwargs: len(task_ids)
        )

        with ProductionSyncer(source_config, target_config) as syncer:
            results = syncer.sync(config)

        # Verify progress bars were created for all tables
        assert mock_progress_instance.add_task.call_count == 3

        # Verify all tables synced
        assert results["users"] == 1000
        assert results["posts"] == 5000
        assert results["comments"] == 15000
