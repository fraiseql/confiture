"""Tests for large table migration patterns."""

from unittest.mock import MagicMock, Mock, patch

import pytest

from confiture.core.large_tables import (
    BatchConfig,
    BatchedMigration,
    BatchProgress,
    OnlineIndexBuilder,
    TableSizeEstimator,
)


class TestBatchConfig:
    """Tests for BatchConfig dataclass."""

    def test_default_config(self):
        """Test default configuration values."""
        config = BatchConfig()
        assert config.batch_size == 10000
        assert config.sleep_between_batches == 0.1
        assert config.max_retries == 3
        assert config.progress_callback is None
        assert config.checkpoint_callback is None

    def test_custom_config(self):
        """Test custom configuration."""
        callback = Mock()
        config = BatchConfig(
            batch_size=5000,
            sleep_between_batches=0.5,
            max_retries=5,
            progress_callback=callback,
        )
        assert config.batch_size == 5000
        assert config.progress_callback is callback


class TestBatchProgress:
    """Tests for BatchProgress dataclass."""

    def test_progress_creation(self):
        """Test creating progress object."""
        progress = BatchProgress(total_rows=1000, processed_rows=500)
        assert progress.total_rows == 1000
        assert progress.processed_rows == 500

    def test_percent_complete(self):
        """Test percent complete calculation."""
        progress = BatchProgress(total_rows=1000, processed_rows=250)
        assert progress.percent_complete == 25.0

    def test_percent_complete_zero_total(self):
        """Test percent complete with zero total rows."""
        progress = BatchProgress(total_rows=0)
        assert progress.percent_complete == 100.0

    def test_is_complete(self):
        """Test is_complete property."""
        progress = BatchProgress(total_rows=1000, processed_rows=500)
        assert progress.is_complete is False

        progress.processed_rows = 1000
        assert progress.is_complete is True

    def test_rows_per_second(self):
        """Test rows per second calculation."""
        progress = BatchProgress(total_rows=1000, processed_rows=500, elapsed_seconds=10.0)
        assert progress.rows_per_second == 50.0

    def test_rows_per_second_zero_elapsed(self):
        """Test rows per second with zero elapsed time."""
        progress = BatchProgress(total_rows=1000, processed_rows=500, elapsed_seconds=0)
        assert progress.rows_per_second == 0.0

    def test_estimated_remaining_seconds(self):
        """Test estimated remaining time."""
        progress = BatchProgress(total_rows=1000, processed_rows=500, elapsed_seconds=10.0)
        # 500 rows in 10 seconds = 50 rows/sec
        # 500 remaining / 50 rows/sec = 10 seconds
        assert progress.estimated_remaining_seconds == 10.0

    def test_to_dict(self):
        """Test converting to dictionary."""
        progress = BatchProgress(
            total_rows=1000,
            processed_rows=500,
            current_batch=5,
            total_batches=10,
            elapsed_seconds=10.0,
        )
        result = progress.to_dict()

        assert result["total_rows"] == 1000
        assert result["processed_rows"] == 500
        assert result["percent_complete"] == 50.0
        assert result["current_batch"] == 5
        assert result["total_batches"] == 10
        assert "rows_per_second" in result
        assert "estimated_remaining_seconds" in result


class TestBatchedMigration:
    """Tests for BatchedMigration class."""

    @pytest.fixture
    def mock_connection(self):
        """Create mock connection."""
        conn = Mock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = Mock(return_value=cursor)
        conn.cursor.return_value.__exit__ = Mock(return_value=False)
        return conn, cursor

    def test_add_column_with_default_empty_table(self, mock_connection):
        """Test adding column to empty table."""
        conn, cursor = mock_connection
        cursor.fetchone.return_value = (0,)  # No rows

        config = BatchConfig(batch_size=100, sleep_between_batches=0)
        batched = BatchedMigration(conn, config)

        progress = batched.add_column_with_default(
            table="users",
            column="status",
            column_type="TEXT",
            default="'active'",
        )

        assert progress.total_rows == 0
        assert progress.is_complete

    def test_add_column_with_default_small_table(self, mock_connection):
        """Test adding column to small table."""
        conn, cursor = mock_connection
        cursor.fetchone.return_value = (50,)  # 50 rows
        cursor.rowcount = 50  # All updated in one batch

        config = BatchConfig(batch_size=100, sleep_between_batches=0)
        batched = BatchedMigration(conn, config)

        progress = batched.add_column_with_default(
            table="users",
            column="status",
            column_type="TEXT",
            default="'active'",
        )

        assert progress.total_rows == 50
        assert progress.processed_rows == 50
        assert conn.commit.called

    def test_add_column_progress_callback(self, mock_connection):
        """Test progress callback is called."""
        conn, cursor = mock_connection
        cursor.fetchone.return_value = (100,)
        cursor.rowcount = 50  # Two batches

        callback_calls = []

        def callback(processed, total):
            callback_calls.append((processed, total))

        config = BatchConfig(batch_size=50, sleep_between_batches=0, progress_callback=callback)
        batched = BatchedMigration(conn, config)

        # Set up rowcount to return 50 first, then 0
        cursor.rowcount = 50

        with patch.object(cursor, "rowcount", new_callable=lambda: Mock()):
            cursor.rowcount = 50
            batched.add_column_with_default(
                table="users", column="status", column_type="TEXT", default="'active'"
            )

        assert len(callback_calls) >= 1

    def test_add_column_checkpoint_callback(self, mock_connection):
        """Test checkpoint callback is called."""
        conn, cursor = mock_connection
        cursor.fetchone.return_value = (50,)
        cursor.rowcount = 50

        checkpoint_calls = []

        def checkpoint(processed):
            checkpoint_calls.append(processed)

        config = BatchConfig(
            batch_size=100, sleep_between_batches=0, checkpoint_callback=checkpoint
        )
        batched = BatchedMigration(conn, config)

        batched.add_column_with_default(
            table="users", column="status", column_type="TEXT", default="'active'"
        )

        assert len(checkpoint_calls) >= 1

    def test_backfill_column_empty(self, mock_connection):
        """Test backfilling empty result set."""
        conn, cursor = mock_connection
        cursor.fetchone.return_value = (0,)

        config = BatchConfig(batch_size=100, sleep_between_batches=0)
        batched = BatchedMigration(conn, config)

        progress = batched.backfill_column(
            table="orders",
            column="total_cents",
            expression="(subtotal + tax) * 100",
            where_clause="total_cents IS NULL",
        )

        assert progress.total_rows == 0

    def test_backfill_column_with_data(self, mock_connection):
        """Test backfilling with data."""
        conn, cursor = mock_connection
        cursor.fetchone.return_value = (100,)

        # First call returns 100 rows, second returns 0
        rowcount_values = [100, 0]
        rowcount_index = [0]

        def get_rowcount():
            idx = rowcount_index[0]
            rowcount_index[0] += 1
            return rowcount_values[idx] if idx < len(rowcount_values) else 0

        type(cursor).rowcount = property(lambda self: get_rowcount())

        config = BatchConfig(batch_size=100, sleep_between_batches=0)
        batched = BatchedMigration(conn, config)

        progress = batched.backfill_column(
            table="orders",
            column="total_cents",
            expression="(subtotal + tax) * 100",
        )

        assert progress.total_rows == 100

    def test_delete_in_batches_empty(self, mock_connection):
        """Test deleting from empty result set."""
        conn, cursor = mock_connection
        cursor.fetchone.return_value = (0,)

        config = BatchConfig(batch_size=100, sleep_between_batches=0)
        batched = BatchedMigration(conn, config)

        progress = batched.delete_in_batches(
            table="audit_logs",
            where_clause="created_at < NOW() - INTERVAL '1 year'",
        )

        assert progress.total_rows == 0

    def test_delete_in_batches_with_data(self, mock_connection):
        """Test deleting with data."""
        conn, cursor = mock_connection
        cursor.fetchone.return_value = (50,)

        # Track rowcount values
        rowcount_values = [50, 0]
        rowcount_index = [0]

        def get_rowcount():
            idx = rowcount_index[0]
            rowcount_index[0] += 1
            return rowcount_values[idx] if idx < len(rowcount_values) else 0

        type(cursor).rowcount = property(lambda self: get_rowcount())

        config = BatchConfig(batch_size=100, sleep_between_batches=0)
        batched = BatchedMigration(conn, config)

        progress = batched.delete_in_batches(
            table="audit_logs",
            where_clause="created_at < NOW() - INTERVAL '1 year'",
        )

        assert progress.total_rows == 50


class TestOnlineIndexBuilder:
    """Tests for OnlineIndexBuilder class."""

    @pytest.fixture
    def mock_connection(self):
        """Create mock connection."""
        conn = Mock()
        conn.autocommit = False
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = Mock(return_value=cursor)
        conn.cursor.return_value.__exit__ = Mock(return_value=False)
        return conn, cursor

    def test_create_index_concurrently(self, mock_connection):
        """Test creating index concurrently."""
        conn, cursor = mock_connection
        builder = OnlineIndexBuilder(conn)

        index_name = builder.create_index_concurrently(table="users", columns=["email"])

        assert index_name == "idx_users_email"
        cursor.execute.assert_called()
        # Should have set autocommit
        assert conn.autocommit is False  # Restored

    def test_create_index_custom_name(self, mock_connection):
        """Test creating index with custom name."""
        conn, cursor = mock_connection
        builder = OnlineIndexBuilder(conn)

        index_name = builder.create_index_concurrently(
            table="users", columns=["email"], index_name="custom_idx"
        )

        assert index_name == "custom_idx"

    def test_create_unique_index(self, mock_connection):
        """Test creating unique index."""
        conn, cursor = mock_connection
        builder = OnlineIndexBuilder(conn)

        builder.create_index_concurrently(table="users", columns=["email"], unique=True)

        call_args = str(cursor.execute.call_args)
        assert "UNIQUE" in call_args

    def test_create_partial_index(self, mock_connection):
        """Test creating partial index."""
        conn, cursor = mock_connection
        builder = OnlineIndexBuilder(conn)

        builder.create_index_concurrently(table="users", columns=["email"], where="active = true")

        call_args = str(cursor.execute.call_args)
        assert "WHERE active = true" in call_args

    def test_create_index_with_include(self, mock_connection):
        """Test creating covering index."""
        conn, cursor = mock_connection
        builder = OnlineIndexBuilder(conn)

        builder.create_index_concurrently(table="users", columns=["id"], include=["email", "name"])

        call_args = str(cursor.execute.call_args)
        assert "INCLUDE" in call_args

    def test_create_index_custom_method(self, mock_connection):
        """Test creating index with custom method."""
        conn, cursor = mock_connection
        builder = OnlineIndexBuilder(conn)

        builder.create_index_concurrently(table="documents", columns=["content"], method="gin")

        call_args = str(cursor.execute.call_args)
        assert "USING gin" in call_args

    def test_drop_index_concurrently(self, mock_connection):
        """Test dropping index concurrently."""
        conn, cursor = mock_connection
        builder = OnlineIndexBuilder(conn)

        builder.drop_index_concurrently("idx_users_email")

        call_args = str(cursor.execute.call_args)
        assert "DROP INDEX CONCURRENTLY" in call_args
        assert "idx_users_email" in call_args

    def test_reindex_concurrently(self, mock_connection):
        """Test reindexing concurrently."""
        conn, cursor = mock_connection
        builder = OnlineIndexBuilder(conn)

        builder.reindex_concurrently("idx_users_email")

        call_args = str(cursor.execute.call_args)
        assert "REINDEX INDEX CONCURRENTLY" in call_args

    def test_check_index_validity_valid(self, mock_connection):
        """Test checking valid index."""
        conn, cursor = mock_connection
        cursor.fetchone.return_value = (True,)
        builder = OnlineIndexBuilder(conn)

        is_valid = builder.check_index_validity("idx_users_email")

        assert is_valid is True

    def test_check_index_validity_invalid(self, mock_connection):
        """Test checking invalid index."""
        conn, cursor = mock_connection
        cursor.fetchone.return_value = (False,)
        builder = OnlineIndexBuilder(conn)

        is_valid = builder.check_index_validity("idx_users_email")

        assert is_valid is False

    def test_check_index_validity_not_found(self, mock_connection):
        """Test checking non-existent index."""
        conn, cursor = mock_connection
        cursor.fetchone.return_value = None
        builder = OnlineIndexBuilder(conn)

        is_valid = builder.check_index_validity("nonexistent_idx")

        assert is_valid is False

    def test_get_index_size(self, mock_connection):
        """Test getting index size."""
        conn, cursor = mock_connection
        cursor.fetchone.return_value = (1048576,)  # 1 MB
        builder = OnlineIndexBuilder(conn)

        size = builder.get_index_size("idx_users_email")

        assert size == 1048576

    def test_get_index_size_not_found(self, mock_connection):
        """Test getting size of non-existent index."""
        conn, cursor = mock_connection
        cursor.fetchone.return_value = None
        builder = OnlineIndexBuilder(conn)

        size = builder.get_index_size("nonexistent_idx")

        assert size == 0


class TestTableSizeEstimator:
    """Tests for TableSizeEstimator class."""

    @pytest.fixture
    def mock_connection(self):
        """Create mock connection."""
        conn = Mock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = Mock(return_value=cursor)
        conn.cursor.return_value.__exit__ = Mock(return_value=False)
        return conn, cursor

    def test_get_row_count_estimate(self, mock_connection):
        """Test getting estimated row count."""
        conn, cursor = mock_connection
        cursor.fetchone.return_value = (1000000,)
        estimator = TableSizeEstimator(conn)

        count = estimator.get_row_count_estimate("users")

        assert count == 1000000

    def test_get_row_count_estimate_negative(self, mock_connection):
        """Test estimated row count handles negative values."""
        conn, cursor = mock_connection
        cursor.fetchone.return_value = (-1,)  # Can happen with fresh tables
        estimator = TableSizeEstimator(conn)

        count = estimator.get_row_count_estimate("users")

        assert count == 0

    def test_get_row_count_estimate_not_found(self, mock_connection):
        """Test estimated row count for non-existent table."""
        conn, cursor = mock_connection
        cursor.fetchone.return_value = None
        estimator = TableSizeEstimator(conn)

        count = estimator.get_row_count_estimate("nonexistent")

        assert count == 0

    def test_get_exact_row_count(self, mock_connection):
        """Test getting exact row count."""
        conn, cursor = mock_connection
        cursor.fetchone.return_value = (12345,)
        estimator = TableSizeEstimator(conn)

        count = estimator.get_exact_row_count("users")

        assert count == 12345

    def test_get_exact_row_count_with_where(self, mock_connection):
        """Test getting exact row count with filter."""
        conn, cursor = mock_connection
        cursor.fetchone.return_value = (100,)
        estimator = TableSizeEstimator(conn)

        count = estimator.get_exact_row_count("users", "active = true")

        assert count == 100

    def test_get_table_size(self, mock_connection):
        """Test getting table size information."""
        conn, cursor = mock_connection
        cursor.fetchone.return_value = (
            1048576,  # table size (1 MB)
            524288,  # index size (512 KB)
            1572864,  # total size (1.5 MB)
        )
        estimator = TableSizeEstimator(conn)

        sizes = estimator.get_table_size("users")

        assert sizes["table_size_bytes"] == 1048576
        assert sizes["index_size_bytes"] == 524288
        assert sizes["total_size_bytes"] == 1572864

    def test_should_use_batched_operation_large(self, mock_connection):
        """Test large table detection."""
        conn, cursor = mock_connection
        cursor.fetchone.return_value = (500000,)
        estimator = TableSizeEstimator(conn)

        should_batch = estimator.should_use_batched_operation("users")

        assert should_batch is True

    def test_should_use_batched_operation_small(self, mock_connection):
        """Test small table detection."""
        conn, cursor = mock_connection
        cursor.fetchone.return_value = (1000,)
        estimator = TableSizeEstimator(conn)

        should_batch = estimator.should_use_batched_operation("users")

        assert should_batch is False

    def test_estimate_operation_time(self, mock_connection):
        """Test operation time estimation."""
        conn, cursor = mock_connection
        cursor.fetchone.return_value = (100000,)  # 100k rows
        estimator = TableSizeEstimator(conn)

        # At 10k rows/sec, 100k rows should take 10 seconds
        estimate = estimator.estimate_operation_time("users", rows_per_second=10000)

        assert estimate == 10.0

    def test_estimate_operation_time_zero_rate(self, mock_connection):
        """Test operation time with zero rate."""
        conn, cursor = mock_connection
        cursor.fetchone.return_value = (100000,)
        estimator = TableSizeEstimator(conn)

        estimate = estimator.estimate_operation_time("users", rows_per_second=0)

        assert estimate == 0.0
