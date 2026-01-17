"""Mutation testing framework for database migrations.

Mutation testing verifies that migration tests would catch intentional bugs
by creating variations of migrations and checking if tests detect them.

Architecture:
- MutationRegistry: Catalog of all possible mutations
- MutationRunner: Execute migrations with mutations applied
- MutationReport: Analyze which tests caught which mutations
- MutationMetrics: Calculate mutation kill rate and effectiveness
"""

import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import psycopg


class MutationSeverity(Enum):
    """Severity level of a mutation."""

    CRITICAL = "CRITICAL"  # Schema/data integrity issues
    IMPORTANT = "IMPORTANT"  # Significant behavior changes
    MINOR = "MINOR"  # Edge cases, optimization


class MutationCategory(Enum):
    """Category of mutation."""

    SCHEMA = "schema"  # Table/column/constraint changes
    DATA = "data"  # Data transformations
    ROLLBACK = "rollback"  # Rollback operations
    PERFORMANCE = "performance"  # Performance optimization


@dataclass
class Mutation:
    """Definition of a single mutation."""

    id: str  # Unique identifier
    name: str  # Human-readable name
    description: str  # What the mutation does
    category: MutationCategory  # Type of mutation
    severity: MutationSeverity  # Impact level
    apply_fn: Callable | None = None  # Function to apply mutation
    apply_regex: str | None = None  # Regex for SQL transformation

    def apply(self, sql: str) -> str:
        """Apply this mutation to SQL code."""
        if self.apply_fn:
            return self.apply_fn(sql)
        elif self.apply_regex:
            # Simple regex-based mutations
            # Format: "pattern=>replacement"
            parts = self.apply_regex.split("=>")
            if len(parts) == 2:
                pattern, replacement = parts
                return re.sub(pattern, replacement, sql, flags=re.IGNORECASE)
        return sql


@dataclass
class MutationResult:
    """Result of executing a migration with a mutation."""

    mutation_id: str
    success: bool  # Migration executed
    mutation_applied: bool  # Mutation was successfully applied
    duration_seconds: float
    stdout: str
    stderr: str
    database_state: dict | None = None  # Schema state after mutation
    error: Exception | None = None


@dataclass
class MutationTestResult:
    """Result of testing a mutation against test suite."""

    mutation_id: str
    mutation_name: str
    test_name: str
    caught: bool  # Test caught the mutation
    duration_seconds: float


@dataclass
class MutationMetrics:
    """Metrics for mutation test results."""

    total_mutations: int = 0
    killed_mutations: int = 0  # Caught by tests
    survived_mutations: int = 0  # Missed by tests
    equivalent_mutations: int = 0  # Logically equivalent

    by_category: dict[str, dict[str, int]] = field(default_factory=dict)
    by_severity: dict[str, dict[str, int]] = field(default_factory=dict)
    weak_tests: list[str] = field(default_factory=list)

    @property
    def kill_rate(self) -> float:
        """Percentage of mutations killed by tests."""
        if self.total_mutations == 0:
            return 0.0
        return (self.killed_mutations / self.total_mutations) * 100


@dataclass
class MutationReport:
    """Complete mutation testing report."""

    timestamp: str
    total_mutations: int
    metrics: MutationMetrics
    results_by_mutation: dict[str, list[MutationTestResult]] = field(default_factory=dict)
    results_by_test: dict[str, list[MutationTestResult]] = field(default_factory=dict)
    recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert report to dictionary."""
        return {
            "timestamp": self.timestamp,
            "total_mutations": self.total_mutations,
            "metrics": asdict(self.metrics),
            "kill_rate": f"{self.metrics.kill_rate:.1f}%",
            "recommendations": self.recommendations,
        }


class MutationRegistry:
    """Registry of all available mutations."""

    def __init__(self):
        self.mutations: dict[str, Mutation] = {}
        self._initialize_default_mutations()

    def _initialize_default_mutations(self):
        """Initialize default mutation set."""
        # Schema mutations
        self._add_schema_mutations()
        # Data mutations
        self._add_data_mutations()
        # Rollback mutations
        self._add_rollback_mutations()
        # Performance mutations
        self._add_performance_mutations()

    def _add_schema_mutations(self):
        """Add schema-related mutations."""
        schema_mutations = [
            Mutation(
                id="schema_001",
                name="remove_primary_key",
                description="Remove PRIMARY KEY constraint from table",
                category=MutationCategory.SCHEMA,
                severity=MutationSeverity.CRITICAL,
                apply_regex=r"PRIMARY KEY\s*,?\s*" + "=>" + " ",
            ),
            Mutation(
                id="schema_002",
                name="remove_not_null",
                description="Remove NOT NULL constraint from column",
                category=MutationCategory.SCHEMA,
                severity=MutationSeverity.CRITICAL,
                apply_regex=r"\s+NOT\s+NULL" + "=>" + " ",
            ),
            Mutation(
                id="schema_003",
                name="remove_unique",
                description="Remove UNIQUE constraint",
                category=MutationCategory.SCHEMA,
                severity=MutationSeverity.IMPORTANT,
                apply_regex=r"\s+UNIQUE" + "=>" + " ",
            ),
            Mutation(
                id="schema_004",
                name="remove_foreign_key",
                description="Remove FOREIGN KEY constraint",
                category=MutationCategory.SCHEMA,
                severity=MutationSeverity.CRITICAL,
                apply_regex=r"FOREIGN\s+KEY\s+\([^)]+\)\s+REFERENCES\s+\S+\s*\([^)]+\)"
                + "=>"
                + " ",
            ),
            Mutation(
                id="schema_005",
                name="skip_index_creation",
                description="Skip index creation in migration",
                category=MutationCategory.SCHEMA,
                severity=MutationSeverity.IMPORTANT,
                apply_regex=r"CREATE\s+(?:UNIQUE\s+)?INDEX" + "=>" + "-- CREATE INDEX",
            ),
            Mutation(
                id="schema_006",
                name="change_column_type",
                description="Change column data type",
                category=MutationCategory.SCHEMA,
                severity=MutationSeverity.CRITICAL,
                apply_fn=lambda sql: sql.replace("TEXT", "VARCHAR(50)") if "TEXT" in sql else sql,
            ),
            Mutation(
                id="schema_007",
                name="remove_default_value",
                description="Remove DEFAULT value from column",
                category=MutationCategory.SCHEMA,
                severity=MutationSeverity.IMPORTANT,
                apply_regex=r"\s+DEFAULT\s+['\"]?[^,)]+['\"]?" + "=>" + " ",
            ),
            Mutation(
                id="schema_008",
                name="add_unnecessary_column",
                description="Add extra unrequired column",
                category=MutationCategory.SCHEMA,
                severity=MutationSeverity.MINOR,
                apply_fn=lambda sql: sql + "\nALTER TABLE ADD COLUMN mutation_marker BOOLEAN;",
            ),
            Mutation(
                id="schema_009",
                name="skip_constraint_check",
                description="Skip CHECK constraint",
                category=MutationCategory.SCHEMA,
                severity=MutationSeverity.IMPORTANT,
                apply_regex=r"CHECK\s*\([^)]+\)" + "=>" + " ",
            ),
            Mutation(
                id="schema_010",
                name="wrong_column_order",
                description="Change column ordering in table",
                category=MutationCategory.SCHEMA,
                severity=MutationSeverity.MINOR,
                apply_fn=lambda sql: sql,  # Complex to implement
            ),
        ]

        for mutation in schema_mutations:
            self.mutations[mutation.id] = mutation

    def _add_data_mutations(self):
        """Add data-related mutations."""
        data_mutations = [
            Mutation(
                id="data_001",
                name="skip_update",
                description="Skip UPDATE statement in migration",
                category=MutationCategory.DATA,
                severity=MutationSeverity.CRITICAL,
                apply_regex=r"UPDATE\s+\w+\s+SET.*?;" + "=>" + "-- UPDATE (skipped);",
            ),
            Mutation(
                id="data_002",
                name="wrong_update_value",
                description="Use wrong value in UPDATE",
                category=MutationCategory.DATA,
                severity=MutationSeverity.CRITICAL,
                apply_fn=lambda sql: sql.replace("'active'", "'inactive'")
                if "'active'" in sql
                else sql,
            ),
            Mutation(
                id="data_003",
                name="skip_delete",
                description="Skip DELETE statement",
                category=MutationCategory.DATA,
                severity=MutationSeverity.CRITICAL,
                apply_regex=r"DELETE\s+FROM.*?;" + "=>" + "-- DELETE (skipped);",
            ),
            Mutation(
                id="data_004",
                name="incomplete_insert",
                description="Skip INSERT statement",
                category=MutationCategory.DATA,
                severity=MutationSeverity.CRITICAL,
                apply_regex=r"INSERT\s+INTO.*?;" + "=>" + "-- INSERT (skipped);",
            ),
            Mutation(
                id="data_005",
                name="wrong_where_clause",
                description="Change WHERE condition",
                category=MutationCategory.DATA,
                severity=MutationSeverity.CRITICAL,
                apply_fn=lambda sql: sql.replace("WHERE id > 0", "WHERE id < 0")
                if "WHERE id > 0" in sql
                else sql,
            ),
            Mutation(
                id="data_006",
                name="missing_coalesce",
                description="Don't use COALESCE for NULLs",
                category=MutationCategory.DATA,
                severity=MutationSeverity.IMPORTANT,
                apply_fn=lambda sql: sql.replace("COALESCE(", "") if "COALESCE(" in sql else sql,
            ),
            Mutation(
                id="data_007",
                name="partial_update",
                description="Update only some rows when should update all",
                category=MutationCategory.DATA,
                severity=MutationSeverity.CRITICAL,
                apply_fn=lambda sql: sql.replace("UPDATE table", "UPDATE table WHERE id IN (1,2,3)")
                if "UPDATE table" in sql
                else sql,
            ),
            Mutation(
                id="data_008",
                name="wrong_cast",
                description="Use wrong type cast",
                category=MutationCategory.DATA,
                severity=MutationSeverity.IMPORTANT,
                apply_fn=lambda sql: sql.replace("::TEXT", "::INTEGER") if "::TEXT" in sql else sql,
            ),
        ]

        for mutation in data_mutations:
            self.mutations[mutation.id] = mutation

    def _add_rollback_mutations(self):
        """Add rollback-related mutations."""
        rollback_mutations = [
            Mutation(
                id="rollback_001",
                name="incomplete_drop",
                description="Don't drop all created objects",
                category=MutationCategory.ROLLBACK,
                severity=MutationSeverity.CRITICAL,
                apply_regex=r"DROP\s+TABLE" + "=>" + "-- DROP TABLE",
            ),
            Mutation(
                id="rollback_002",
                name="skip_data_restore",
                description="Skip restoring backup data",
                category=MutationCategory.ROLLBACK,
                severity=MutationSeverity.CRITICAL,
                apply_regex=r"INSERT\s+INTO.*backup" + "=>" + "-- RESTORE (skipped)",
            ),
            Mutation(
                id="rollback_003",
                name="partial_rollback",
                description="Rollback only partially",
                category=MutationCategory.ROLLBACK,
                severity=MutationSeverity.CRITICAL,
                apply_fn=lambda sql: sql.replace("DROP COLUMN", "-- DROP COLUMN"),
            ),
            Mutation(
                id="rollback_004",
                name="wrong_constraint_restoration",
                description="Restore wrong constraint definition",
                category=MutationCategory.ROLLBACK,
                severity=MutationSeverity.IMPORTANT,
                apply_fn=lambda sql: sql,  # Complex to implement
            ),
            Mutation(
                id="rollback_005",
                name="skip_index_drop",
                description="Don't drop indexes when rolling back",
                category=MutationCategory.ROLLBACK,
                severity=MutationSeverity.IMPORTANT,
                apply_regex=r"DROP\s+INDEX" + "=>" + "-- DROP INDEX",
            ),
        ]

        for mutation in rollback_mutations:
            self.mutations[mutation.id] = mutation

    def _add_performance_mutations(self):
        """Add performance-related mutations."""
        performance_mutations = [
            Mutation(
                id="perf_001",
                name="missing_index",
                description="Skip index that should be created",
                category=MutationCategory.PERFORMANCE,
                severity=MutationSeverity.IMPORTANT,
                apply_regex=r"CREATE\s+INDEX" + "=>" + "-- CREATE INDEX (skipped)",
            ),
            Mutation(
                id="perf_002",
                name="inefficient_join",
                description="Use inefficient JOIN instead of WHERE",
                category=MutationCategory.PERFORMANCE,
                severity=MutationSeverity.IMPORTANT,
                apply_fn=lambda sql: sql,  # Complex implementation
            ),
            Mutation(
                id="perf_003",
                name="missing_bulk_operation",
                description="Process rows one by one instead of bulk",
                category=MutationCategory.PERFORMANCE,
                severity=MutationSeverity.IMPORTANT,
                apply_fn=lambda sql: sql,  # Complex implementation
            ),
            Mutation(
                id="perf_004",
                name="scan_full_table",
                description="Scan entire table instead of using index",
                category=MutationCategory.PERFORMANCE,
                severity=MutationSeverity.IMPORTANT,
                apply_fn=lambda sql: sql.replace("WHERE id =", "WHERE TRUE")
                if "WHERE id =" in sql
                else sql,
            ),
        ]

        for mutation in performance_mutations:
            self.mutations[mutation.id] = mutation

    def get_mutation(self, mutation_id: str) -> Mutation | None:
        """Get a specific mutation by ID."""
        return self.mutations.get(mutation_id)

    def get_by_category(self, category: MutationCategory) -> list[Mutation]:
        """Get all mutations in a category."""
        return [m for m in self.mutations.values() if m.category == category]

    def get_by_severity(self, severity: MutationSeverity) -> list[Mutation]:
        """Get all mutations of a severity level."""
        return [m for m in self.mutations.values() if m.severity == severity]

    def list_all(self) -> list[Mutation]:
        """Get all mutations."""
        return list(self.mutations.values())


class MutationRunner:
    """Execute migrations with mutations applied."""

    def __init__(self, db_connection: psycopg.Connection, migrations_dir: Path):
        self.connection = db_connection
        self.migrations_dir = migrations_dir
        self.registry = MutationRegistry()
        self.test_results: list[MutationTestResult] = []

    def run_migration_with_mutation(
        self,
        migration_name: str,
        mutation: Mutation,
    ) -> MutationResult:
        """Execute migration with a mutation applied."""
        try:
            # Load migration SQL
            migration_file = self.migrations_dir / f"{migration_name}.sql"
            if not migration_file.exists():
                raise FileNotFoundError(f"Migration not found: {migration_file}")

            with open(migration_file) as f:
                original_sql = f.read()

            # Apply mutation
            mutated_sql = mutation.apply(original_sql)
            mutation_applied = mutated_sql != original_sql

            # Execute mutated migration
            if not mutation_applied:
                # Mutation couldn't be applied
                return MutationResult(
                    mutation_id=mutation.id,
                    success=False,
                    mutation_applied=False,
                    duration_seconds=0.0,
                    stdout="",
                    stderr="Mutation could not be applied to SQL",
                )

            # Execute in isolated transaction
            import time

            start_time = time.time()

            try:
                with self.connection.cursor() as cur:
                    cur.execute(mutated_sql)
                    self.connection.commit()

                duration = time.time() - start_time

                return MutationResult(
                    mutation_id=mutation.id,
                    success=True,
                    mutation_applied=True,
                    duration_seconds=duration,
                    stdout=f"Mutation {mutation.id} executed successfully",
                    stderr="",
                )

            except Exception as e:
                self.connection.rollback()
                duration = time.time() - start_time

                return MutationResult(
                    mutation_id=mutation.id,
                    success=False,
                    mutation_applied=True,
                    duration_seconds=duration,
                    stdout="",
                    stderr=str(e),
                    error=e,
                )

        except Exception as e:
            return MutationResult(
                mutation_id=mutation.id,
                success=False,
                mutation_applied=False,
                duration_seconds=0.0,
                stdout="",
                stderr=str(e),
                error=e,
            )

    def record_test_result(
        self,
        mutation_id: str,
        mutation_name: str,
        test_name: str,
        caught: bool,
        duration: float,
    ):
        """Record test result for a mutation."""
        result = MutationTestResult(
            mutation_id=mutation_id,
            mutation_name=mutation_name,
            test_name=test_name,
            caught=caught,
            duration_seconds=duration,
        )
        self.test_results.append(result)

    def generate_report(self) -> MutationReport:
        """Generate comprehensive mutation report."""
        from datetime import datetime

        # Calculate metrics
        total = len(self.registry.list_all())
        killed = sum(1 for r in self.test_results if r.caught)
        survived = total - killed

        metrics = MutationMetrics(
            total_mutations=total,
            killed_mutations=killed,
            survived_mutations=survived,
        )

        # Generate recommendations
        recommendations = self._generate_recommendations()

        report = MutationReport(
            timestamp=datetime.now().isoformat(),
            total_mutations=total,
            metrics=metrics,
            recommendations=recommendations,
        )

        return report

    def _generate_recommendations(self) -> list[str]:
        """Generate recommendations based on test results."""
        recommendations = []

        if self.test_results:
            # Find weak tests
            test_catches = {}
            for result in self.test_results:
                if result.test_name not in test_catches:
                    test_catches[result.test_name] = {"caught": 0, "total": 0}
                test_catches[result.test_name]["total"] += 1
                if result.caught:
                    test_catches[result.test_name]["caught"] += 1

            # Identify tests that catch < 50% of mutations
            for test_name, stats in test_catches.items():
                catch_rate = stats["caught"] / stats["total"]
                if catch_rate < 0.5:
                    recommendations.append(
                        f"Test '{test_name}' has low mutation kill rate ({catch_rate * 100:.0f}%). "
                        f"Consider adding more assertions or validations."
                    )

        return recommendations

    def export_report(self, report: MutationReport, path: Path):
        """Export report to file."""
        with open(path, "w") as f:
            json.dump(report.to_dict(), f, indent=2)
