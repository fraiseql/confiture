"""Conflict detection for multi-agent coordination.

Analyzes schema changes from multiple agents to detect conflicts
before code is written.
"""

from __future__ import annotations

import re

from confiture.integrations.pggit.coordination.models import (
    ConflictReport,
    ConflictSeverity,
    ConflictType,
    Intent,
)


class ConflictDetector:
    """Detects conflicts between agent intents.

    This detector analyzes schema changes to identify:
    - Same-table conflicts
    - Column conflicts
    - Constraint conflicts
    - Function conflicts
    - Dependency conflicts
    """

    def __init__(self):
        """Initialize conflict detector."""
        self._table_pattern = re.compile(
            r"(?:CREATE|ALTER|DROP)\s+TABLE\s+(?:IF\s+EXISTS\s+)?(\w+)", re.IGNORECASE
        )
        self._column_pattern = re.compile(
            r"ALTER\s+TABLE\s+(\w+)\s+(?:ADD|DROP)\s+COLUMN\s+(\w+)", re.IGNORECASE
        )
        self._constraint_pattern = re.compile(
            r"(?:ADD|DROP)\s+(?:PRIMARY\s+KEY|FOREIGN\s+KEY|UNIQUE|CHECK|DEFAULT)", re.IGNORECASE
        )
        self._function_pattern = re.compile(
            r"(?:CREATE|ALTER|DROP)\s+FUNCTION\s+(?:IF\s+EXISTS\s+)?(\w+)", re.IGNORECASE
        )
        self._index_pattern = re.compile(
            r"(?:CREATE|DROP)\s+(?:UNIQUE\s+)?INDEX\s+(?:IF\s+EXISTS\s+)?(\w+)", re.IGNORECASE
        )

    def detect_conflicts(
        self,
        intent_a: Intent,
        intent_b: Intent,
    ) -> list[ConflictReport]:
        """Detect all conflicts between two intents.

        Args:
            intent_a: First intent
            intent_b: Second intent

        Returns:
            List of ConflictReport objects
        """
        conflicts: list[ConflictReport] = []

        # Same agent - no conflict
        if intent_a.agent_id == intent_b.agent_id:
            return conflicts

        # Check table conflicts
        table_conflicts = self._detect_table_conflicts(intent_a, intent_b)
        conflicts.extend(table_conflicts)

        # Check column conflicts
        column_conflicts = self._detect_column_conflicts(intent_a, intent_b)
        conflicts.extend(column_conflicts)

        # Check function conflicts
        function_conflicts = self._detect_function_conflicts(intent_a, intent_b)
        conflicts.extend(function_conflicts)

        # Check index conflicts
        index_conflicts = self._detect_index_conflicts(intent_a, intent_b)
        conflicts.extend(index_conflicts)

        # Check constraint conflicts
        constraint_conflicts = self._detect_constraint_conflicts(intent_a, intent_b)
        conflicts.extend(constraint_conflicts)

        # Add suggestions to all conflicts
        for conflict in conflicts:
            conflict.resolution_suggestions = self._generate_suggestions(
                conflict, intent_a, intent_b
            )

        return conflicts

    def _detect_table_conflicts(
        self,
        intent_a: Intent,
        intent_b: Intent,
    ) -> list[ConflictReport]:
        """Detect conflicts when intents affect the same table."""
        conflicts: list[ConflictReport] = []

        # Find overlapping tables
        tables_a = set(intent_a.tables_affected)
        tables_b = set(intent_b.tables_affected)
        overlapping = tables_a & tables_b

        if overlapping:
            conflict = ConflictReport(
                intent_a=intent_a.id,
                intent_b=intent_b.id,
                conflict_type=ConflictType.TABLE,
                affected_objects=list(overlapping),
                severity=ConflictSeverity.WARNING,
            )
            conflicts.append(conflict)

        return conflicts

    def _detect_column_conflicts(
        self,
        intent_a: Intent,
        intent_b: Intent,
    ) -> list[ConflictReport]:
        """Detect conflicts when intents modify same columns."""
        conflicts: list[ConflictReport] = []

        # Extract columns from schema changes
        columns_a = self._extract_columns_from_changes(intent_a.schema_changes)
        columns_b = self._extract_columns_from_changes(intent_b.schema_changes)

        # Find overlapping columns
        overlapping = columns_a & columns_b

        if overlapping:
            conflict = ConflictReport(
                intent_a=intent_a.id,
                intent_b=intent_b.id,
                conflict_type=ConflictType.COLUMN,
                affected_objects=list(overlapping),
                severity=ConflictSeverity.ERROR,
            )
            conflicts.append(conflict)

        return conflicts

    def _detect_function_conflicts(
        self,
        intent_a: Intent,
        intent_b: Intent,
    ) -> list[ConflictReport]:
        """Detect conflicts when intents affect the same functions."""
        conflicts: list[ConflictReport] = []

        functions_a = self._extract_functions_from_changes(intent_a.schema_changes)
        functions_b = self._extract_functions_from_changes(intent_b.schema_changes)

        overlapping = functions_a & functions_b

        if overlapping:
            conflict = ConflictReport(
                intent_a=intent_a.id,
                intent_b=intent_b.id,
                conflict_type=ConflictType.FUNCTION,
                affected_objects=list(overlapping),
                severity=ConflictSeverity.ERROR,
            )
            conflicts.append(conflict)

        return conflicts

    def _detect_index_conflicts(
        self,
        intent_a: Intent,
        intent_b: Intent,
    ) -> list[ConflictReport]:
        """Detect conflicts when intents affect the same indexes."""
        conflicts: list[ConflictReport] = []

        indexes_a = self._extract_indexes_from_changes(intent_a.schema_changes)
        indexes_b = self._extract_indexes_from_changes(intent_b.schema_changes)

        overlapping = indexes_a & indexes_b

        if overlapping:
            conflict = ConflictReport(
                intent_a=intent_a.id,
                intent_b=intent_b.id,
                conflict_type=ConflictType.INDEX,
                affected_objects=list(overlapping),
                severity=ConflictSeverity.WARNING,
            )
            conflicts.append(conflict)

        return conflicts

    def _detect_constraint_conflicts(
        self,
        intent_a: Intent,
        intent_b: Intent,
    ) -> list[ConflictReport]:
        """Detect conflicts when intents affect constraints on same table."""
        conflicts: list[ConflictReport] = []

        # If both modify same tables AND both have constraint operations
        tables_a = set(intent_a.tables_affected)
        tables_b = set(intent_b.tables_affected)
        overlapping_tables = tables_a & tables_b

        if overlapping_tables:
            has_constraint_a = any(
                self._constraint_pattern.search(change) for change in intent_a.schema_changes
            )
            has_constraint_b = any(
                self._constraint_pattern.search(change) for change in intent_b.schema_changes
            )

            if has_constraint_a and has_constraint_b:
                conflict = ConflictReport(
                    intent_a=intent_a.id,
                    intent_b=intent_b.id,
                    conflict_type=ConflictType.CONSTRAINT,
                    affected_objects=list(overlapping_tables),
                    severity=ConflictSeverity.WARNING,
                )
                conflicts.append(conflict)

        return conflicts

    def _extract_columns_from_changes(self, schema_changes: list[str]) -> set[str]:
        """Extract column names from schema changes."""
        columns = set()
        for change in schema_changes:
            matches = self._column_pattern.findall(change)
            for match in matches:
                if isinstance(match, tuple):
                    columns.add(f"{match[0]}.{match[1]}")
                else:
                    columns.add(match)
        return columns

    def _extract_functions_from_changes(self, schema_changes: list[str]) -> set[str]:
        """Extract function names from schema changes."""
        functions = set()
        for change in schema_changes:
            matches = self._function_pattern.findall(change)
            functions.update(matches)
        return functions

    def _extract_indexes_from_changes(self, schema_changes: list[str]) -> set[str]:
        """Extract index names from schema changes."""
        indexes = set()
        for change in schema_changes:
            matches = self._index_pattern.findall(change)
            indexes.update(matches)
        return indexes

    def _extract_tables_from_changes(self, schema_changes: list[str]) -> set[str]:
        """Extract table names from schema changes."""
        tables = set()
        for change in schema_changes:
            matches = self._table_pattern.findall(change)
            tables.update(matches)
        return tables

    def _generate_suggestions(
        self,
        conflict: ConflictReport,
        _intent_a: Intent,
        intent_b: Intent,
    ) -> list[str]:
        """Generate suggestions for resolving a conflict.

        Args:
            conflict: The conflict report
            _intent_a: First intent
            intent_b: Second intent

        Returns:
            List of suggestion strings
        """
        suggestions: list[str] = []

        if conflict.conflict_type == ConflictType.TABLE:
            suggestions.append(
                f"Both agents are modifying tables: {', '.join(conflict.affected_objects)}"
            )
            suggestions.append(
                f"Consider coordinating with {intent_b.agent_id} ({intent_b.feature_name})"
            )
            suggestions.append("You could apply changes sequentially or divide responsibilities")

        elif conflict.conflict_type == ConflictType.COLUMN:
            suggestions.append(
                f"Both agents are modifying columns: {', '.join(conflict.affected_objects)}"
            )
            suggestions.append("This is a high-priority conflict - coordinate immediately")
            suggestions.append("Consider combining your changes into a single migration")

        elif conflict.conflict_type == ConflictType.FUNCTION:
            suggestions.append(
                f"Both agents are modifying functions: {', '.join(conflict.affected_objects)}"
            )
            suggestions.append("Coordinate to avoid function signature conflicts")
            suggestions.append(
                "One agent should update the function, the other should adjust calls"
            )

        elif conflict.conflict_type == ConflictType.INDEX:
            suggestions.append(
                f"Both agents are creating indexes on: {', '.join(conflict.affected_objects)}"
            )
            suggestions.append("Consider having one agent create indexes for both features")
            suggestions.append("This is low priority if different index strategies are used")

        elif conflict.conflict_type == ConflictType.CONSTRAINT:
            suggestions.append(
                f"Both agents are modifying constraints on: {', '.join(conflict.affected_objects)}"
            )
            suggestions.append("Coordinate to ensure constraint compatibility")
            suggestions.append("Test merge carefully to catch constraint violations")

        # General suggestions
        if len(suggestions) == 0:
            suggestions.append("Coordinate with the other agent on timing and scope")

        suggestions.append(
            f"Severity: {conflict.severity.value} - {'Proceed with caution' if conflict.severity == ConflictSeverity.ERROR else 'Can proceed with coordination'}"
        )

        return suggestions

    def parse_schema_changes(self, changes: list[str]) -> dict[str, list[str]]:
        """Parse schema changes into categorized operations.

        Args:
            changes: List of DDL statements

        Returns:
            Dictionary with keys: 'tables', 'functions', 'indexes', 'other'
        """
        result: dict[str, list[str]] = {
            "tables": [],
            "functions": [],
            "indexes": [],
            "other": [],
        }

        for change in changes:
            if self._table_pattern.search(change):
                result["tables"].append(change)
            elif self._function_pattern.search(change):
                result["functions"].append(change)
            elif self._index_pattern.search(change):
                result["indexes"].append(change)
            else:
                result["other"].append(change)

        return result
