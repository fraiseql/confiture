"""Tests for SeedBatchBuilder - intelligently choose VALUES vs COPY format."""

from confiture.core.seed.seed_batch_builder import SeedBatchBuilder


class TestBasicBatchBuilding:
    """Test basic batch building and format selection."""

    def test_selects_copy_for_large_datasets(self) -> None:
        """Test that COPY format is selected for large datasets."""
        builder = SeedBatchBuilder()
        seed_data = {"users": [{"id": str(i), "name": f"User {i}"} for i in range(1500)]}

        batches = builder.build_batches(seed_data, copy_threshold=1000)

        assert len(batches) == 1
        assert batches[0].format == "COPY"
        assert batches[0].table == "users"
        assert batches[0].rows_count == 1500

    def test_selects_values_for_small_datasets(self) -> None:
        """Test that VALUES format is selected for small datasets."""
        builder = SeedBatchBuilder()
        seed_data = {"users": [{"id": str(i), "name": f"User {i}"} for i in range(100)]}

        batches = builder.build_batches(seed_data, copy_threshold=1000)

        assert len(batches) == 1
        assert batches[0].format == "VALUES"
        assert batches[0].table == "users"
        assert batches[0].rows_count == 100

    def test_respects_configurable_threshold(self) -> None:
        """Test that threshold is configurable."""
        builder = SeedBatchBuilder()
        seed_data = {"users": [{"id": str(i), "name": f"User {i}"} for i in range(500)]}

        # With threshold of 1000, should use VALUES
        batches = builder.build_batches(seed_data, copy_threshold=1000)
        assert batches[0].format == "VALUES"

        # With threshold of 200, should use COPY
        batches = builder.build_batches(seed_data, copy_threshold=200)
        assert batches[0].format == "COPY"

    def test_builds_multiple_table_batches(self) -> None:
        """Test batching multiple tables with mixed formats."""
        builder = SeedBatchBuilder()
        seed_data = {
            "users": [{"id": str(i)} for i in range(1500)],  # Large -> COPY
            "roles": [{"id": str(i)} for i in range(10)],  # Small -> VALUES
            "permissions": [{"id": str(i)} for i in range(2000)],  # Large -> COPY
        }

        batches = builder.build_batches(seed_data, copy_threshold=1000)

        assert len(batches) == 3

        # Find batches by table
        users_batch = next(b for b in batches if b.table == "users")
        roles_batch = next(b for b in batches if b.table == "roles")
        perms_batch = next(b for b in batches if b.table == "permissions")

        assert users_batch.format == "COPY"
        assert roles_batch.format == "VALUES"
        assert perms_batch.format == "COPY"


class TestBoundaryConditions:
    """Test boundary conditions for format selection."""

    def test_exact_threshold_uses_values(self) -> None:
        """Test that exact threshold uses VALUES (not COPY)."""
        builder = SeedBatchBuilder()
        seed_data = {
            "users": [{"id": str(i)} for i in range(1000)]  # Exactly at threshold
        }

        batches = builder.build_batches(seed_data, copy_threshold=1000)

        assert batches[0].format == "VALUES"

    def test_just_above_threshold_uses_copy(self) -> None:
        """Test that just above threshold uses COPY."""
        builder = SeedBatchBuilder()
        seed_data = {
            "users": [{"id": str(i)} for i in range(1001)]  # Just above threshold
        }

        batches = builder.build_batches(seed_data, copy_threshold=1000)

        assert batches[0].format == "COPY"

    def test_empty_table_uses_values(self) -> None:
        """Test that empty tables use VALUES format."""
        builder = SeedBatchBuilder()
        seed_data = {"users": []}

        batches = builder.build_batches(seed_data, copy_threshold=1000)

        assert len(batches) == 1
        assert batches[0].format == "VALUES"
        assert batches[0].rows_count == 0


class TestBatchDataPreservation:
    """Test that batch data is preserved correctly."""

    def test_preserves_row_data_in_copy_batch(self) -> None:
        """Test that row data is preserved in COPY batch."""
        builder = SeedBatchBuilder()
        rows = [
            {"id": "1", "name": "Alice"},
            {"id": "2", "name": "Bob"},
        ]
        seed_data = {"users": rows}

        batches = builder.build_batches(seed_data, copy_threshold=1)

        assert batches[0].rows == rows

    def test_preserves_row_data_in_values_batch(self) -> None:
        """Test that row data is preserved in VALUES batch."""
        builder = SeedBatchBuilder()
        rows = [
            {"id": "1", "name": "Alice"},
            {"id": "2", "name": "Bob"},
        ]
        seed_data = {"users": rows}

        batches = builder.build_batches(seed_data, copy_threshold=1000)

        assert batches[0].rows == rows

    def test_preserves_column_order(self) -> None:
        """Test that column order from rows is preserved."""
        builder = SeedBatchBuilder()
        rows = [
            {"id": "1", "name": "Alice", "email": "alice@example.com"},
            {"id": "2", "name": "Bob", "email": "bob@example.com"},
        ]
        seed_data = {"users": rows}

        batches = builder.build_batches(seed_data, copy_threshold=1)

        assert list(batches[0].rows[0].keys()) == ["id", "name", "email"]


class TestBatchMetadata:
    """Test batch metadata and metrics."""

    def test_batch_has_correct_metadata(self) -> None:
        """Test that batch includes all required metadata."""
        builder = SeedBatchBuilder()
        seed_data = {"users": [{"id": str(i)} for i in range(100)]}

        batches = builder.build_batches(seed_data, copy_threshold=1000)
        batch = batches[0]

        assert hasattr(batch, "table")
        assert hasattr(batch, "format")
        assert hasattr(batch, "rows")
        assert hasattr(batch, "rows_count")

    def test_batch_rows_count_matches_data(self) -> None:
        """Test that rows_count matches actual row count."""
        builder = SeedBatchBuilder()
        for size in [10, 100, 500, 1500]:
            seed_data = {"users": [{"id": str(i)} for i in range(size)]}
            batches = builder.build_batches(seed_data)
            assert batches[0].rows_count == size


class TestTableOrdering:
    """Test that batches preserve input table ordering."""

    def test_preserves_table_order(self) -> None:
        """Test that batch order matches input table order."""
        builder = SeedBatchBuilder()
        # Create dict with specific order (Python 3.7+ preserves dict order)
        seed_data = {
            "users": [{"id": str(i)} for i in range(100)],
            "posts": [{"id": str(i)} for i in range(100)],
            "comments": [{"id": str(i)} for i in range(100)],
        }

        batches = builder.build_batches(seed_data)

        tables = [batch.table for batch in batches]
        assert tables == ["users", "posts", "comments"]

    def test_handles_single_table(self) -> None:
        """Test handling single table input."""
        builder = SeedBatchBuilder()
        seed_data = {"users": [{"id": str(i)} for i in range(100)]}

        batches = builder.build_batches(seed_data)

        assert len(batches) == 1
        assert batches[0].table == "users"

    def test_handles_many_tables(self) -> None:
        """Test handling many tables."""
        builder = SeedBatchBuilder()
        table_names = [f"table_{i}" for i in range(10)]
        seed_data = {name: [{"id": "1"}] for name in table_names}

        batches = builder.build_batches(seed_data)

        assert len(batches) == 10
        batch_tables = [batch.table for batch in batches]
        assert batch_tables == table_names


class TestDefaultThreshold:
    """Test default threshold behavior."""

    def test_uses_default_threshold(self) -> None:
        """Test that default threshold is used when not specified."""
        builder = SeedBatchBuilder()
        seed_data = {"users": [{"id": str(i)} for i in range(500)]}

        # Call without threshold parameter
        batches = builder.build_batches(seed_data)

        # Should use some default (likely 1000)
        # 500 < 1000, so should be VALUES
        assert batches[0].format == "VALUES"
