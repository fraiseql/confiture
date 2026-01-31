"""Pattern detection for seed data validation issues.

This module provides regex-based detection of SQL patterns in seed files that
should be addressed for consistency and reliability.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import NamedTuple

from confiture.core.seed_validation.models import SeedValidationPattern


@dataclass
class PatternMatch:
    """Represents a detected seed validation issue.

    Attributes:
        pattern: The type of validation issue
        sql_snippet: The matched SQL text
        line_number: Line number where the match starts
        start_pos: Character position where match starts
        end_pos: Character position where match ends
    """

    pattern: SeedValidationPattern
    sql_snippet: str
    line_number: int
    start_pos: int
    end_pos: int


class PatternDefinition(NamedTuple):
    """Definition of a pattern to detect."""

    pattern: SeedValidationPattern
    regex: re.Pattern[str]
    skip_regex: re.Pattern[str] | None = None


# Compile regex patterns for performance
PATTERNS: list[PatternDefinition] = [
    # Double semicolons (;;)
    PatternDefinition(
        pattern=SeedValidationPattern.DOUBLE_SEMICOLON,
        regex=re.compile(r";;", re.IGNORECASE | re.MULTILINE),
    ),
    # Non-INSERT statements (CREATE, ALTER, DROP, etc.)
    PatternDefinition(
        pattern=SeedValidationPattern.NON_INSERT_STATEMENT,
        regex=re.compile(
            r"^\s*(CREATE|ALTER|DROP|TRUNCATE|UPDATE|DELETE|WITH)\s+",
            re.IGNORECASE | re.MULTILINE,
        ),
    ),
    # INSERT without ON CONFLICT
    PatternDefinition(
        pattern=SeedValidationPattern.MISSING_ON_CONFLICT,
        regex=re.compile(
            r"INSERT\s+INTO\s+\w+.*?VALUES\s*\(.*?\)\s*;",
            re.IGNORECASE | re.MULTILINE | re.DOTALL,
        ),
        skip_regex=re.compile(
            r"ON\s+CONFLICT",
            re.IGNORECASE,
        ),
    ),
]


def detect_seed_issues(sql: str) -> list[PatternMatch]:
    """Detect seed data validation issues in SQL.

    Args:
        sql: The SQL content to validate

    Returns:
        List of PatternMatch objects for each issue found
    """
    issues: list[PatternMatch] = []

    # Preprocess SQL to preserve line numbers
    processed_sql = _preprocess_sql(sql)

    for pattern_def in PATTERNS:
        for match in pattern_def.regex.finditer(processed_sql):
            # Skip if skip_regex matches (e.g., INSERT WITH ON CONFLICT)
            if pattern_def.skip_regex:
                # Check if skip pattern exists after this match
                remaining = processed_sql[match.start() :]
                if pattern_def.skip_regex.search(remaining):
                    # Only skip if the skip pattern is in the same statement
                    next_semicolon = remaining.find(";")
                    if next_semicolon > 0:
                        check_area = remaining[: next_semicolon + 1]
                        if pattern_def.skip_regex.search(check_area):
                            continue

            # Calculate line number
            line_number = processed_sql[: match.start()].count("\n") + 1

            # Extract snippet
            snippet_start = max(0, match.start() - 20)
            snippet_end = min(len(processed_sql), match.end() + 30)
            sql_snippet = processed_sql[snippet_start:snippet_end].replace("\n", " ").strip()

            issues.append(
                PatternMatch(
                    pattern=pattern_def.pattern,
                    sql_snippet=sql_snippet,
                    line_number=line_number,
                    start_pos=match.start(),
                    end_pos=match.end(),
                )
            )

    return sorted(issues, key=lambda x: x.line_number)


def _preprocess_sql(sql: str) -> str:
    """Preprocess SQL to preserve line numbers while handling comments.

    Args:
        sql: Raw SQL content

    Returns:
        Processed SQL with line numbers preserved
    """
    # Remove single-line comments but preserve newlines
    lines = []
    for line in sql.split("\n"):
        # Remove everything after -- but keep the newline
        if "--" in line:
            line = line[: line.index("--")]
        lines.append(line)

    return "\n".join(lines)
