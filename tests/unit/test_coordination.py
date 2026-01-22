"""Unit tests for multi-agent coordination.

Tests for Intent registry, conflict detection, and coordination models.
These tests do NOT require a database - models and detection logic are tested in isolation.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from confiture.integrations.pggit.coordination import (
    ConflictDetector,
    ConflictReport,
    ConflictSeverity,
    ConflictType,
    Intent,
    IntentStatus,
    RiskLevel,
)


class TestIntentModels:
    """Test Intent dataclass and serialization."""

    def test_create_intent_with_defaults(self):
        """Intent should create with required fields and defaults."""
        intent = Intent(
            agent_id="agent_a",
            feature_name="feature_x",
            schema_changes=["ALTER TABLE users ADD COLUMN x TEXT"],
            tables_affected=["users"],
        )

        assert intent.agent_id == "agent_a"
        assert intent.feature_name == "feature_x"
        assert intent.status == IntentStatus.REGISTERED
        assert intent.risk_level == RiskLevel.LOW
        assert len(intent.id) > 0
        assert intent.conflicts_with == []

    def test_intent_to_dict(self):
        """Intent should serialize to dictionary."""
        intent = Intent(
            agent_id="agent_a",
            feature_name="test",
            schema_changes=["CREATE TABLE test (id INT)"],
            tables_affected=["test"],
            risk_level=RiskLevel.MEDIUM,
        )

        data = intent.to_dict()

        assert data["agent_id"] == "agent_a"
        assert data["feature_name"] == "test"
        assert data["risk_level"] == "medium"
        assert data["status"] == "registered"

    def test_intent_from_dict(self):
        """Intent should deserialize from dictionary."""
        data = {
            "agent_id": "agent_b",
            "feature_name": "feature_y",
            "schema_changes": ["DROP TABLE old"],
            "tables_affected": ["old"],
            "risk_level": "high",
            "status": "in_progress",
        }

        intent = Intent.from_dict(data)

        assert intent.agent_id == "agent_b"
        assert intent.feature_name == "feature_y"
        assert intent.risk_level == RiskLevel.HIGH
        assert intent.status == IntentStatus.IN_PROGRESS


class TestConflictReportModels:
    """Test ConflictReport dataclass and serialization."""

    def test_create_conflict_report(self):
        """ConflictReport should store all fields."""
        report = ConflictReport(
            intent_a="intent_1",
            intent_b="intent_2",
            conflict_type=ConflictType.TABLE,
            affected_objects=["users"],
            severity=ConflictSeverity.WARNING,
            resolution_suggestions=["Coordinate with agent B"],
        )

        assert report.intent_a == "intent_1"
        assert report.intent_b == "intent_2"
        assert report.conflict_type == ConflictType.TABLE
        assert "users" in report.affected_objects
        assert len(report.resolution_suggestions) > 0

    def test_conflict_report_to_dict(self):
        """ConflictReport should serialize to dictionary."""
        report = ConflictReport(
            intent_a="int_1",
            intent_b="int_2",
            conflict_type=ConflictType.COLUMN,
            affected_objects=["users.email"],
            severity=ConflictSeverity.ERROR,
        )

        data = report.to_dict()

        assert data["intent_a"] == "int_1"
        assert data["conflict_type"] == "column"
        assert data["severity"] == "error"

    def test_conflict_report_from_dict(self):
        """ConflictReport should deserialize from dictionary."""
        data = {
            "intent_a": "int_a",
            "intent_b": "int_b",
            "conflict_type": "function",
            "severity": "warning",
            "affected_objects": ["calc_total"],
        }

        report = ConflictReport.from_dict(data)

        assert report.intent_a == "int_a"
        assert report.conflict_type == ConflictType.FUNCTION
        assert report.severity == ConflictSeverity.WARNING


class TestConflictDetectorTableConflicts:
    """Test conflict detection for table modifications."""

    def test_detect_same_table_conflict(self):
        """Should detect when two intents modify the same table."""
        detector = ConflictDetector()

        intent_a = Intent(
            agent_id="agent_a",
            feature_name="feature_a",
            schema_changes=["ALTER TABLE users ADD COLUMN stripe_id TEXT"],
            tables_affected=["users"],
        )

        intent_b = Intent(
            agent_id="agent_b",
            feature_name="feature_b",
            schema_changes=["ALTER TABLE users ADD COLUMN phone TEXT"],
            tables_affected=["users"],
        )

        conflicts = detector.detect_conflicts(intent_a, intent_b)

        assert len(conflicts) > 0
        assert conflicts[0].conflict_type == ConflictType.TABLE
        assert "users" in conflicts[0].affected_objects

    def test_no_conflict_different_tables(self):
        """Should NOT detect conflict when intents modify different tables."""
        detector = ConflictDetector()

        intent_a = Intent(
            agent_id="agent_a",
            feature_name="feature_a",
            schema_changes=["ALTER TABLE users ADD COLUMN x TEXT"],
            tables_affected=["users"],
        )

        intent_b = Intent(
            agent_id="agent_b",
            feature_name="feature_b",
            schema_changes=["ALTER TABLE orders ADD COLUMN y TEXT"],
            tables_affected=["orders"],
        )

        conflicts = detector.detect_conflicts(intent_a, intent_b)

        assert len(conflicts) == 0

    def test_same_agent_no_conflict(self):
        """Should NOT detect conflict for same agent."""
        detector = ConflictDetector()

        intent_a = Intent(
            agent_id="agent_a",
            feature_name="feature_a",
            schema_changes=["ALTER TABLE users ADD COLUMN x TEXT"],
            tables_affected=["users"],
        )

        intent_b = Intent(
            agent_id="agent_a",  # Same agent
            feature_name="feature_b",
            schema_changes=["ALTER TABLE users ADD COLUMN y TEXT"],
            tables_affected=["users"],
        )

        conflicts = detector.detect_conflicts(intent_a, intent_b)

        assert len(conflicts) == 0


class TestConflictDetectorColumnConflicts:
    """Test conflict detection for column modifications."""

    def test_detect_column_conflict(self):
        """Should detect when two intents modify same column."""
        detector = ConflictDetector()

        intent_a = Intent(
            agent_id="agent_a",
            feature_name="feature_a",
            schema_changes=["ALTER TABLE users ADD COLUMN email TEXT"],
            tables_affected=["users"],
        )

        intent_b = Intent(
            agent_id="agent_b",
            feature_name="feature_b",
            schema_changes=["ALTER TABLE users ADD COLUMN email VARCHAR(255)"],
            tables_affected=["users"],
        )

        conflicts = detector.detect_conflicts(intent_a, intent_b)

        # Should have column conflict
        column_conflicts = [c for c in conflicts if c.conflict_type == ConflictType.COLUMN]
        assert len(column_conflicts) > 0


class TestConflictDetectorFunctionConflicts:
    """Test conflict detection for function modifications."""

    def test_detect_function_conflict(self):
        """Should detect when two intents modify same function."""
        detector = ConflictDetector()

        intent_a = Intent(
            agent_id="agent_a",
            feature_name="feature_a",
            schema_changes=["CREATE FUNCTION calculate_total() RETURNS INT AS $$ SELECT 1 $$ LANGUAGE SQL"],
            tables_affected=[],
        )

        intent_b = Intent(
            agent_id="agent_b",
            feature_name="feature_b",
            schema_changes=["DROP FUNCTION calculate_total"],
            tables_affected=[],
        )

        conflicts = detector.detect_conflicts(intent_a, intent_b)

        function_conflicts = [c for c in conflicts if c.conflict_type == ConflictType.FUNCTION]
        assert len(function_conflicts) > 0


class TestConflictDetectorSuggestions:
    """Test suggestion generation for conflicts."""

    def test_generate_table_conflict_suggestions(self):
        """Should generate helpful suggestions for table conflicts."""
        detector = ConflictDetector()

        intent_a = Intent(
            agent_id="agent_a",
            feature_name="payments",
            schema_changes=["ALTER TABLE users ADD COLUMN stripe_id TEXT"],
            tables_affected=["users"],
        )

        intent_b = Intent(
            agent_id="agent_b",
            feature_name="auth",
            schema_changes=["ALTER TABLE users ADD COLUMN mfa_enabled BOOLEAN"],
            tables_affected=["users"],
        )

        conflicts = detector.detect_conflicts(intent_a, intent_b)

        assert len(conflicts) > 0
        assert len(conflicts[0].resolution_suggestions) > 0

        # Suggestions should mention both agents
        suggestions_text = " ".join(conflicts[0].resolution_suggestions)
        assert "auth" in suggestions_text or "agent_b" in suggestions_text or "coordinate" in suggestions_text.lower()

    def test_generate_column_conflict_suggestions(self):
        """Should generate urgent suggestions for column conflicts."""
        detector = ConflictDetector()

        intent_a = Intent(
            agent_id="agent_a",
            feature_name="feature_a",
            schema_changes=["ALTER TABLE users ADD COLUMN email TEXT"],
            tables_affected=["users"],
        )

        intent_b = Intent(
            agent_id="agent_b",
            feature_name="feature_b",
            schema_changes=["ALTER TABLE users ADD COLUMN email VARCHAR(255)"],
            tables_affected=["users"],
        )

        conflicts = detector.detect_conflicts(intent_a, intent_b)

        # Find column conflict
        column_conflicts = [c for c in conflicts if c.conflict_type == ConflictType.COLUMN]
        assert len(column_conflicts) > 0

        suggestions = column_conflicts[0].resolution_suggestions
        # Column conflicts should have urgent language
        suggestions_text = " ".join(suggestions).lower()
        assert "high" in suggestions_text or "urgent" in suggestions_text or "coordinate" in suggestions_text


class TestConflictDetectorParsing:
    """Test DDL parsing utility methods."""

    def test_extract_tables_from_changes(self):
        """Should extract table names from DDL."""
        detector = ConflictDetector()

        changes = [
            "CREATE TABLE users (id INT)",
            "ALTER TABLE orders ADD COLUMN status TEXT",
            "DROP TABLE old_table",
        ]

        tables = detector._extract_tables_from_changes(changes)

        assert "users" in tables
        assert "orders" in tables
        assert "old_table" in tables

    def test_extract_functions_from_changes(self):
        """Should extract function names from DDL."""
        detector = ConflictDetector()

        changes = [
            "CREATE FUNCTION calculate_total() RETURNS INT",
            "ALTER FUNCTION calc_avg(numeric) RETURNS numeric",
        ]

        functions = detector._extract_functions_from_changes(changes)

        assert "calculate_total" in functions
        assert "calc_avg" in functions

    def test_extract_columns_from_changes(self):
        """Should extract column specifications from DDL."""
        detector = ConflictDetector()

        changes = [
            "ALTER TABLE users ADD COLUMN email TEXT",
            "ALTER TABLE users DROP COLUMN phone",
        ]

        columns = detector._extract_columns_from_changes(changes)

        assert len(columns) > 0

    def test_parse_schema_changes(self):
        """Should categorize schema changes."""
        detector = ConflictDetector()

        changes = [
            "CREATE TABLE new_table (id INT)",
            "CREATE FUNCTION calc() RETURNS INT",
            "CREATE INDEX idx_user_email ON users(email)",
            "ALTER TABLE users ADD COLUMN x TEXT",
            "GRANT SELECT ON users TO public",  # Won't match any pattern
        ]

        parsed = detector.parse_schema_changes(changes)

        assert len(parsed["tables"]) > 0
        assert len(parsed["functions"]) > 0
        assert len(parsed["indexes"]) > 0
        assert len(parsed["other"]) > 0


class TestConflictDetectorMultiIntent:
    """Test conflict detection with multiple intents."""

    def test_three_intents_with_transitive_conflicts(self):
        """Should detect transitive conflicts (A conflicts with B and C)."""
        detector = ConflictDetector()

        intent_a = Intent(
            agent_id="agent_a",
            feature_name="users_updates",
            schema_changes=["ALTER TABLE users ADD COLUMN x TEXT"],
            tables_affected=["users"],
        )

        intent_b = Intent(
            agent_id="agent_b",
            feature_name="users_auth",
            schema_changes=["ALTER TABLE users ADD COLUMN mfa TEXT"],
            tables_affected=["users"],
        )

        intent_c = Intent(
            agent_id="agent_c",
            feature_name="orders_updates",
            schema_changes=["ALTER TABLE orders ADD COLUMN user_ref INT"],
            tables_affected=["orders"],
        )

        # A and B conflict (same table)
        conflicts_ab = detector.detect_conflicts(intent_a, intent_b)
        assert len(conflicts_ab) > 0

        # B and C don't conflict (different tables)
        conflicts_bc = detector.detect_conflicts(intent_b, intent_c)
        assert len(conflicts_bc) == 0

        # A and C don't conflict (different tables)
        conflicts_ac = detector.detect_conflicts(intent_a, intent_c)
        assert len(conflicts_ac) == 0


class TestEnumValues:
    """Test enum definitions."""

    def test_intent_status_values(self):
        """IntentStatus should have all required values."""
        statuses = [s.value for s in IntentStatus]

        assert "registered" in statuses
        assert "in_progress" in statuses
        assert "completed" in statuses
        assert "merged" in statuses
        assert "abandoned" in statuses
        assert "conflicted" in statuses

    def test_conflict_type_values(self):
        """ConflictType should have all required types."""
        types = [t.value for t in ConflictType]

        assert "table" in types
        assert "column" in types
        assert "function" in types
        assert "index" in types

    def test_conflict_severity_values(self):
        """ConflictSeverity should have required values."""
        severities = [s.value for s in ConflictSeverity]

        assert "warning" in severities
        assert "error" in severities

    def test_risk_level_values(self):
        """RiskLevel should have required values."""
        levels = [l.value for l in RiskLevel]

        assert "low" in levels
        assert "medium" in levels
        assert "high" in levels


class TestConflictDetectorEdgeCases:
    """Test edge cases in conflict detection."""

    def test_empty_schema_changes(self):
        """Should handle intents with empty schema changes."""
        detector = ConflictDetector()

        intent_a = Intent(
            agent_id="agent_a",
            feature_name="feature_a",
            schema_changes=[],
            tables_affected=[],
        )

        intent_b = Intent(
            agent_id="agent_b",
            feature_name="feature_b",
            schema_changes=[],
            tables_affected=[],
        )

        conflicts = detector.detect_conflicts(intent_a, intent_b)
        assert isinstance(conflicts, list)

    def test_malformed_ddl(self):
        """Should handle malformed DDL gracefully."""
        detector = ConflictDetector()

        intent_a = Intent(
            agent_id="agent_a",
            feature_name="feature_a",
            schema_changes=["This is not valid DDL"],
            tables_affected=["users"],
        )

        intent_b = Intent(
            agent_id="agent_b",
            feature_name="feature_b",
            schema_changes=["ALTER TABLE users ADD COLUMN x TEXT"],
            tables_affected=["users"],
        )

        conflicts = detector.detect_conflicts(intent_a, intent_b)
        # Should detect table conflict regardless of DDL validity
        assert len(conflicts) > 0

    def test_duplicate_detection(self):
        """Should not report same conflict twice."""
        detector = ConflictDetector()

        intent_a = Intent(
            agent_id="agent_a",
            feature_name="feature_a",
            schema_changes=["ALTER TABLE users ADD COLUMN x TEXT"],
            tables_affected=["users"],
        )

        intent_b = Intent(
            agent_id="agent_b",
            feature_name="feature_b",
            schema_changes=["ALTER TABLE users ADD COLUMN y TEXT"],
            tables_affected=["users"],
        )

        conflicts = detector.detect_conflicts(intent_a, intent_b)

        # Should not have duplicate table conflicts
        table_conflicts = [c for c in conflicts if c.conflict_type == ConflictType.TABLE]
        assert len(table_conflicts) <= 1
