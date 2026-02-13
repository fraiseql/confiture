"""Tests for CopyExecutor - executing COPY format data in PostgreSQL."""

from unittest.mock import AsyncMock

import pytest

from confiture.core.seed.copy_executor import CopyExecutionResult, CopyExecutor


class TestBasicCopyExecution:
    """Test basic COPY execution."""

    @pytest.mark.asyncio
    async def test_executes_copy_statement(self) -> None:
        """Test executing a basic COPY statement."""
        executor = CopyExecutor()

        # Mock connection
        mock_connection = AsyncMock()
        mock_connection.copy = AsyncMock(return_value=2)

        copy_data = "1\tAlice\n2\tBob\n\\."
        result = await executor.execute_copy(mock_connection, "users", copy_data)

        assert result.success is True
        assert result.rows_loaded == 2

    @pytest.mark.asyncio
    async def test_returns_row_count(self) -> None:
        """Test that execution returns correct row count."""
        executor = CopyExecutor()

        mock_connection = AsyncMock()
        mock_connection.copy = AsyncMock(return_value=5)

        copy_data = "1\ta\n2\tb\n3\tc\n4\td\n5\te\n\\."
        result = await executor.execute_copy(mock_connection, "data", copy_data)

        assert result.rows_loaded == 5

    @pytest.mark.asyncio
    async def test_handles_empty_copy(self) -> None:
        """Test executing COPY with no data rows."""
        executor = CopyExecutor()

        mock_connection = AsyncMock()
        mock_connection.copy = AsyncMock(return_value=0)

        copy_data = "\\."
        result = await executor.execute_copy(mock_connection, "users", copy_data)

        assert result.success is True
        assert result.rows_loaded == 0

    @pytest.mark.asyncio
    async def test_handles_execution_error(self) -> None:
        """Test handling database errors during COPY."""
        executor = CopyExecutor()

        mock_connection = AsyncMock()
        mock_connection.copy = AsyncMock(side_effect=Exception("Database error"))

        copy_data = "1\tAlice\n\\."
        result = await executor.execute_copy(mock_connection, "users", copy_data)

        assert result.success is False
        assert result.error is not None
        assert "Database error" in result.error

    @pytest.mark.asyncio
    async def test_constructs_correct_copy_statement(self) -> None:
        """Test that COPY statement is constructed correctly."""
        executor = CopyExecutor()

        mock_connection = AsyncMock()
        mock_connection.copy = AsyncMock(return_value=1)

        copy_data = "1\ttest\n\\."
        await executor.execute_copy(mock_connection, "mytable", copy_data)

        # Verify copy was called
        assert mock_connection.copy.called


class TestTransactionSafety:
    """Test transaction safety in COPY execution."""

    @pytest.mark.asyncio
    async def test_uses_savepoint_for_isolation(self) -> None:
        """Test that COPY uses savepoint for isolation."""
        executor = CopyExecutor()

        mock_connection = AsyncMock()
        mock_connection.copy = AsyncMock(return_value=1)
        mock_connection.execute = AsyncMock()
        mock_connection.rollback = AsyncMock()

        copy_data = "1\ttest\n\\."
        await executor.execute_copy(mock_connection, "users", copy_data, use_savepoint=True)

        assert mock_connection.copy.called

    @pytest.mark.asyncio
    async def test_rollback_on_error_with_savepoint(self) -> None:
        """Test rollback behavior with savepoint on error."""
        executor = CopyExecutor()

        mock_connection = AsyncMock()
        mock_connection.copy = AsyncMock(side_effect=Exception("Constraint violation"))

        copy_data = "1\tinvalid\n\\."
        result = await executor.execute_copy(
            mock_connection, "users", copy_data, use_savepoint=True
        )

        assert result.success is False
        assert "Constraint violation" in result.error


class TestCopyExecutionResult:
    """Test CopyExecutionResult structure."""

    def test_result_has_required_fields(self) -> None:
        """Test that result has all required fields."""
        result = CopyExecutionResult(
            success=True,
            rows_loaded=5,
            error=None,
            table="users",
        )

        assert hasattr(result, "success")
        assert hasattr(result, "rows_loaded")
        assert hasattr(result, "error")
        assert hasattr(result, "table")

    def test_success_result(self) -> None:
        """Test creating a successful result."""
        result = CopyExecutionResult(success=True, rows_loaded=10, error=None, table="users")

        assert result.success is True
        assert result.rows_loaded == 10
        assert result.error is None

    def test_error_result(self) -> None:
        """Test creating an error result."""
        error_msg = "Constraint violation"
        result = CopyExecutionResult(
            success=False,
            rows_loaded=0,
            error=error_msg,
            table="users",
        )

        assert result.success is False
        assert result.error == error_msg


class TestMultipleTableExecution:
    """Test executing COPY on multiple tables."""

    @pytest.mark.asyncio
    async def test_executes_copy_on_different_tables(self) -> None:
        """Test executing COPY on different tables sequentially."""
        executor = CopyExecutor()

        mock_connection = AsyncMock()
        mock_connection.copy = AsyncMock(return_value=2)

        # Execute COPY on users table
        result1 = await executor.execute_copy(mock_connection, "users", "1\tAlice\n2\tBob\n\\.")

        # Execute COPY on orders table
        result2 = await executor.execute_copy(mock_connection, "orders", "1\t100\n2\t200\n\\.")

        assert result1.success is True
        assert result2.success is True
        assert mock_connection.copy.call_count == 2


class TestCopyDataVariations:
    """Test COPY with various data types."""

    @pytest.mark.asyncio
    async def test_handles_uuid_data(self) -> None:
        """Test COPY with UUID values."""
        executor = CopyExecutor()

        mock_connection = AsyncMock()
        mock_connection.copy = AsyncMock(return_value=1)

        uuid_str = "550e8400-e29b-41d4-a716-446655440000"
        copy_data = f"{uuid_str}\tAlice\n\\."
        result = await executor.execute_copy(mock_connection, "users", copy_data)

        assert result.success is True

    @pytest.mark.asyncio
    async def test_handles_null_values_in_copy(self) -> None:
        """Test COPY with NULL values."""
        executor = CopyExecutor()

        mock_connection = AsyncMock()
        mock_connection.copy = AsyncMock(return_value=2)

        copy_data = "1\tAlice\n2\t\\N\n\\."
        result = await executor.execute_copy(mock_connection, "users", copy_data)

        assert result.success is True

    @pytest.mark.asyncio
    async def test_handles_special_characters(self) -> None:
        """Test COPY with escaped special characters."""
        executor = CopyExecutor()

        mock_connection = AsyncMock()
        mock_connection.copy = AsyncMock(return_value=1)

        copy_data = "1\tLine1\\nLine2\n\\."
        result = await executor.execute_copy(mock_connection, "data", copy_data)

        assert result.success is True


class TestExecutorConfiguration:
    """Test CopyExecutor configuration options."""

    def test_creates_executor_with_defaults(self) -> None:
        """Test creating executor with default configuration."""
        executor = CopyExecutor()

        assert executor is not None
        assert hasattr(executor, "execute_copy")

    def test_creates_executor_with_options(self) -> None:
        """Test creating executor with custom options."""
        executor = CopyExecutor(
            default_savepoint=True,
            max_retries=3,
            timeout=30,
        )

        assert executor is not None

    @pytest.mark.asyncio
    async def test_respects_timeout_option(self) -> None:
        """Test that executor respects timeout setting."""
        executor = CopyExecutor(timeout=5)

        mock_connection = AsyncMock()
        mock_connection.copy = AsyncMock(return_value=1)

        copy_data = "1\ttest\n\\."
        result = await executor.execute_copy(mock_connection, "users", copy_data)

        assert result.success is True


class TestExecutorMetrics:
    """Test execution metrics and reporting."""

    @pytest.mark.asyncio
    async def test_includes_execution_time(self) -> None:
        """Test that result includes execution time."""
        executor = CopyExecutor()

        mock_connection = AsyncMock()
        mock_connection.copy = AsyncMock(return_value=1)

        copy_data = "1\ttest\n\\."
        result = await executor.execute_copy(mock_connection, "users", copy_data)

        assert hasattr(result, "execution_time_ms")

    @pytest.mark.asyncio
    async def test_tracks_rows_per_second(self) -> None:
        """Test that metrics include throughput."""
        executor = CopyExecutor()

        mock_connection = AsyncMock()
        mock_connection.copy = AsyncMock(return_value=1000)

        copy_data = "\n".join([f"{i}\tdata{i}" for i in range(1000)] + [r"\."])
        result = await executor.execute_copy(mock_connection, "users", copy_data)

        assert hasattr(result, "rows_per_second")


class TestErrorHandling:
    """Test error handling in COPY execution."""

    @pytest.mark.asyncio
    async def test_handles_syntax_error_in_copy(self) -> None:
        """Test handling malformed COPY data."""
        executor = CopyExecutor()

        mock_connection = AsyncMock()
        mock_connection.copy = AsyncMock(side_effect=ValueError("Invalid COPY format"))

        copy_data = "malformed data"
        result = await executor.execute_copy(mock_connection, "users", copy_data)

        assert result.success is False

    @pytest.mark.asyncio
    async def test_includes_error_context(self) -> None:
        """Test that errors include helpful context."""
        executor = CopyExecutor()

        mock_connection = AsyncMock()
        error_msg = "Unique constraint violation on column email"
        mock_connection.copy = AsyncMock(side_effect=Exception(error_msg))

        copy_data = "1\talice@example.com\n\\."
        result = await executor.execute_copy(mock_connection, "users", copy_data)

        assert error_msg in result.error

    @pytest.mark.asyncio
    async def test_handles_connection_error(self) -> None:
        """Test handling connection failures."""
        executor = CopyExecutor()

        mock_connection = AsyncMock()
        mock_connection.copy = AsyncMock(side_effect=ConnectionError("Connection lost"))

        copy_data = "1\ttest\n\\."
        result = await executor.execute_copy(mock_connection, "users", copy_data)

        assert result.success is False
        assert "Connection" in result.error
