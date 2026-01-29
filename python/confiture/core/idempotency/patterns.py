"""Pattern detection for non-idempotent SQL statements.

This module provides regex-based detection of SQL patterns that are not
idempotent by default and may fail when re-run.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import NamedTuple

from confiture.core.idempotency.models import IdempotencyPattern


@dataclass
class PatternMatch:
    """Represents a detected non-idempotent pattern match.

    Attributes:
        pattern: The type of non-idempotent pattern
        sql_snippet: The matched SQL text
        line_number: Line number where the match starts
        start_pos: Character position where match starts
        end_pos: Character position where match ends
    """

    pattern: IdempotencyPattern
    sql_snippet: str
    line_number: int
    start_pos: int
    end_pos: int


class PatternDefinition(NamedTuple):
    """Definition of a pattern to detect."""

    pattern: IdempotencyPattern
    regex: re.Pattern[str]
    skip_regex: re.Pattern[str] | None = None


# Compile regex patterns for performance
# Each pattern detects non-idempotent SQL and has an optional skip pattern
# for the idempotent equivalent

PATTERNS: list[PatternDefinition] = [
    # CREATE TABLE without IF NOT EXISTS
    PatternDefinition(
        pattern=IdempotencyPattern.CREATE_TABLE,
        regex=re.compile(
            r"CREATE\s+TABLE\s+(?!IF\s+NOT\s+EXISTS\b)(\w+\.)?(\w+)",
            re.IGNORECASE | re.MULTILINE,
        ),
        skip_regex=re.compile(r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS", re.IGNORECASE),
    ),
    # CREATE UNIQUE INDEX without IF NOT EXISTS (must be before CREATE INDEX)
    PatternDefinition(
        pattern=IdempotencyPattern.CREATE_UNIQUE_INDEX,
        regex=re.compile(
            r"CREATE\s+UNIQUE\s+INDEX\s+(?!IF\s+NOT\s+EXISTS\b)(?:CONCURRENTLY\s+)?(?!IF\s+NOT\s+EXISTS\b)(\w+)",
            re.IGNORECASE | re.MULTILINE,
        ),
        skip_regex=re.compile(
            r"CREATE\s+UNIQUE\s+INDEX\s+(?:CONCURRENTLY\s+)?IF\s+NOT\s+EXISTS", re.IGNORECASE
        ),
    ),
    # CREATE INDEX without IF NOT EXISTS
    PatternDefinition(
        pattern=IdempotencyPattern.CREATE_INDEX,
        regex=re.compile(
            r"CREATE\s+INDEX\s+(?!IF\s+NOT\s+EXISTS\b)(?:CONCURRENTLY\s+)?(?!IF\s+NOT\s+EXISTS\b)(\w+)",
            re.IGNORECASE | re.MULTILINE,
        ),
        skip_regex=re.compile(
            r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:CONCURRENTLY\s+)?IF\s+NOT\s+EXISTS", re.IGNORECASE
        ),
    ),
    # CREATE FUNCTION without OR REPLACE
    PatternDefinition(
        pattern=IdempotencyPattern.CREATE_FUNCTION,
        regex=re.compile(
            r"CREATE\s+FUNCTION\s+(?!OR\s+REPLACE\b)",
            re.IGNORECASE | re.MULTILINE,
        ),
        skip_regex=re.compile(r"CREATE\s+OR\s+REPLACE\s+FUNCTION", re.IGNORECASE),
    ),
    # CREATE PROCEDURE without OR REPLACE
    PatternDefinition(
        pattern=IdempotencyPattern.CREATE_PROCEDURE,
        regex=re.compile(
            r"CREATE\s+PROCEDURE\s+(?!OR\s+REPLACE\b)",
            re.IGNORECASE | re.MULTILINE,
        ),
        skip_regex=re.compile(r"CREATE\s+OR\s+REPLACE\s+PROCEDURE", re.IGNORECASE),
    ),
    # CREATE VIEW without OR REPLACE
    PatternDefinition(
        pattern=IdempotencyPattern.CREATE_VIEW,
        regex=re.compile(
            r"CREATE\s+VIEW\s+(?!OR\s+REPLACE\b)",
            re.IGNORECASE | re.MULTILINE,
        ),
        skip_regex=re.compile(r"CREATE\s+OR\s+REPLACE\s+VIEW", re.IGNORECASE),
    ),
    # CREATE TYPE (always non-idempotent without DO block check)
    PatternDefinition(
        pattern=IdempotencyPattern.CREATE_TYPE,
        regex=re.compile(
            r"CREATE\s+TYPE\s+(\w+)",
            re.IGNORECASE | re.MULTILINE,
        ),
        # No simple skip - needs DO block detection
        skip_regex=None,
    ),
    # CREATE EXTENSION without IF NOT EXISTS
    PatternDefinition(
        pattern=IdempotencyPattern.CREATE_EXTENSION,
        regex=re.compile(
            r"CREATE\s+EXTENSION\s+(?!IF\s+NOT\s+EXISTS\b)",
            re.IGNORECASE | re.MULTILINE,
        ),
        skip_regex=re.compile(r"CREATE\s+EXTENSION\s+IF\s+NOT\s+EXISTS", re.IGNORECASE),
    ),
    # CREATE SCHEMA without IF NOT EXISTS
    PatternDefinition(
        pattern=IdempotencyPattern.CREATE_SCHEMA,
        regex=re.compile(
            r"CREATE\s+SCHEMA\s+(?!IF\s+NOT\s+EXISTS\b)",
            re.IGNORECASE | re.MULTILINE,
        ),
        skip_regex=re.compile(r"CREATE\s+SCHEMA\s+IF\s+NOT\s+EXISTS", re.IGNORECASE),
    ),
    # CREATE SEQUENCE without IF NOT EXISTS
    PatternDefinition(
        pattern=IdempotencyPattern.CREATE_SEQUENCE,
        regex=re.compile(
            r"CREATE\s+SEQUENCE\s+(?!IF\s+NOT\s+EXISTS\b)",
            re.IGNORECASE | re.MULTILINE,
        ),
        skip_regex=re.compile(r"CREATE\s+SEQUENCE\s+IF\s+NOT\s+EXISTS", re.IGNORECASE),
    ),
    # ALTER TABLE ADD COLUMN without IF NOT EXISTS
    PatternDefinition(
        pattern=IdempotencyPattern.ALTER_TABLE_ADD_COLUMN,
        regex=re.compile(
            r"ALTER\s+TABLE\s+(\w+\.)?(\w+)\s+ADD\s+(?:COLUMN\s+)?(?!IF\s+NOT\s+EXISTS\b)(\w+)",
            re.IGNORECASE | re.MULTILINE,
        ),
        skip_regex=re.compile(
            r"ALTER\s+TABLE\s+\w+\s+ADD\s+(?:COLUMN\s+)?IF\s+NOT\s+EXISTS", re.IGNORECASE
        ),
    ),
    # DROP TABLE without IF EXISTS
    PatternDefinition(
        pattern=IdempotencyPattern.DROP_TABLE,
        regex=re.compile(
            r"DROP\s+TABLE\s+(?!IF\s+EXISTS\b)",
            re.IGNORECASE | re.MULTILINE,
        ),
        skip_regex=re.compile(r"DROP\s+TABLE\s+IF\s+EXISTS", re.IGNORECASE),
    ),
    # DROP INDEX without IF EXISTS
    PatternDefinition(
        pattern=IdempotencyPattern.DROP_INDEX,
        regex=re.compile(
            r"DROP\s+INDEX\s+(?!IF\s+EXISTS\b)(?:CONCURRENTLY\s+)?(?!IF\s+EXISTS\b)",
            re.IGNORECASE | re.MULTILINE,
        ),
        skip_regex=re.compile(r"DROP\s+INDEX\s+(?:CONCURRENTLY\s+)?IF\s+EXISTS", re.IGNORECASE),
    ),
    # DROP FUNCTION without IF EXISTS
    PatternDefinition(
        pattern=IdempotencyPattern.DROP_FUNCTION,
        regex=re.compile(
            r"DROP\s+FUNCTION\s+(?!IF\s+EXISTS\b)",
            re.IGNORECASE | re.MULTILINE,
        ),
        skip_regex=re.compile(r"DROP\s+FUNCTION\s+IF\s+EXISTS", re.IGNORECASE),
    ),
    # DROP VIEW without IF EXISTS
    PatternDefinition(
        pattern=IdempotencyPattern.DROP_VIEW,
        regex=re.compile(
            r"DROP\s+VIEW\s+(?!IF\s+EXISTS\b)",
            re.IGNORECASE | re.MULTILINE,
        ),
        skip_regex=re.compile(r"DROP\s+VIEW\s+IF\s+EXISTS", re.IGNORECASE),
    ),
    # DROP TYPE without IF EXISTS
    PatternDefinition(
        pattern=IdempotencyPattern.DROP_TYPE,
        regex=re.compile(
            r"DROP\s+TYPE\s+(?!IF\s+EXISTS\b)",
            re.IGNORECASE | re.MULTILINE,
        ),
        skip_regex=re.compile(r"DROP\s+TYPE\s+IF\s+EXISTS", re.IGNORECASE),
    ),
    # DROP SCHEMA without IF EXISTS
    PatternDefinition(
        pattern=IdempotencyPattern.DROP_SCHEMA,
        regex=re.compile(
            r"DROP\s+SCHEMA\s+(?!IF\s+EXISTS\b)",
            re.IGNORECASE | re.MULTILINE,
        ),
        skip_regex=re.compile(r"DROP\s+SCHEMA\s+IF\s+EXISTS", re.IGNORECASE),
    ),
    # DROP SEQUENCE without IF EXISTS
    PatternDefinition(
        pattern=IdempotencyPattern.DROP_SEQUENCE,
        regex=re.compile(
            r"DROP\s+SEQUENCE\s+(?!IF\s+EXISTS\b)",
            re.IGNORECASE | re.MULTILINE,
        ),
        skip_regex=re.compile(r"DROP\s+SEQUENCE\s+IF\s+EXISTS", re.IGNORECASE),
    ),
]

# Pattern to detect DO blocks (for exception handling)
DO_BLOCK_PATTERN = re.compile(
    r"DO\s+\$\$.*?EXCEPTION\s+WHEN\s+\w+.*?\$\$",
    re.IGNORECASE | re.DOTALL,
)

# Pattern to detect DO blocks with type check
DO_BLOCK_TYPE_CHECK_PATTERN = re.compile(
    r"DO\s+\$\$.*?(?:pg_type|NOT\s+EXISTS).*?CREATE\s+TYPE.*?\$\$",
    re.IGNORECASE | re.DOTALL,
)


def _get_line_number(sql: str, position: int) -> int:
    """Get the line number for a character position in SQL.

    Args:
        sql: The SQL string
        position: Character position (0-indexed)

    Returns:
        Line number (1-indexed)
    """
    return sql[:position].count("\n") + 1


def _extract_snippet(sql: str, match: re.Match[str], max_length: int = 80) -> str:
    """Extract a snippet of SQL around a match.

    Args:
        sql: The full SQL string
        match: The regex match object
        max_length: Maximum snippet length

    Returns:
        The SQL snippet, possibly truncated
    """
    start = match.start()
    # Find the end of the statement or max_length, whichever is first
    end = min(match.end() + 50, len(sql))

    # Try to find statement end (semicolon)
    semicolon_pos = sql.find(";", match.start())
    if semicolon_pos != -1 and semicolon_pos < end:
        end = semicolon_pos + 1

    snippet = sql[start:end].strip()

    # Clean up whitespace
    snippet = " ".join(snippet.split())

    if len(snippet) > max_length:
        snippet = snippet[:max_length] + "..."

    return snippet


def _find_do_blocks(sql: str) -> list[tuple[int, int]]:
    """Find all DO blocks in the SQL that provide idempotency protection.

    Args:
        sql: The SQL string

    Returns:
        List of (start, end) positions for protected DO blocks
    """
    blocks = []

    # Find DO blocks with EXCEPTION handlers
    for match in DO_BLOCK_PATTERN.finditer(sql):
        blocks.append((match.start(), match.end()))

    # Find DO blocks with type existence checks
    for match in DO_BLOCK_TYPE_CHECK_PATTERN.finditer(sql):
        blocks.append((match.start(), match.end()))

    return blocks


def _is_in_do_block(position: int, do_blocks: list[tuple[int, int]]) -> bool:
    """Check if a position is inside a protected DO block.

    Args:
        position: Character position to check
        do_blocks: List of (start, end) positions for DO blocks

    Returns:
        True if position is inside a DO block
    """
    return any(start <= position <= end for start, end in do_blocks)


def detect_non_idempotent_patterns(sql: str) -> list[PatternMatch]:
    """Detect non-idempotent SQL patterns in the given SQL.

    Scans the SQL for patterns that are not idempotent by default,
    such as CREATE TABLE without IF NOT EXISTS.

    Args:
        sql: The SQL string to analyze

    Returns:
        List of PatternMatch objects for each violation found

    Example:
        >>> sql = "CREATE TABLE users (id INT);"
        >>> matches = detect_non_idempotent_patterns(sql)
        >>> len(matches)
        1
        >>> matches[0].pattern
        <IdempotencyPattern.CREATE_TABLE: 'CREATE_TABLE'>
    """
    matches: list[PatternMatch] = []

    # Find all DO blocks that provide idempotency protection
    do_blocks = _find_do_blocks(sql)

    for pattern_def in PATTERNS:
        for match in pattern_def.regex.finditer(sql):
            # Check if this position is protected by a DO block
            if _is_in_do_block(match.start(), do_blocks):
                continue

            # For patterns with skip_regex, verify it's not the idempotent version
            if pattern_def.skip_regex:
                # Check if the matched text actually matches the skip pattern
                matched_text = sql[match.start() : match.end() + 20]
                if pattern_def.skip_regex.match(matched_text):
                    continue

            # Special handling for CREATE UNIQUE INDEX - don't double-count
            if pattern_def.pattern == IdempotencyPattern.CREATE_INDEX:
                # Skip if this is actually a UNIQUE INDEX
                pre_match = sql[max(0, match.start() - 10) : match.start()]
                if "UNIQUE" in pre_match.upper():
                    continue

            matches.append(
                PatternMatch(
                    pattern=pattern_def.pattern,
                    sql_snippet=_extract_snippet(sql, match),
                    line_number=_get_line_number(sql, match.start()),
                    start_pos=match.start(),
                    end_pos=match.end(),
                )
            )

    # Sort by position to maintain order
    matches.sort(key=lambda m: m.start_pos)

    return matches
