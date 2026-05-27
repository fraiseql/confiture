"""Pattern detection for non-idempotent SQL statements.

This module exposes :func:`detect_non_idempotent_patterns`, a dispatcher
that prefers the pglast-backed AST detector when available and falls
back to a regex-only implementation otherwise. The fallback is also the
slim-install path for users who don't have the ``[ast]`` extra.

Setting ``CONFITURE_IDEMPOTENCY_FORCE_REGEX=1`` pins the dispatcher to
the regex backend — kept as an escape hatch for one release after the
0.14.0 cutover in case a user hits an AST regression.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import NamedTuple, TypedDict

from confiture.core.idempotency.ast_detector import _detect_via_ast, is_pglast_available
from confiture.core.idempotency.models import IdempotencyPattern


class PatternCatalogEntry(TypedDict):
    """Public shape of a single entry in the pattern catalog.

    Stable contract — see ``--list-patterns`` JSON schema (``version: "1"``)
    in ``docs/reference/json-schemas/migrate-validate-list-patterns.schema.json``.
    """

    id: str
    description: str
    severity: str
    has_skip_regex: bool
    skip_hint: str | None
    has_auto_fix: bool
    template_fillable: bool


_FORCE_REGEX_ENV = "CONFITURE_IDEMPOTENCY_FORCE_REGEX"


def _force_regex() -> bool:
    """Return True when the force-regex env var is set to a truthy value."""
    value = os.environ.get(_FORCE_REGEX_ENV, "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class PatternMatch:
    """Represents a detected non-idempotent pattern match.

    Attributes:
        pattern: The type of non-idempotent pattern
        sql_snippet: The matched SQL text
        line_number: Line number where the match starts
        start_pos: Character position where match starts
        end_pos: Character position where match ends
        severity: ``"error"`` (default — fails the gate) or ``"info"``
            (heuristic finding — rendered but doesn't fail the gate
            unless ``--strict-cor`` is passed at the CLI layer).
        suggestion: Filled-in fix template (captures-driven) or ``None``
            to fall back to :attr:`IdempotencyPattern.suggestion`. The
            validator copies this onto the resulting
            :class:`~confiture.core.idempotency.models.IdempotencyViolation`.
    """

    pattern: IdempotencyPattern
    sql_snippet: str
    line_number: int
    start_pos: int
    end_pos: int
    severity: str = "error"
    suggestion: str | None = None


class PatternDefinition(NamedTuple):
    """Definition of a pattern to detect."""

    pattern: IdempotencyPattern
    regex: re.Pattern[str]
    skip_regex: re.Pattern[str] | None = None
    severity: str = "error"


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
            r"ALTER\s+TABLE\s+(\w+\.)?(\w+)\s+ADD\s+(?:COLUMN\s+)?(?!IF\s+NOT\s+EXISTS\b)"
            r"(?!CONSTRAINT\b)(\w+)",
            re.IGNORECASE | re.MULTILINE,
        ),
        skip_regex=re.compile(
            r"ALTER\s+TABLE\s+\w+\s+ADD\s+(?:COLUMN\s+)?IF\s+NOT\s+EXISTS", re.IGNORECASE
        ),
    ),
    # ALTER TABLE ADD CONSTRAINT ... PRIMARY KEY (must match before generic CHECK)
    PatternDefinition(
        pattern=IdempotencyPattern.ALTER_TABLE_ADD_CONSTRAINT_PRIMARY_KEY,
        regex=re.compile(
            r"ALTER\s+TABLE\s+(?:ONLY\s+)?(?:\w+\.)?\w+\s+ADD\s+CONSTRAINT\s+\w+\s+PRIMARY\s+KEY\b",
            re.IGNORECASE | re.MULTILINE,
        ),
    ),
    # ALTER TABLE ADD CONSTRAINT ... UNIQUE
    PatternDefinition(
        pattern=IdempotencyPattern.ALTER_TABLE_ADD_CONSTRAINT_UNIQUE,
        regex=re.compile(
            r"ALTER\s+TABLE\s+(?:ONLY\s+)?(?:\w+\.)?\w+\s+ADD\s+CONSTRAINT\s+\w+\s+UNIQUE\b",
            re.IGNORECASE | re.MULTILINE,
        ),
    ),
    # ALTER TABLE ADD CONSTRAINT ... CHECK
    PatternDefinition(
        pattern=IdempotencyPattern.ALTER_TABLE_ADD_CONSTRAINT_CHECK,
        regex=re.compile(
            r"ALTER\s+TABLE\s+(?:ONLY\s+)?(?:\w+\.)?\w+\s+ADD\s+CONSTRAINT\s+\w+\s+CHECK\b",
            re.IGNORECASE | re.MULTILINE,
        ),
    ),
    # ALTER TABLE RENAME COLUMN
    PatternDefinition(
        pattern=IdempotencyPattern.ALTER_TABLE_RENAME_COLUMN,
        regex=re.compile(
            r"ALTER\s+TABLE\s+(?:ONLY\s+)?(?:\w+\.)?\w+\s+RENAME\s+(?:COLUMN\s+)?\w+\s+TO\s+\w+",
            re.IGNORECASE | re.MULTILINE,
        ),
    ),
    # ALTER MATERIALIZED VIEW ... OWNER TO (must come before plain VIEW)
    PatternDefinition(
        pattern=IdempotencyPattern.ALTER_MATVIEW_OWNER,
        regex=re.compile(
            r"ALTER\s+MATERIALIZED\s+VIEW\s+(?:\w+\.)?\w+\s+OWNER\s+TO\s+\w+",
            re.IGNORECASE | re.MULTILINE,
        ),
    ),
    # ALTER VIEW ... OWNER TO
    PatternDefinition(
        pattern=IdempotencyPattern.ALTER_VIEW_OWNER,
        regex=re.compile(
            r"ALTER\s+VIEW\s+(?:\w+\.)?\w+\s+OWNER\s+TO\s+\w+",
            re.IGNORECASE | re.MULTILINE,
        ),
    ),
    # ALTER TABLE ... OWNER TO
    PatternDefinition(
        pattern=IdempotencyPattern.ALTER_TABLE_OWNER,
        regex=re.compile(
            r"ALTER\s+TABLE\s+(?:ONLY\s+)?(?:\w+\.)?\w+\s+OWNER\s+TO\s+\w+",
            re.IGNORECASE | re.MULTILINE,
        ),
    ),
    # CREATE OR REPLACE VIEW — shape-change risk (info severity)
    PatternDefinition(
        pattern=IdempotencyPattern.CREATE_OR_REPLACE_VIEW_SHAPE_RISK,
        regex=re.compile(
            r"CREATE\s+OR\s+REPLACE\s+VIEW\s+(?:\w+\.)?\w+",
            re.IGNORECASE | re.MULTILINE,
        ),
        severity="info",
    ),
    # CREATE OR REPLACE FUNCTION — parameter-rename risk (info severity)
    PatternDefinition(
        pattern=IdempotencyPattern.CREATE_OR_REPLACE_FUNCTION_SHAPE_RISK,
        regex=re.compile(
            r"CREATE\s+OR\s+REPLACE\s+FUNCTION\s+(?:\w+\.)?\w+",
            re.IGNORECASE | re.MULTILINE,
        ),
        severity="info",
    ),
    # CREATE OR REPLACE PROCEDURE — parameter-rename risk (info severity)
    PatternDefinition(
        pattern=IdempotencyPattern.CREATE_OR_REPLACE_PROCEDURE_SHAPE_RISK,
        regex=re.compile(
            r"CREATE\s+OR\s+REPLACE\s+PROCEDURE\s+(?:\w+\.)?\w+",
            re.IGNORECASE | re.MULTILINE,
        ),
        severity="info",
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

# Human-readable descriptions of what each pattern detects.
# Surfaced via ``confiture migrate validate --list-patterns``; keep concise
# (one short sentence per entry, present tense, describes the violation —
# not the fix).
_DESCRIPTIONS: dict[IdempotencyPattern, str] = {
    IdempotencyPattern.CREATE_TABLE: "CREATE TABLE without IF NOT EXISTS.",
    IdempotencyPattern.CREATE_INDEX: "CREATE INDEX without IF NOT EXISTS.",
    IdempotencyPattern.CREATE_UNIQUE_INDEX: "CREATE UNIQUE INDEX without IF NOT EXISTS.",
    IdempotencyPattern.CREATE_FUNCTION: "CREATE FUNCTION without OR REPLACE.",
    IdempotencyPattern.CREATE_PROCEDURE: "CREATE PROCEDURE without OR REPLACE.",
    IdempotencyPattern.CREATE_VIEW: "CREATE VIEW without a preceding DROP VIEW IF EXISTS.",
    IdempotencyPattern.CREATE_TYPE: (
        "CREATE TYPE outside a DO block that checks pg_type — re-run will fail."
    ),
    IdempotencyPattern.CREATE_EXTENSION: "CREATE EXTENSION without IF NOT EXISTS.",
    IdempotencyPattern.CREATE_SCHEMA: "CREATE SCHEMA without IF NOT EXISTS.",
    IdempotencyPattern.CREATE_SEQUENCE: "CREATE SEQUENCE without IF NOT EXISTS.",
    IdempotencyPattern.ALTER_TABLE_ADD_COLUMN: "ALTER TABLE ADD COLUMN without IF NOT EXISTS.",
    IdempotencyPattern.ALTER_TABLE_ADD_CONSTRAINT_CHECK: (
        "ALTER TABLE ADD CONSTRAINT CHECK without DROP CONSTRAINT IF EXISTS or DO-block guard."
    ),
    IdempotencyPattern.ALTER_TABLE_ADD_CONSTRAINT_PRIMARY_KEY: (
        "ALTER TABLE ADD CONSTRAINT PRIMARY KEY without DROP CONSTRAINT IF EXISTS or guard."
    ),
    IdempotencyPattern.ALTER_TABLE_ADD_CONSTRAINT_UNIQUE: (
        "ALTER TABLE ADD CONSTRAINT UNIQUE without DROP CONSTRAINT IF EXISTS or guard."
    ),
    IdempotencyPattern.ALTER_TABLE_RENAME_COLUMN: (
        "ALTER TABLE RENAME COLUMN without information_schema guard."
    ),
    IdempotencyPattern.ALTER_TABLE_OWNER: "ALTER TABLE … OWNER TO without pg_class existence check.",
    IdempotencyPattern.ALTER_VIEW_OWNER: "ALTER VIEW … OWNER TO without pg_class existence check.",
    IdempotencyPattern.ALTER_MATVIEW_OWNER: (
        "ALTER MATERIALIZED VIEW … OWNER TO without pg_matviews existence check."
    ),
    IdempotencyPattern.DROP_TABLE: "DROP TABLE without IF EXISTS.",
    IdempotencyPattern.DROP_INDEX: "DROP INDEX without IF EXISTS.",
    IdempotencyPattern.DROP_FUNCTION: "DROP FUNCTION without IF EXISTS.",
    IdempotencyPattern.DROP_VIEW: "DROP VIEW without IF EXISTS.",
    IdempotencyPattern.DROP_TYPE: "DROP TYPE without IF EXISTS.",
    IdempotencyPattern.DROP_SCHEMA: "DROP SCHEMA without IF EXISTS.",
    IdempotencyPattern.DROP_SEQUENCE: "DROP SEQUENCE without IF EXISTS.",
    IdempotencyPattern.CREATE_OR_REPLACE_VIEW_SHAPE_RISK: (
        "CREATE OR REPLACE VIEW — shape changes (column add/rename/reorder) fail at runtime."
    ),
    IdempotencyPattern.CREATE_OR_REPLACE_FUNCTION_SHAPE_RISK: (
        "CREATE OR REPLACE FUNCTION — fails when input parameters are renamed."
    ),
    IdempotencyPattern.CREATE_OR_REPLACE_PROCEDURE_SHAPE_RISK: (
        "CREATE OR REPLACE PROCEDURE — fails when input parameters are renamed."
    ),
}

# Classification of patterns by whether a captures-driven suggestion
# template can be filled from the match. Both sets together cover every
# :class:`IdempotencyPattern` member; the two sets are disjoint.
#
# ``TEMPLATE_FILLABLE`` patterns expose at least one identifier
# (table, index, constraint, column, …) that the AST / regex backend
# can extract reliably, so the violation's ``suggestion`` is a
# copy-pasteable SQL block with that identifier inlined.
#
# ``TEMPLATE_NOT_AVAILABLE`` patterns can be detected but their
# corrective fix has no mechanical structure — the suggestion stays
# generic and explicitly says so.
TEMPLATE_FILLABLE: frozenset[IdempotencyPattern] = frozenset(
    {
        IdempotencyPattern.CREATE_TABLE,
        IdempotencyPattern.CREATE_INDEX,
        IdempotencyPattern.CREATE_UNIQUE_INDEX,
        IdempotencyPattern.CREATE_VIEW,
        IdempotencyPattern.CREATE_TYPE,
        IdempotencyPattern.CREATE_SCHEMA,
        IdempotencyPattern.CREATE_SEQUENCE,
        IdempotencyPattern.CREATE_EXTENSION,
        IdempotencyPattern.ALTER_TABLE_ADD_COLUMN,
        IdempotencyPattern.ALTER_TABLE_ADD_CONSTRAINT_CHECK,
        IdempotencyPattern.ALTER_TABLE_ADD_CONSTRAINT_PRIMARY_KEY,
        IdempotencyPattern.ALTER_TABLE_ADD_CONSTRAINT_UNIQUE,
        IdempotencyPattern.ALTER_TABLE_RENAME_COLUMN,
        IdempotencyPattern.ALTER_TABLE_OWNER,
        IdempotencyPattern.ALTER_VIEW_OWNER,
        IdempotencyPattern.ALTER_MATVIEW_OWNER,
        IdempotencyPattern.DROP_TABLE,
        IdempotencyPattern.DROP_INDEX,
        IdempotencyPattern.DROP_VIEW,
        IdempotencyPattern.DROP_TYPE,
        IdempotencyPattern.DROP_SCHEMA,
        IdempotencyPattern.DROP_SEQUENCE,
        IdempotencyPattern.CREATE_OR_REPLACE_VIEW_SHAPE_RISK,
    }
)

# Patterns that can be detected but whose fix has no mechanical
# template — the regex doesn't pin a single identifier to substitute
# in, or the fix structurally requires user judgement (e.g. DROP
# FUNCTION needs a parameter signature, not just a name).
TEMPLATE_NOT_AVAILABLE: frozenset[IdempotencyPattern] = frozenset(
    {
        IdempotencyPattern.CREATE_FUNCTION,
        IdempotencyPattern.CREATE_PROCEDURE,
        IdempotencyPattern.DROP_FUNCTION,
        IdempotencyPattern.CREATE_OR_REPLACE_FUNCTION_SHAPE_RISK,
        IdempotencyPattern.CREATE_OR_REPLACE_PROCEDURE_SHAPE_RISK,
    }
)

# Human-friendly hints describing what idempotent form the validator
# skips over. Only set for patterns with a ``skip_regex`` — patterns
# that have no simple skip (e.g. CREATE TYPE) map to ``None``.
_SKIP_HINTS: dict[IdempotencyPattern, str | None] = {
    IdempotencyPattern.CREATE_TABLE: "CREATE TABLE IF NOT EXISTS",
    IdempotencyPattern.CREATE_INDEX: "CREATE INDEX IF NOT EXISTS",
    IdempotencyPattern.CREATE_UNIQUE_INDEX: "CREATE UNIQUE INDEX IF NOT EXISTS",
    IdempotencyPattern.CREATE_FUNCTION: "CREATE OR REPLACE FUNCTION",
    IdempotencyPattern.CREATE_PROCEDURE: "CREATE OR REPLACE PROCEDURE",
    IdempotencyPattern.CREATE_VIEW: "CREATE OR REPLACE VIEW",
    IdempotencyPattern.CREATE_EXTENSION: "CREATE EXTENSION IF NOT EXISTS",
    IdempotencyPattern.CREATE_SCHEMA: "CREATE SCHEMA IF NOT EXISTS",
    IdempotencyPattern.CREATE_SEQUENCE: "CREATE SEQUENCE IF NOT EXISTS",
    IdempotencyPattern.ALTER_TABLE_ADD_COLUMN: "ALTER TABLE … ADD COLUMN IF NOT EXISTS",
    IdempotencyPattern.DROP_TABLE: "DROP TABLE IF EXISTS",
    IdempotencyPattern.DROP_INDEX: "DROP INDEX IF EXISTS",
    IdempotencyPattern.DROP_FUNCTION: "DROP FUNCTION IF EXISTS",
    IdempotencyPattern.DROP_VIEW: "DROP VIEW IF EXISTS",
    IdempotencyPattern.DROP_TYPE: "DROP TYPE IF EXISTS",
    IdempotencyPattern.DROP_SCHEMA: "DROP SCHEMA IF EXISTS",
    IdempotencyPattern.DROP_SEQUENCE: "DROP SEQUENCE IF EXISTS",
}


def list_patterns() -> list[PatternCatalogEntry]:
    """Build a machine-readable catalog of all detection patterns.

    Read-only: no DB connection, no config file, no migrations directory.
    Returned entries are JSON-serialisable (no ``re.Pattern`` objects).

    Returns:
        One :class:`PatternCatalogEntry` per :data:`PATTERNS` entry, in
        the same order. Stable contract — frozen at ``version: "1"``.
    """
    catalog: list[PatternCatalogEntry] = []
    for pdef in PATTERNS:
        has_skip = pdef.skip_regex is not None
        catalog.append(
            PatternCatalogEntry(
                id=pdef.pattern.name,
                description=_DESCRIPTIONS.get(pdef.pattern, ""),
                severity=pdef.severity,
                has_skip_regex=has_skip,
                skip_hint=_SKIP_HINTS.get(pdef.pattern) if has_skip else None,
                has_auto_fix=pdef.pattern.fix_available,
                template_fillable=pdef.pattern in TEMPLATE_FILLABLE,
            )
        )
    return catalog


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

# Pattern to detect DO blocks guarded by a pg_constraint existence check —
# the safe wrapper for ALTER TABLE … ADD CONSTRAINT.
DO_BLOCK_CONSTRAINT_CHECK_PATTERN = re.compile(
    r"DO\s+\$\$.*?pg_constraint.*?ADD\s+CONSTRAINT.*?\$\$",
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
    for pattern in (
        DO_BLOCK_PATTERN,
        DO_BLOCK_TYPE_CHECK_PATTERN,
        DO_BLOCK_CONSTRAINT_CHECK_PATTERN,
    ):
        for match in pattern.finditer(sql):
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


_ADD_CONSTRAINT_PATTERNS = frozenset(
    {
        IdempotencyPattern.ALTER_TABLE_ADD_CONSTRAINT_CHECK,
        IdempotencyPattern.ALTER_TABLE_ADD_CONSTRAINT_PRIMARY_KEY,
        IdempotencyPattern.ALTER_TABLE_ADD_CONSTRAINT_UNIQUE,
    }
)


def _filter_drop_add_constraint_pairs(sql: str, matches: list[PatternMatch]) -> list[PatternMatch]:
    """Suppress ADD CONSTRAINT violations paired with DROP CONSTRAINT IF EXISTS.

    Mirrors :func:`_filter_drop_create_view_pairs`: collects constraint
    names dropped earlier in the same SQL, then strips any matching
    ``ADD CONSTRAINT <name>`` violation. Constraint-name lookup is
    case-insensitive.
    """
    drop_pattern = re.compile(
        r"DROP\s+CONSTRAINT\s+IF\s+EXISTS\s+((?:\w+|\"[^\"]+\"))",
        re.IGNORECASE,
    )
    dropped: set[str] = {m.group(1).lower().replace('"', "") for m in drop_pattern.finditer(sql)}
    if not dropped:
        return matches

    name_re = re.compile(
        r"ADD\s+CONSTRAINT\s+((?:\w+|\"[^\"]+\"))",
        re.IGNORECASE,
    )
    filtered: list[PatternMatch] = []
    for match in matches:
        if match.pattern in _ADD_CONSTRAINT_PATTERNS:
            m = name_re.search(match.sql_snippet)
            if m and m.group(1).lower().replace('"', "") in dropped:
                continue
        filtered.append(match)
    return filtered


_COR_SHAPE_RISK_KINDS: dict[IdempotencyPattern, str] = {
    IdempotencyPattern.CREATE_OR_REPLACE_VIEW_SHAPE_RISK: "VIEW",
    IdempotencyPattern.CREATE_OR_REPLACE_FUNCTION_SHAPE_RISK: "FUNCTION",
    IdempotencyPattern.CREATE_OR_REPLACE_PROCEDURE_SHAPE_RISK: "PROCEDURE",
}


def _earlier_drop_targets(sql: str, kind: str) -> set[str]:
    """Collect object names dropped earlier in the same SQL with DROP IF EXISTS.

    ``kind`` is one of ``"VIEW"``, ``"FUNCTION"``, ``"PROCEDURE"``. Returns
    a set of lowercased, dequoted object names.
    """
    pattern = re.compile(
        rf"DROP\s+{kind}\s+IF\s+EXISTS\s+((?:(?:\w+|\"[^\"]+\")\.)?(?:\w+|\"[^\"]+\"))",
        re.IGNORECASE,
    )
    return {m.group(1).lower().replace('"', "") for m in pattern.finditer(sql)}


def _filter_cor_shape_risk_with_drop(sql: str, matches: list[PatternMatch]) -> list[PatternMatch]:
    """Suppress ``CREATE OR REPLACE`` shape-risk notes paired with a DROP IF EXISTS.

    When the user explicitly chose the safer DROP+CREATE pattern, we don't
    nag them with the heuristic note.
    """
    if not any(m.pattern in _COR_SHAPE_RISK_KINDS for m in matches):
        return matches

    drop_targets_by_kind = {
        kind: _earlier_drop_targets(sql, kind) for kind in {"VIEW", "FUNCTION", "PROCEDURE"}
    }

    name_re = re.compile(
        r"CREATE\s+OR\s+REPLACE\s+(?:VIEW|FUNCTION|PROCEDURE)\s+"
        r"((?:(?:\w+|\"[^\"]+\")\.)?(?:\w+|\"[^\"]+\"))",
        re.IGNORECASE,
    )
    filtered: list[PatternMatch] = []
    for match in matches:
        kind = _COR_SHAPE_RISK_KINDS.get(match.pattern)
        if kind is not None:
            m = name_re.search(match.sql_snippet)
            if m and m.group(1).lower().replace('"', "") in drop_targets_by_kind[kind]:
                continue
        filtered.append(match)
    return filtered


def _filter_drop_create_view_pairs(sql: str, matches: list[PatternMatch]) -> list[PatternMatch]:
    """Remove CREATE VIEW violations that are preceded by DROP VIEW IF EXISTS.

    The DROP IF EXISTS + CREATE VIEW pattern is the correct idempotent
    approach for views (unlike CREATE OR REPLACE VIEW, it handles column
    renames safely). This function detects pairs and removes the CREATE VIEW
    violation from the match list.
    """
    # Collect view names that have a DROP VIEW IF EXISTS
    drop_pattern = re.compile(
        r"DROP\s+VIEW\s+IF\s+EXISTS\s+((?:(?:\w+|\"[^\"]+\")\.)?(?:\w+|\"[^\"]+\"))",
        re.IGNORECASE,
    )
    dropped_views: set[str] = set()
    for m in drop_pattern.finditer(sql):
        dropped_views.add(m.group(1).lower().replace('"', ""))

    if not dropped_views:
        return matches

    # Extract the view name from a CREATE VIEW match snippet
    create_view_re = re.compile(
        r"CREATE\s+VIEW\s+((?:(?:\w+|\"[^\"]+\")\.)?(?:\w+|\"[^\"]+\"))",
        re.IGNORECASE,
    )

    filtered: list[PatternMatch] = []
    for match in matches:
        if match.pattern == IdempotencyPattern.CREATE_VIEW:
            m = create_view_re.search(match.sql_snippet)
            if m and m.group(1).lower().replace('"', "") in dropped_views:
                continue  # Already idempotent via DROP + CREATE
        filtered.append(match)

    return filtered


def detect_non_idempotent_patterns(sql: str) -> list[PatternMatch]:
    """Detect non-idempotent SQL patterns in the given SQL.

    Dispatches to the pglast-backed AST detector when available, falling
    back to the regex detector when pglast isn't installed, when
    ``CONFITURE_IDEMPOTENCY_FORCE_REGEX`` is set, or when pglast raises
    a parse error (typically on partial/templated SQL).

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
    if is_pglast_available() and not _force_regex():
        try:
            return _detect_via_ast(sql)
        except Exception:  # noqa: BLE001 — pglast.parser.ParseError + defensive fallback
            # The AST backend is best-effort; any failure (parse error,
            # unexpected node shape) falls through to the regex backend
            # so partial/templated SQL is still scanned.
            pass
    return _detect_via_regex(sql)


def _detect_via_regex(sql: str) -> list[PatternMatch]:
    """Regex-only implementation of :func:`detect_non_idempotent_patterns`.

    Preserved unchanged from the pre-0.14.0 implementation so the slim
    install path and the force-regex escape hatch keep their existing
    behavior bit-for-bit.
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

            # Build the filled suggestion at detection time so violations
            # carry a copy-pasteable fix block instead of the generic
            # placeholder text. ``captures_from_regex`` returns an
            # all-None ``Captures`` for patterns it can't extract from;
            # ``suggestion_for`` handles that by falling back to the
            # generic suggestion automatically.
            from confiture.core.idempotency._captures import captures_from_regex  # noqa: PLC0415
            from confiture.core.idempotency.suggestion_templates import (  # noqa: PLC0415
                suggestion_for,
            )

            captures = captures_from_regex(pattern_def.pattern, match)
            matches.append(
                PatternMatch(
                    pattern=pattern_def.pattern,
                    sql_snippet=_extract_snippet(sql, match),
                    line_number=_get_line_number(sql, match.start()),
                    start_pos=match.start(),
                    end_pos=match.end(),
                    severity=pattern_def.severity,
                    suggestion=suggestion_for(pattern_def.pattern, captures),
                )
            )

    # Filter out CREATE VIEW violations that are already idempotent via
    # a preceding DROP VIEW IF EXISTS for the same view name.
    # CREATE OR REPLACE VIEW is unsafe for column renames, so the correct
    # idempotent pattern for views is DROP IF EXISTS + CREATE VIEW.
    matches = _filter_drop_create_view_pairs(sql, matches)
    matches = _filter_drop_add_constraint_pairs(sql, matches)
    matches = _filter_cor_shape_risk_with_drop(sql, matches)

    # Sort by position to maintain order
    matches.sort(key=lambda m: m.start_pos)

    return matches
