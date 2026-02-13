"""Build seed data batches with intelligent format selection (VALUES vs COPY).

This module provides SeedBatchBuilder to intelligently choose between VALUES and
COPY format based on dataset size for optimal performance.
"""

from dataclasses import dataclass
from typing import Any


@dataclass
class SeedBatch:
    """A batch of seed data with format choice and metrics.

    Attributes:
        table: Table name
        format: Format to use ("VALUES" or "COPY")
        rows: List of row dictionaries
        rows_count: Number of rows in batch
        selected_because: Reason format was selected (e.g., "above threshold")
        estimated_load_time_ms: Estimated execution time in milliseconds
    """

    table: str
    format: str
    rows: list[dict[str, Any]]
    rows_count: int
    selected_because: str = ""
    estimated_load_time_ms: float = 0.0


class SeedBatchBuilder:
    """Intelligently choose VALUES vs COPY format based on dataset size.

    For small datasets (below threshold), uses VALUES format (simpler SQL).
    For large datasets (above threshold), uses COPY format (faster loading).

    Example:
        >>> builder = SeedBatchBuilder()
        >>> seed_data = {
        ...     "users": [{"id": "1", "name": "Alice"}] * 1500,
        ...     "roles": [{"id": "1"}, {"id": "2"}],
        ... }
        >>> batches = builder.build_batches(seed_data, copy_threshold=1000)
        >>> batches[0].format  # "COPY" for users (1500 rows)
        >>> batches[1].format  # "VALUES" for roles (2 rows)
    """

    # Heuristic estimates for execution time (ms per 1000 rows)
    COPY_TIME_PER_1K_ROWS = 10  # COPY is fast
    VALUES_TIME_PER_1K_ROWS = 100  # VALUES is slower

    def build_batches(
        self,
        seed_data: dict[str, list[dict[str, Any]]],
        copy_threshold: int = 1000,
    ) -> list[SeedBatch]:
        """Build seed batches with format selection.

        Args:
            seed_data: Dictionary mapping table names to lists of rows
            copy_threshold: Row count threshold. Use COPY if len(rows) > threshold,
                otherwise use VALUES.

        Returns:
            List of SeedBatch objects with format choices made
        """
        batches = []

        for table, rows in seed_data.items():
            rows_count = len(rows)

            # Choose format based on row count
            format_choice, selection_reason = self._select_format(rows_count, copy_threshold)

            # Estimate execution time
            estimated_time_ms = self._estimate_load_time(rows_count, format_choice)

            batch = SeedBatch(
                table=table,
                format=format_choice,
                rows=rows,
                rows_count=rows_count,
                selected_because=selection_reason,
                estimated_load_time_ms=estimated_time_ms,
            )
            batches.append(batch)

        return batches

    def _select_format(self, rows_count: int, threshold: int) -> tuple[str, str]:
        """Select format based on row count.

        Args:
            rows_count: Number of rows in the dataset
            threshold: Row threshold for format selection

        Returns:
            Tuple of (format, reason) where format is "COPY" or "VALUES"
        """
        if rows_count > threshold:
            return "COPY", f"large dataset ({rows_count} > {threshold} rows)"
        return "VALUES", f"small dataset ({rows_count} <= {threshold} rows)"

    def _estimate_load_time(self, rows_count: int, format_choice: str) -> float:
        """Estimate execution time in milliseconds.

        Args:
            rows_count: Number of rows to load
            format_choice: Selected format ("COPY" or "VALUES")

        Returns:
            Estimated time in milliseconds
        """
        if rows_count == 0:
            return 0.0

        if format_choice == "COPY":
            return (rows_count / 1000) * self.COPY_TIME_PER_1K_ROWS
        else:
            return (rows_count / 1000) * self.VALUES_TIME_PER_1K_ROWS
