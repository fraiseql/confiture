"""Unit tests for confiture.testing.frameworks.mutation module.

Tests cover:
- MutationSeverity and MutationCategory enums
- Mutation dataclass and apply method
- MutationResult and MutationTestResult dataclasses
- MutationMetrics calculations
- MutationReport and to_dict method
- MutationRegistry initialization and queries
- MutationRunner execution and reporting
"""

import json
from unittest.mock import MagicMock

import pytest

from confiture.testing.frameworks.mutation import (
    Mutation,
    MutationCategory,
    MutationMetrics,
    MutationRegistry,
    MutationReport,
    MutationResult,
    MutationRunner,
    MutationSeverity,
    MutationTestResult,
)


class TestMutationSeverity:
    """Test MutationSeverity enum."""

    def test_critical_value(self):
        """Test CRITICAL value."""
        assert MutationSeverity.CRITICAL.value == "CRITICAL"

    def test_important_value(self):
        """Test IMPORTANT value."""
        assert MutationSeverity.IMPORTANT.value == "IMPORTANT"

    def test_minor_value(self):
        """Test MINOR value."""
        assert MutationSeverity.MINOR.value == "MINOR"


class TestMutationCategory:
    """Test MutationCategory enum."""

    def test_schema_value(self):
        """Test schema category."""
        assert MutationCategory.SCHEMA.value == "schema"

    def test_data_value(self):
        """Test data category."""
        assert MutationCategory.DATA.value == "data"

    def test_rollback_value(self):
        """Test rollback category."""
        assert MutationCategory.ROLLBACK.value == "rollback"

    def test_performance_value(self):
        """Test performance category."""
        assert MutationCategory.PERFORMANCE.value == "performance"


class TestMutation:
    """Test Mutation dataclass and apply method."""

    def test_creation(self):
        """Test creating a Mutation."""
        mutation = Mutation(
            id="test_001",
            name="test_mutation",
            description="Test mutation for unit tests",
            category=MutationCategory.SCHEMA,
            severity=MutationSeverity.CRITICAL,
        )

        assert mutation.id == "test_001"
        assert mutation.name == "test_mutation"
        assert mutation.category == MutationCategory.SCHEMA
        assert mutation.severity == MutationSeverity.CRITICAL

    def test_apply_with_function(self):
        """Test apply with a custom function."""
        mutation = Mutation(
            id="test_002",
            name="func_mutation",
            description="Mutation with function",
            category=MutationCategory.DATA,
            severity=MutationSeverity.IMPORTANT,
            apply_fn=lambda sql: sql.replace("SELECT", "SELECT /*mutated*/"),
        )

        result = mutation.apply("SELECT * FROM users")
        assert "/*mutated*/" in result

    def test_apply_with_regex(self):
        """Test apply with regex pattern."""
        mutation = Mutation(
            id="test_003",
            name="regex_mutation",
            description="Mutation with regex",
            category=MutationCategory.SCHEMA,
            severity=MutationSeverity.CRITICAL,
            apply_regex=r"NOT\s+NULL" + "=>" + "NULL",
        )

        result = mutation.apply("CREATE TABLE t (id INT NOT NULL)")
        assert "NULL" in result
        assert "NOT NULL" not in result

    def test_apply_with_invalid_regex(self):
        """Test apply with invalid regex format."""
        mutation = Mutation(
            id="test_004",
            name="invalid_regex",
            description="Mutation with invalid regex",
            category=MutationCategory.SCHEMA,
            severity=MutationSeverity.MINOR,
            apply_regex="invalid-no-separator",
        )

        result = mutation.apply("SELECT * FROM users")
        # Should return original SQL unchanged
        assert result == "SELECT * FROM users"

    def test_apply_with_no_transform(self):
        """Test apply with neither function nor regex."""
        mutation = Mutation(
            id="test_005",
            name="no_transform",
            description="Mutation with no transform",
            category=MutationCategory.DATA,
            severity=MutationSeverity.MINOR,
        )

        result = mutation.apply("SELECT * FROM users")
        assert result == "SELECT * FROM users"


class TestMutationResult:
    """Test MutationResult dataclass."""

    def test_creation(self):
        """Test creating a MutationResult."""
        result = MutationResult(
            mutation_id="test_001",
            success=True,
            mutation_applied=True,
            duration_seconds=0.5,
            stdout="Mutation executed",
            stderr="",
        )

        assert result.mutation_id == "test_001"
        assert result.success is True
        assert result.mutation_applied is True
        assert result.duration_seconds == 0.5

    def test_with_error(self):
        """Test MutationResult with error."""
        error = ValueError("Test error")
        result = MutationResult(
            mutation_id="test_002",
            success=False,
            mutation_applied=True,
            duration_seconds=0.1,
            stdout="",
            stderr="Test error",
            error=error,
        )

        assert result.success is False
        assert result.error is error


class TestMutationTestResult:
    """Test MutationTestResult dataclass."""

    def test_creation(self):
        """Test creating a MutationTestResult."""
        result = MutationTestResult(
            mutation_id="test_001",
            mutation_name="test_mutation",
            test_name="test_something",
            caught=True,
            duration_seconds=0.05,
        )

        assert result.mutation_id == "test_001"
        assert result.caught is True


class TestMutationMetrics:
    """Test MutationMetrics dataclass and calculations."""

    def test_creation(self):
        """Test creating MutationMetrics."""
        metrics = MutationMetrics(
            total_mutations=100,
            killed_mutations=75,
            survived_mutations=25,
        )

        assert metrics.total_mutations == 100
        assert metrics.killed_mutations == 75

    def test_kill_rate(self):
        """Test kill_rate calculation."""
        metrics = MutationMetrics(
            total_mutations=100,
            killed_mutations=80,
            survived_mutations=20,
        )

        assert metrics.kill_rate == 80.0

    def test_kill_rate_zero_mutations(self):
        """Test kill_rate with zero mutations."""
        metrics = MutationMetrics(
            total_mutations=0,
            killed_mutations=0,
            survived_mutations=0,
        )

        assert metrics.kill_rate == 0.0


class TestMutationReport:
    """Test MutationReport dataclass."""

    def test_creation(self):
        """Test creating MutationReport."""
        metrics = MutationMetrics(
            total_mutations=50,
            killed_mutations=40,
            survived_mutations=10,
        )

        report = MutationReport(
            timestamp="2024-01-15T10:00:00",
            total_mutations=50,
            metrics=metrics,
        )

        assert report.total_mutations == 50
        assert report.metrics.kill_rate == 80.0

    def test_to_dict(self):
        """Test to_dict method."""
        metrics = MutationMetrics(
            total_mutations=50,
            killed_mutations=40,
            survived_mutations=10,
        )

        report = MutationReport(
            timestamp="2024-01-15T10:00:00",
            total_mutations=50,
            metrics=metrics,
            recommendations=["Add more tests"],
        )

        result = report.to_dict()

        assert result["timestamp"] == "2024-01-15T10:00:00"
        assert result["total_mutations"] == 50
        assert "80.0%" in result["kill_rate"]
        assert "Add more tests" in result["recommendations"]


class TestMutationRegistry:
    """Test MutationRegistry class."""

    def test_init_creates_default_mutations(self):
        """Test registry initializes with default mutations."""
        registry = MutationRegistry()

        assert len(registry.mutations) > 0
        # Should have mutations from all categories
        assert any(m.category == MutationCategory.SCHEMA for m in registry.mutations.values())
        assert any(m.category == MutationCategory.DATA for m in registry.mutations.values())
        assert any(m.category == MutationCategory.ROLLBACK for m in registry.mutations.values())
        assert any(m.category == MutationCategory.PERFORMANCE for m in registry.mutations.values())

    def test_get_mutation(self):
        """Test get_mutation method."""
        registry = MutationRegistry()

        mutation = registry.get_mutation("schema_001")
        assert mutation is not None
        assert mutation.id == "schema_001"

    def test_get_mutation_not_found(self):
        """Test get_mutation returns None for unknown ID."""
        registry = MutationRegistry()

        mutation = registry.get_mutation("nonexistent_id")
        assert mutation is None

    def test_get_by_category(self):
        """Test get_by_category method."""
        registry = MutationRegistry()

        schema_mutations = registry.get_by_category(MutationCategory.SCHEMA)
        assert len(schema_mutations) > 0
        assert all(m.category == MutationCategory.SCHEMA for m in schema_mutations)

    def test_get_by_severity(self):
        """Test get_by_severity method."""
        registry = MutationRegistry()

        critical_mutations = registry.get_by_severity(MutationSeverity.CRITICAL)
        assert len(critical_mutations) > 0
        assert all(m.severity == MutationSeverity.CRITICAL for m in critical_mutations)

    def test_list_all(self):
        """Test list_all method."""
        registry = MutationRegistry()

        all_mutations = registry.list_all()
        assert len(all_mutations) == len(registry.mutations)

    def test_default_schema_mutations(self):
        """Test default schema mutations exist."""
        registry = MutationRegistry()

        schema_mutations = registry.get_by_category(MutationCategory.SCHEMA)
        mutation_names = [m.name for m in schema_mutations]

        assert "remove_primary_key" in mutation_names
        assert "remove_not_null" in mutation_names
        assert "remove_unique" in mutation_names

    def test_default_data_mutations(self):
        """Test default data mutations exist."""
        registry = MutationRegistry()

        data_mutations = registry.get_by_category(MutationCategory.DATA)
        mutation_names = [m.name for m in data_mutations]

        assert "skip_update" in mutation_names
        assert "skip_delete" in mutation_names


class TestMutationRunner:
    """Test MutationRunner class."""

    @pytest.fixture
    def mock_connection(self):
        """Create mock database connection."""
        return MagicMock()

    @pytest.fixture
    def temp_migrations_dir(self, tmp_path):
        """Create temporary migrations directory."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        return migrations_dir

    def test_init(self, mock_connection, temp_migrations_dir):
        """Test runner initialization."""
        runner = MutationRunner(mock_connection, temp_migrations_dir)

        assert runner.connection is mock_connection
        assert runner.migrations_dir == temp_migrations_dir
        assert isinstance(runner.registry, MutationRegistry)
        assert runner.test_results == []

    def test_run_migration_with_mutation_file_not_found(self, mock_connection, temp_migrations_dir):
        """Test run_migration_with_mutation with missing file."""
        runner = MutationRunner(mock_connection, temp_migrations_dir)
        mutation = Mutation(
            id="test_001",
            name="test",
            description="Test",
            category=MutationCategory.SCHEMA,
            severity=MutationSeverity.MINOR,
        )

        result = runner.run_migration_with_mutation("nonexistent", mutation)

        assert result.success is False
        assert result.mutation_applied is False
        assert "not found" in result.stderr.lower() or "Migration not found" in result.stderr

    def test_run_migration_with_mutation_not_applied(self, mock_connection, temp_migrations_dir):
        """Test run_migration_with_mutation when mutation doesn't apply."""
        # Create migration file
        migration_file = temp_migrations_dir / "test_migration.sql"
        migration_file.write_text("SELECT 1;")

        runner = MutationRunner(mock_connection, temp_migrations_dir)

        # Mutation that won't match the SQL
        mutation = Mutation(
            id="test_001",
            name="no_match",
            description="Won't match",
            category=MutationCategory.SCHEMA,
            severity=MutationSeverity.MINOR,
            apply_regex=r"NONEXISTENT" + "=>" + "SOMETHING",
        )

        result = runner.run_migration_with_mutation("test_migration", mutation)

        assert result.success is False
        assert result.mutation_applied is False
        assert "could not be applied" in result.stderr.lower()

    def test_run_migration_with_mutation_success(self, mock_connection, temp_migrations_dir):
        """Test run_migration_with_mutation successful execution."""
        # Create migration file
        migration_file = temp_migrations_dir / "test_migration.sql"
        migration_file.write_text("CREATE TABLE test NOT NULL;")

        # Mock cursor
        mock_cursor = MagicMock()
        mock_connection.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_connection.cursor.return_value.__exit__ = MagicMock(return_value=None)

        runner = MutationRunner(mock_connection, temp_migrations_dir)

        mutation = Mutation(
            id="test_001",
            name="remove_not_null",
            description="Remove NOT NULL",
            category=MutationCategory.SCHEMA,
            severity=MutationSeverity.CRITICAL,
            apply_regex=r"NOT\s+NULL" + "=>" + " ",
        )

        result = runner.run_migration_with_mutation("test_migration", mutation)

        assert result.mutation_applied is True
        mock_cursor.execute.assert_called_once()

    def test_run_migration_with_mutation_execution_error(
        self, mock_connection, temp_migrations_dir
    ):
        """Test run_migration_with_mutation with execution error."""
        # Create migration file
        migration_file = temp_migrations_dir / "test_migration.sql"
        migration_file.write_text("CREATE TABLE test NOT NULL;")

        # Mock cursor to raise error
        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = Exception("SQL Error")
        mock_connection.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_connection.cursor.return_value.__exit__ = MagicMock(return_value=None)

        runner = MutationRunner(mock_connection, temp_migrations_dir)

        mutation = Mutation(
            id="test_001",
            name="remove_not_null",
            description="Remove NOT NULL",
            category=MutationCategory.SCHEMA,
            severity=MutationSeverity.CRITICAL,
            apply_regex=r"NOT\s+NULL" + "=>" + " ",
        )

        result = runner.run_migration_with_mutation("test_migration", mutation)

        assert result.success is False
        assert result.mutation_applied is True
        assert "SQL Error" in result.stderr
        mock_connection.rollback.assert_called()

    def test_record_test_result(self, mock_connection, temp_migrations_dir):
        """Test record_test_result method."""
        runner = MutationRunner(mock_connection, temp_migrations_dir)

        runner.record_test_result(
            mutation_id="test_001",
            mutation_name="test_mutation",
            test_name="test_something",
            caught=True,
            duration=0.05,
        )

        assert len(runner.test_results) == 1
        assert runner.test_results[0].mutation_id == "test_001"
        assert runner.test_results[0].caught is True

    def test_generate_report(self, mock_connection, temp_migrations_dir):
        """Test generate_report method."""
        runner = MutationRunner(mock_connection, temp_migrations_dir)

        # Add some test results
        runner.record_test_result("m1", "mutation1", "test1", True, 0.1)
        runner.record_test_result("m2", "mutation2", "test1", False, 0.1)
        runner.record_test_result("m3", "mutation3", "test2", True, 0.1)

        report = runner.generate_report()

        assert report.total_mutations > 0
        assert report.metrics.killed_mutations == 2
        assert report.timestamp is not None

    def test_generate_recommendations_weak_tests(self, mock_connection, temp_migrations_dir):
        """Test _generate_recommendations identifies weak tests."""
        runner = MutationRunner(mock_connection, temp_migrations_dir)

        # Add results where test1 catches few mutations
        runner.record_test_result("m1", "mutation1", "weak_test", False, 0.1)
        runner.record_test_result("m2", "mutation2", "weak_test", False, 0.1)
        runner.record_test_result("m3", "mutation3", "weak_test", True, 0.1)
        runner.record_test_result("m4", "mutation4", "weak_test", False, 0.1)

        recommendations = runner._generate_recommendations()

        assert len(recommendations) > 0
        assert any("weak_test" in r for r in recommendations)

    def test_export_report(self, mock_connection, temp_migrations_dir, tmp_path):
        """Test export_report method."""
        runner = MutationRunner(mock_connection, temp_migrations_dir)

        metrics = MutationMetrics(
            total_mutations=10,
            killed_mutations=8,
            survived_mutations=2,
        )

        report = MutationReport(
            timestamp="2024-01-15T10:00:00",
            total_mutations=10,
            metrics=metrics,
        )

        output_path = tmp_path / "report.json"
        runner.export_report(report, output_path)

        assert output_path.exists()
        data = json.loads(output_path.read_text())
        assert data["total_mutations"] == 10


class TestMutationApplyIntegration:
    """Integration tests for mutation apply functionality."""

    def test_remove_not_null_mutation(self):
        """Test remove_not_null mutation applies correctly."""
        registry = MutationRegistry()
        mutation = registry.get_mutation("schema_002")

        sql = "CREATE TABLE users (id INT NOT NULL, name VARCHAR(255) NOT NULL)"
        result = mutation.apply(sql)

        assert "NOT NULL" not in result

    def test_skip_index_mutation(self):
        """Test skip_index mutation comments out index creation."""
        registry = MutationRegistry()
        mutation = registry.get_mutation("schema_005")

        sql = "CREATE INDEX idx_users_email ON users(email)"
        result = mutation.apply(sql)

        assert "-- CREATE INDEX" in result

    def test_skip_update_mutation(self):
        """Test skip_update mutation comments out UPDATE."""
        registry = MutationRegistry()
        mutation = registry.get_mutation("data_001")

        sql = "UPDATE users SET status = 'active';"
        result = mutation.apply(sql)

        # Should be commented out
        assert "--" in result or "(skipped)" in result

    def test_drop_table_mutation(self):
        """Test rollback mutation comments out DROP TABLE."""
        registry = MutationRegistry()
        mutation = registry.get_mutation("rollback_001")

        sql = "DROP TABLE users CASCADE"
        result = mutation.apply(sql)

        assert "-- DROP TABLE" in result
