"""Compare seed data across environments.

This module provides comparison of seed data between different environments
(dev, staging, production) to detect inconsistencies that might cause
deployment issues.
"""

from dataclasses import dataclass
from typing import Any


@dataclass
class EnvironmentDifference:
    """Represents a difference between two environments.

    Attributes:
        table: Table name where difference was found
        difference_type: Type of difference (TABLE_MISSING_IN_ENV2, ROW_COUNT_MISMATCH, VALUE_MISMATCH, etc.)
        message: Human-readable description of the difference
        env1_count: Row count in environment 1 (for ROW_COUNT_MISMATCH)
        env2_count: Row count in environment 2 (for ROW_COUNT_MISMATCH)
    """

    table: str
    difference_type: str
    message: str
    env1_count: int | None = None
    env2_count: int | None = None


class EnvironmentComparator:
    """Compare seed data across environments.

    Detects differences in seed data between two environments such as:
    - Missing tables
    - Extra tables
    - Row count mismatches
    - Data value differences
    - NULL vs value differences

    Ignores row order (same data in different order is not a difference).

    Example:
        >>> comparator = EnvironmentComparator()
        >>> env1 = {"users": [{"id": "1"}, {"id": "2"}]}
        >>> env2 = {"users": [{"id": "1"}]}
        >>> differences = comparator.compare(env1, env2)
        >>> len(differences)
        1
    """

    def __init__(self) -> None:
        """Initialize the comparator."""
        pass

    def compare(
        self,
        env1: dict[str, list[dict[str, Any]]],
        env2: dict[str, list[dict[str, Any]]],
    ) -> list[EnvironmentDifference]:
        """Compare seed data from two environments.

        Args:
            env1: Seed data from first environment
            env2: Seed data from second environment

        Returns:
            List of EnvironmentDifference objects for any differences found
        """
        differences = []

        # Get all table names from both environments
        all_tables = set(env1.keys()) | set(env2.keys())

        for table_name in all_tables:
            # Check if table exists in both environments
            if table_name not in env1:
                difference = EnvironmentDifference(
                    table=table_name,
                    difference_type="TABLE_EXTRA_IN_ENV2",
                    message=f"Table {table_name} exists in environment 2 but not in environment 1",
                    env2_count=len(env2[table_name]),
                )
                differences.append(difference)
                continue

            if table_name not in env2:
                difference = EnvironmentDifference(
                    table=table_name,
                    difference_type="TABLE_MISSING_IN_ENV2",
                    message=f"Table {table_name} exists in environment 1 but not in environment 2",
                    env1_count=len(env1[table_name]),
                )
                differences.append(difference)
                continue

            # Table exists in both, compare rows
            rows1 = env1[table_name]
            rows2 = env2[table_name]

            # Check row count first
            if len(rows1) != len(rows2):
                difference = EnvironmentDifference(
                    table=table_name,
                    difference_type="ROW_COUNT_MISMATCH",
                    message=(
                        f"Table {table_name} has {len(rows1)} rows in environment 1 "
                        f"but {len(rows2)} rows in environment 2"
                    ),
                    env1_count=len(rows1),
                    env2_count=len(rows2),
                )
                differences.append(difference)
                continue

            # Check for data differences (order-independent)
            diffs = self._compare_row_sets(table_name, rows1, rows2)
            differences.extend(diffs)

        return differences

    @staticmethod
    def _compare_row_sets(
        table_name: str,
        rows1: list[dict[str, Any]],
        rows2: list[dict[str, Any]],
    ) -> list[EnvironmentDifference]:
        """Compare two sets of rows (order-independent).

        Args:
            table_name: Name of the table
            rows1: Rows from environment 1
            rows2: Rows from environment 2

        Returns:
            List of differences found
        """
        differences = []

        # Normalize rows for comparison (convert to sorted tuples)
        rows1_set = {EnvironmentComparator._normalize_row(r) for r in rows1}
        rows2_set = {EnvironmentComparator._normalize_row(r) for r in rows2}

        # Check if sets are equal
        if rows1_set != rows2_set:
            difference = EnvironmentDifference(
                table=table_name,
                difference_type="VALUE_MISMATCH",
                message=f"Table {table_name} has different values between environments",
            )
            differences.append(difference)

        return differences

    @staticmethod
    def _normalize_row(row: dict[str, Any]) -> tuple[tuple[str, str], ...]:
        """Convert row to normalized tuple for comparison.

        Args:
            row: Row dictionary

        Returns:
            Sorted tuple of (key, value) pairs
        """
        items = []
        for key, value in sorted(row.items()):
            # Convert value to string for comparison, handling None
            str_value = "NULL" if value is None else str(value)
            items.append((key, str_value))
        return tuple(items)
