"""Tests for EnvironmentComparator - comparing seed data across environments."""

from confiture.core.seed_validation.environment_comparator import (
    EnvironmentComparator,
)


class TestBasicEnvironmentComparison:
    """Test basic environment comparison."""

    def test_detects_identical_data(self) -> None:
        """Test detecting when environments have identical data."""
        comparator = EnvironmentComparator()
        env1 = {
            "users": [
                {"id": "1", "email": "alice@example.com"},
                {"id": "2", "email": "bob@example.com"},
            ]
        }
        env2 = {
            "users": [
                {"id": "1", "email": "alice@example.com"},
                {"id": "2", "email": "bob@example.com"},
            ]
        }

        differences = comparator.compare(env1, env2)

        assert len(differences) == 0

    def test_detects_missing_table_in_env2(self) -> None:
        """Test detecting when a table exists in env1 but not env2."""
        comparator = EnvironmentComparator()
        env1 = {
            "users": [{"id": "1", "email": "alice@example.com"}],
            "roles": [{"id": "1", "name": "admin"}],
        }
        env2 = {
            "users": [{"id": "1", "email": "alice@example.com"}],
        }

        differences = comparator.compare(env1, env2)

        assert len(differences) == 1
        assert differences[0].table == "roles"
        assert differences[0].difference_type == "TABLE_MISSING_IN_ENV2"

    def test_detects_extra_table_in_env2(self) -> None:
        """Test detecting when a table exists in env2 but not env1."""
        comparator = EnvironmentComparator()
        env1 = {
            "users": [{"id": "1", "email": "alice@example.com"}],
        }
        env2 = {
            "users": [{"id": "1", "email": "alice@example.com"}],
            "roles": [{"id": "1", "name": "admin"}],
        }

        differences = comparator.compare(env1, env2)

        assert len(differences) == 1
        assert differences[0].table == "roles"
        assert differences[0].difference_type == "TABLE_EXTRA_IN_ENV2"


class TestRowCountDifferences:
    """Test detecting row count differences."""

    def test_detects_different_row_counts(self) -> None:
        """Test detecting when table has different row counts."""
        comparator = EnvironmentComparator()
        env1 = {
            "users": [
                {"id": "1", "email": "alice@example.com"},
                {"id": "2", "email": "bob@example.com"},
            ]
        }
        env2 = {
            "users": [
                {"id": "1", "email": "alice@example.com"},
            ]
        }

        differences = comparator.compare(env1, env2)

        assert len(differences) == 1
        assert differences[0].table == "users"
        assert differences[0].difference_type == "ROW_COUNT_MISMATCH"
        assert differences[0].env1_count == 2
        assert differences[0].env2_count == 1

    def test_allows_same_row_counts(self) -> None:
        """Test that same row counts are OK."""
        comparator = EnvironmentComparator()
        env1 = {
            "users": [
                {"id": "1", "email": "alice@example.com"},
                {"id": "2", "email": "bob@example.com"},
            ]
        }
        env2 = {
            "users": [
                {"id": "1", "email": "alice@example.com"},
                {"id": "2", "email": "bob@example.com"},
            ]
        }

        differences = comparator.compare(env1, env2)

        assert len(differences) == 0


class TestDataValueDifferences:
    """Test detecting actual data value differences."""

    def test_detects_different_values(self) -> None:
        """Test detecting when values differ between environments."""
        comparator = EnvironmentComparator()
        env1 = {
            "users": [
                {"id": "1", "email": "alice@example.com"},
            ]
        }
        env2 = {
            "users": [
                {"id": "1", "email": "alice-staging@example.com"},
            ]
        }

        differences = comparator.compare(env1, env2)

        assert len(differences) == 1
        assert differences[0].difference_type == "VALUE_MISMATCH"

    def test_detects_missing_row_in_env2(self) -> None:
        """Test detecting when env1 has a row that env2 doesn't."""
        comparator = EnvironmentComparator()
        env1 = {
            "users": [
                {"id": "1", "email": "alice@example.com"},
                {"id": "2", "email": "bob@example.com"},
            ]
        }
        env2 = {
            "users": [
                {"id": "1", "email": "alice@example.com"},
            ]
        }

        differences = comparator.compare(env1, env2)

        # Should report either row count mismatch or missing row
        assert len(differences) >= 1

    def test_detects_extra_row_in_env2(self) -> None:
        """Test detecting when env2 has a row that env1 doesn't."""
        comparator = EnvironmentComparator()
        env1 = {
            "users": [
                {"id": "1", "email": "alice@example.com"},
            ]
        }
        env2 = {
            "users": [
                {"id": "1", "email": "alice@example.com"},
                {"id": "2", "email": "bob@example.com"},
            ]
        }

        differences = comparator.compare(env1, env2)

        # Should report row count mismatch
        assert len(differences) >= 1


class TestMultipleTableComparison:
    """Test comparing multiple tables."""

    def test_detects_differences_in_multiple_tables(self) -> None:
        """Test detecting differences across multiple tables."""
        comparator = EnvironmentComparator()
        env1 = {
            "users": [
                {"id": "1", "email": "alice@example.com"},
            ],
            "roles": [
                {"id": "1", "name": "admin"},
            ],
        }
        env2 = {
            "users": [
                {"id": "1", "email": "alice-staging@example.com"},
            ],
            "roles": [],
        }

        differences = comparator.compare(env1, env2)

        assert len(differences) >= 2


class TestEnvironmentComparisonEdgeCases:
    """Test edge cases in environment comparison."""

    def test_handles_empty_environments(self) -> None:
        """Test comparing two empty environments."""
        comparator = EnvironmentComparator()
        env1 = {}
        env2 = {}

        differences = comparator.compare(env1, env2)

        assert len(differences) == 0

    def test_handles_one_empty_environment(self) -> None:
        """Test comparing empty vs non-empty environment."""
        comparator = EnvironmentComparator()
        env1 = {
            "users": [{"id": "1"}],
        }
        env2 = {}

        differences = comparator.compare(env1, env2)

        assert len(differences) >= 1

    def test_handles_null_values(self) -> None:
        """Test comparing NULL values."""
        comparator = EnvironmentComparator()
        env1 = {
            "users": [
                {"id": "1", "phone": None},
            ]
        }
        env2 = {
            "users": [
                {"id": "1", "phone": None},
            ]
        }

        differences = comparator.compare(env1, env2)

        # NULLs are equal
        assert len(differences) == 0

    def test_handles_different_null_states(self) -> None:
        """Test comparing NULL vs value."""
        comparator = EnvironmentComparator()
        env1 = {
            "users": [
                {"id": "1", "phone": None},
            ]
        }
        env2 = {
            "users": [
                {"id": "1", "phone": "555-1234"},
            ]
        }

        differences = comparator.compare(env1, env2)

        # NULL != value should be detected
        assert len(differences) == 1

    def test_ignores_row_order(self) -> None:
        """Test that row order doesn't matter for comparison."""
        comparator = EnvironmentComparator()
        env1 = {
            "users": [
                {"id": "1", "email": "alice@example.com"},
                {"id": "2", "email": "bob@example.com"},
            ]
        }
        env2 = {
            "users": [
                {"id": "2", "email": "bob@example.com"},
                {"id": "1", "email": "alice@example.com"},
            ]
        }

        differences = comparator.compare(env1, env2)

        # Same data, different order should not be a difference
        assert len(differences) == 0


class TestViolationStructure:
    """Test the structure of EnvironmentDifference objects."""

    def test_difference_has_all_fields(self) -> None:
        """Test that difference contains all required fields."""
        comparator = EnvironmentComparator()
        env1 = {
            "users": [{"id": "1"}],
        }
        env2 = {}

        differences = comparator.compare(env1, env2)

        diff = differences[0]
        assert hasattr(diff, "table")
        assert hasattr(diff, "difference_type")
        assert hasattr(diff, "message")

    def test_difference_includes_counts(self) -> None:
        """Test that row count difference includes counts."""
        comparator = EnvironmentComparator()
        env1 = {
            "users": [
                {"id": "1"},
                {"id": "2"},
            ]
        }
        env2 = {
            "users": [
                {"id": "1"},
            ]
        }

        differences = comparator.compare(env1, env2)

        diff = differences[0]
        assert hasattr(diff, "env1_count")
        assert hasattr(diff, "env2_count")
        assert diff.env1_count == 2
        assert diff.env2_count == 1

    def test_difference_message_is_descriptive(self) -> None:
        """Test that difference message is human-readable."""
        comparator = EnvironmentComparator()
        env1 = {
            "users": [{"id": "1"}],
        }
        env2 = {}

        differences = comparator.compare(env1, env2)

        message = differences[0].message
        assert "users" in message.lower()
