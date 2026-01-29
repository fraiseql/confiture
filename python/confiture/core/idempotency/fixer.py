"""Auto-fix transformations for non-idempotent SQL.

This module provides the IdempotencyFixer class which transforms
non-idempotent SQL statements into their idempotent equivalents.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from confiture.core.idempotency.models import IdempotencyPattern
from confiture.core.idempotency.patterns import detect_non_idempotent_patterns


@dataclass
class FixChange:
    """Represents a proposed fix for a non-idempotent pattern.

    Attributes:
        pattern: The type of pattern being fixed
        original: The original SQL snippet
        suggested_fix: The idempotent replacement
        line_number: Line number where the change would occur
    """

    pattern: IdempotencyPattern
    original: str
    suggested_fix: str
    line_number: int


class IdempotencyFixer:
    """Transforms non-idempotent SQL into idempotent equivalents.

    Applies transformations like:
    - CREATE TABLE → CREATE TABLE IF NOT EXISTS
    - CREATE INDEX → CREATE INDEX IF NOT EXISTS
    - CREATE FUNCTION → CREATE OR REPLACE FUNCTION
    - DROP TABLE → DROP TABLE IF EXISTS

    Example:
        >>> fixer = IdempotencyFixer()
        >>> sql = "CREATE TABLE users (id INT);"
        >>> result = fixer.fix(sql)
        >>> print(result)
        CREATE TABLE IF NOT EXISTS users (id INT);
    """

    def __init__(
        self,
        fix_patterns: list[IdempotencyPattern] | None = None,
    ):
        """Initialize the fixer.

        Args:
            fix_patterns: Only fix these patterns. If None, fix all patterns.
        """
        self.fix_patterns = set(fix_patterns) if fix_patterns else None

    def fix(self, sql: str) -> str:
        """Apply all idempotency fixes to SQL.

        Args:
            sql: The SQL to fix

        Returns:
            SQL with non-idempotent patterns transformed to idempotent equivalents

        Example:
            >>> fixer = IdempotencyFixer()
            >>> fixer.fix("CREATE TABLE users (id INT);")
            'CREATE TABLE IF NOT EXISTS users (id INT);'
        """
        result = sql

        # Apply fixes in order of specificity (more specific patterns first)
        # to avoid conflicts

        # CREATE UNIQUE INDEX before CREATE INDEX
        result = self._fix_create_unique_index(result)
        result = self._fix_create_index(result)
        result = self._fix_create_index_concurrently(result)

        # CREATE statements
        result = self._fix_create_table(result)
        result = self._fix_create_function(result)
        result = self._fix_create_procedure(result)
        result = self._fix_create_view(result)
        result = self._fix_create_extension(result)
        result = self._fix_create_schema(result)
        result = self._fix_create_sequence(result)

        # ALTER statements
        result = self._fix_alter_table_add_column(result)

        # DROP statements
        result = self._fix_drop_table(result)
        result = self._fix_drop_index(result)
        result = self._fix_drop_function(result)
        result = self._fix_drop_view(result)
        result = self._fix_drop_type(result)
        result = self._fix_drop_schema(result)
        result = self._fix_drop_sequence(result)

        return result

    def dry_run(self, sql: str) -> list[FixChange]:
        """Report what fixes would be applied without modifying SQL.

        Args:
            sql: The SQL to analyze

        Returns:
            List of FixChange objects describing proposed fixes

        Example:
            >>> fixer = IdempotencyFixer()
            >>> changes = fixer.dry_run("CREATE TABLE users (id INT);")
            >>> changes[0].pattern
            <IdempotencyPattern.CREATE_TABLE: 'CREATE_TABLE'>
        """
        changes: list[FixChange] = []
        matches = detect_non_idempotent_patterns(sql)

        for match in matches:
            if self.fix_patterns and match.pattern not in self.fix_patterns:
                continue

            suggested_fix = self._get_suggested_fix(match.pattern, match.sql_snippet)
            changes.append(
                FixChange(
                    pattern=match.pattern,
                    original=match.sql_snippet,
                    suggested_fix=suggested_fix,
                    line_number=match.line_number,
                )
            )

        return changes

    def _should_fix(self, pattern: IdempotencyPattern) -> bool:
        """Check if a pattern should be fixed based on configuration."""
        if self.fix_patterns is None:
            return True
        return pattern in self.fix_patterns

    def _get_suggested_fix(self, pattern: IdempotencyPattern, original: str) -> str:
        """Get the suggested fix for a pattern."""
        # Apply the specific fix and return the result
        fix_methods = {
            IdempotencyPattern.CREATE_TABLE: self._fix_create_table,
            IdempotencyPattern.CREATE_INDEX: self._fix_create_index,
            IdempotencyPattern.CREATE_UNIQUE_INDEX: self._fix_create_unique_index,
            IdempotencyPattern.CREATE_FUNCTION: self._fix_create_function,
            IdempotencyPattern.CREATE_PROCEDURE: self._fix_create_procedure,
            IdempotencyPattern.CREATE_VIEW: self._fix_create_view,
            IdempotencyPattern.DROP_TABLE: self._fix_drop_table,
            IdempotencyPattern.DROP_INDEX: self._fix_drop_index,
            IdempotencyPattern.DROP_FUNCTION: self._fix_drop_function,
            IdempotencyPattern.DROP_VIEW: self._fix_drop_view,
            IdempotencyPattern.ALTER_TABLE_ADD_COLUMN: self._fix_alter_table_add_column,
        }
        fix_method = fix_methods.get(pattern)
        if fix_method:
            return fix_method(original)
        return original

    def _fix_create_table(self, sql: str) -> str:
        """Add IF NOT EXISTS to CREATE TABLE statements."""
        if not self._should_fix(IdempotencyPattern.CREATE_TABLE):
            return sql

        # Match CREATE TABLE that doesn't already have IF NOT EXISTS
        pattern = re.compile(
            r"CREATE\s+TABLE\s+(?!IF\s+NOT\s+EXISTS\b)((?:\w+\.)?\w+)",
            re.IGNORECASE,
        )
        return pattern.sub(r"CREATE TABLE IF NOT EXISTS \1", sql)

    def _fix_create_index(self, sql: str) -> str:
        """Add IF NOT EXISTS to CREATE INDEX statements."""
        if not self._should_fix(IdempotencyPattern.CREATE_INDEX):
            return sql

        # Match CREATE INDEX that doesn't already have IF NOT EXISTS
        # Be careful not to match CREATE UNIQUE INDEX
        pattern = re.compile(
            r"CREATE\s+INDEX\s+(?!IF\s+NOT\s+EXISTS\b)(?!CONCURRENTLY\b)(\w+)",
            re.IGNORECASE,
        )
        return pattern.sub(r"CREATE INDEX IF NOT EXISTS \1", sql)

    def _fix_create_unique_index(self, sql: str) -> str:
        """Add IF NOT EXISTS to CREATE UNIQUE INDEX statements."""
        if not self._should_fix(IdempotencyPattern.CREATE_UNIQUE_INDEX):
            return sql

        pattern = re.compile(
            r"CREATE\s+UNIQUE\s+INDEX\s+(?!IF\s+NOT\s+EXISTS\b)(\w+)",
            re.IGNORECASE,
        )
        return pattern.sub(r"CREATE UNIQUE INDEX IF NOT EXISTS \1", sql)

    def _fix_create_index_concurrently(self, sql: str) -> str:
        """Add IF NOT EXISTS to CREATE INDEX CONCURRENTLY statements."""
        if not self._should_fix(IdempotencyPattern.CREATE_INDEX):
            return sql

        pattern = re.compile(
            r"CREATE\s+INDEX\s+CONCURRENTLY\s+(?!IF\s+NOT\s+EXISTS\b)(\w+)",
            re.IGNORECASE,
        )
        return pattern.sub(r"CREATE INDEX CONCURRENTLY IF NOT EXISTS \1", sql)

    def _fix_create_function(self, sql: str) -> str:
        """Add OR REPLACE to CREATE FUNCTION statements."""
        if not self._should_fix(IdempotencyPattern.CREATE_FUNCTION):
            return sql

        pattern = re.compile(
            r"CREATE\s+FUNCTION\s+(?!OR\s+REPLACE\b)",
            re.IGNORECASE,
        )
        return pattern.sub("CREATE OR REPLACE FUNCTION ", sql)

    def _fix_create_procedure(self, sql: str) -> str:
        """Add OR REPLACE to CREATE PROCEDURE statements."""
        if not self._should_fix(IdempotencyPattern.CREATE_PROCEDURE):
            return sql

        pattern = re.compile(
            r"CREATE\s+PROCEDURE\s+(?!OR\s+REPLACE\b)",
            re.IGNORECASE,
        )
        return pattern.sub("CREATE OR REPLACE PROCEDURE ", sql)

    def _fix_create_view(self, sql: str) -> str:
        """Add OR REPLACE to CREATE VIEW statements."""
        if not self._should_fix(IdempotencyPattern.CREATE_VIEW):
            return sql

        pattern = re.compile(
            r"CREATE\s+VIEW\s+(?!OR\s+REPLACE\b)",
            re.IGNORECASE,
        )
        return pattern.sub("CREATE OR REPLACE VIEW ", sql)

    def _fix_create_extension(self, sql: str) -> str:
        """Add IF NOT EXISTS to CREATE EXTENSION statements."""
        if not self._should_fix(IdempotencyPattern.CREATE_EXTENSION):
            return sql

        pattern = re.compile(
            r"CREATE\s+EXTENSION\s+(?!IF\s+NOT\s+EXISTS\b)",
            re.IGNORECASE,
        )
        return pattern.sub("CREATE EXTENSION IF NOT EXISTS ", sql)

    def _fix_create_schema(self, sql: str) -> str:
        """Add IF NOT EXISTS to CREATE SCHEMA statements."""
        if not self._should_fix(IdempotencyPattern.CREATE_SCHEMA):
            return sql

        pattern = re.compile(
            r"CREATE\s+SCHEMA\s+(?!IF\s+NOT\s+EXISTS\b)",
            re.IGNORECASE,
        )
        return pattern.sub("CREATE SCHEMA IF NOT EXISTS ", sql)

    def _fix_create_sequence(self, sql: str) -> str:
        """Add IF NOT EXISTS to CREATE SEQUENCE statements."""
        if not self._should_fix(IdempotencyPattern.CREATE_SEQUENCE):
            return sql

        pattern = re.compile(
            r"CREATE\s+SEQUENCE\s+(?!IF\s+NOT\s+EXISTS\b)",
            re.IGNORECASE,
        )
        return pattern.sub("CREATE SEQUENCE IF NOT EXISTS ", sql)

    def _fix_alter_table_add_column(self, sql: str) -> str:
        """Add IF NOT EXISTS to ALTER TABLE ADD COLUMN statements."""
        if not self._should_fix(IdempotencyPattern.ALTER_TABLE_ADD_COLUMN):
            return sql

        # Handle ALTER TABLE ... ADD COLUMN ... (with COLUMN keyword)
        pattern1 = re.compile(
            r"ALTER\s+TABLE\s+((?:\w+\.)?\w+)\s+ADD\s+COLUMN\s+(?!IF\s+NOT\s+EXISTS\b)(\w+)",
            re.IGNORECASE,
        )
        sql = pattern1.sub(r"ALTER TABLE \1 ADD COLUMN IF NOT EXISTS \2", sql)

        # Handle ALTER TABLE ... ADD ... (without COLUMN keyword)
        # Only match if not already fixed and not ADD CONSTRAINT
        pattern2 = re.compile(
            r"ALTER\s+TABLE\s+((?:\w+\.)?\w+)\s+ADD\s+(?!COLUMN\b)(?!CONSTRAINT\b)(?!IF\s+NOT\s+EXISTS\b)(\w+)",
            re.IGNORECASE,
        )
        sql = pattern2.sub(r"ALTER TABLE \1 ADD COLUMN IF NOT EXISTS \2", sql)

        return sql

    def _fix_drop_table(self, sql: str) -> str:
        """Add IF EXISTS to DROP TABLE statements."""
        if not self._should_fix(IdempotencyPattern.DROP_TABLE):
            return sql

        # Preserve CASCADE/RESTRICT if present
        pattern = re.compile(
            r"DROP\s+TABLE\s+(?!IF\s+EXISTS\b)((?:\w+\.)?\w+)(\s+(?:CASCADE|RESTRICT))?",
            re.IGNORECASE,
        )
        return pattern.sub(r"DROP TABLE IF EXISTS \1\2", sql)

    def _fix_drop_index(self, sql: str) -> str:
        """Add IF EXISTS to DROP INDEX statements."""
        if not self._should_fix(IdempotencyPattern.DROP_INDEX):
            return sql

        pattern = re.compile(
            r"DROP\s+INDEX\s+(?!IF\s+EXISTS\b)(?!CONCURRENTLY\b)((?:\w+\.)?\w+)",
            re.IGNORECASE,
        )
        return pattern.sub(r"DROP INDEX IF EXISTS \1", sql)

    def _fix_drop_function(self, sql: str) -> str:
        """Add IF EXISTS to DROP FUNCTION statements."""
        if not self._should_fix(IdempotencyPattern.DROP_FUNCTION):
            return sql

        pattern = re.compile(
            r"DROP\s+FUNCTION\s+(?!IF\s+EXISTS\b)((?:\w+\.)?\w+)",
            re.IGNORECASE,
        )
        return pattern.sub(r"DROP FUNCTION IF EXISTS \1", sql)

    def _fix_drop_view(self, sql: str) -> str:
        """Add IF EXISTS to DROP VIEW statements."""
        if not self._should_fix(IdempotencyPattern.DROP_VIEW):
            return sql

        pattern = re.compile(
            r"DROP\s+VIEW\s+(?!IF\s+EXISTS\b)((?:\w+\.)?\w+)(\s+(?:CASCADE|RESTRICT))?",
            re.IGNORECASE,
        )
        return pattern.sub(r"DROP VIEW IF EXISTS \1\2", sql)

    def _fix_drop_type(self, sql: str) -> str:
        """Add IF EXISTS to DROP TYPE statements."""
        if not self._should_fix(IdempotencyPattern.DROP_TYPE):
            return sql

        pattern = re.compile(
            r"DROP\s+TYPE\s+(?!IF\s+EXISTS\b)((?:\w+\.)?\w+)(\s+(?:CASCADE|RESTRICT))?",
            re.IGNORECASE,
        )
        return pattern.sub(r"DROP TYPE IF EXISTS \1\2", sql)

    def _fix_drop_schema(self, sql: str) -> str:
        """Add IF EXISTS to DROP SCHEMA statements."""
        if not self._should_fix(IdempotencyPattern.DROP_SCHEMA):
            return sql

        pattern = re.compile(
            r"DROP\s+SCHEMA\s+(?!IF\s+EXISTS\b)((?:\w+\.)?\w+)(\s+(?:CASCADE|RESTRICT))?",
            re.IGNORECASE,
        )
        return pattern.sub(r"DROP SCHEMA IF EXISTS \1\2", sql)

    def _fix_drop_sequence(self, sql: str) -> str:
        """Add IF EXISTS to DROP SEQUENCE statements."""
        if not self._should_fix(IdempotencyPattern.DROP_SEQUENCE):
            return sql

        pattern = re.compile(
            r"DROP\s+SEQUENCE\s+(?!IF\s+EXISTS\b)((?:\w+\.)?\w+)(\s+(?:CASCADE|RESTRICT))?",
            re.IGNORECASE,
        )
        return pattern.sub(r"DROP SEQUENCE IF EXISTS \1\2", sql)
