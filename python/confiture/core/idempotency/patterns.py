"""Non-idempotent pattern detection: the catalog, and the one entry point.

pglast is the parser (D13). :func:`detect_non_idempotent_patterns` walks the
AST (``ast_detector``) and lets a ``pglast.parser.ParseError`` propagate, so a
file PostgreSQL rejects is reported as unparseable instead of being scanned by
something less exact. :data:`PATTERN_CATALOG` is what ``--list-patterns``
publishes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple, TypedDict

from confiture.core._pglast_enums import enums_are_usable
from confiture.core.idempotency.ast_detector import _detect_via_ast
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


# Compile regex patterns for performance
# Each pattern detects non-idempotent SQL and has an optional skip pattern
# for the idempotent equivalent


# Human-readable descriptions of what each pattern detects.
# Surfaced via ``confiture migrate validate --list-patterns``; keep concise
# (one short sentence per entry, present tense, describes the violation —
# not the fix).
class CatalogEntryDefinition(NamedTuple):
    """One detectable pattern: what it is, how severe, whether an idempotent spelling exists."""

    pattern: IdempotencyPattern
    severity: str
    has_skip_form: bool


# The catalog `--list-patterns` publishes (frozen at ``version: "1"``): one entry
# per pattern the AST detector reports, in the order the regex table once had.
PATTERN_CATALOG: tuple[CatalogEntryDefinition, ...] = (
    CatalogEntryDefinition(IdempotencyPattern.CREATE_TABLE, "error", True),
    CatalogEntryDefinition(IdempotencyPattern.CREATE_UNIQUE_INDEX, "error", True),
    CatalogEntryDefinition(IdempotencyPattern.CREATE_INDEX, "error", True),
    CatalogEntryDefinition(IdempotencyPattern.CREATE_FUNCTION, "error", True),
    CatalogEntryDefinition(IdempotencyPattern.CREATE_PROCEDURE, "error", True),
    CatalogEntryDefinition(IdempotencyPattern.CREATE_VIEW, "error", True),
    CatalogEntryDefinition(IdempotencyPattern.CREATE_TYPE, "error", False),
    CatalogEntryDefinition(IdempotencyPattern.CREATE_EXTENSION, "error", True),
    CatalogEntryDefinition(IdempotencyPattern.CREATE_SCHEMA, "error", True),
    CatalogEntryDefinition(IdempotencyPattern.CREATE_SEQUENCE, "error", True),
    CatalogEntryDefinition(IdempotencyPattern.ALTER_TABLE_ADD_COLUMN, "error", True),
    CatalogEntryDefinition(
        IdempotencyPattern.ALTER_TABLE_ADD_CONSTRAINT_PRIMARY_KEY, "error", False
    ),
    CatalogEntryDefinition(IdempotencyPattern.ALTER_TABLE_ADD_CONSTRAINT_UNIQUE, "error", False),
    CatalogEntryDefinition(IdempotencyPattern.ALTER_TABLE_ADD_CONSTRAINT_CHECK, "error", False),
    CatalogEntryDefinition(IdempotencyPattern.ALTER_TABLE_RENAME_COLUMN, "error", False),
    CatalogEntryDefinition(IdempotencyPattern.ALTER_MATVIEW_OWNER, "error", False),
    CatalogEntryDefinition(IdempotencyPattern.ALTER_VIEW_OWNER, "error", False),
    CatalogEntryDefinition(IdempotencyPattern.ALTER_TABLE_OWNER, "error", False),
    CatalogEntryDefinition(IdempotencyPattern.CREATE_OR_REPLACE_VIEW_SHAPE_RISK, "info", False),
    CatalogEntryDefinition(IdempotencyPattern.CREATE_OR_REPLACE_FUNCTION_SHAPE_RISK, "info", False),
    CatalogEntryDefinition(
        IdempotencyPattern.CREATE_OR_REPLACE_PROCEDURE_SHAPE_RISK, "info", False
    ),
    CatalogEntryDefinition(IdempotencyPattern.DROP_TABLE, "error", True),
    CatalogEntryDefinition(IdempotencyPattern.DROP_INDEX, "error", True),
    CatalogEntryDefinition(IdempotencyPattern.DROP_FUNCTION, "error", True),
    CatalogEntryDefinition(IdempotencyPattern.DROP_VIEW, "error", True),
    CatalogEntryDefinition(IdempotencyPattern.DROP_TYPE, "error", True),
    CatalogEntryDefinition(IdempotencyPattern.DROP_SCHEMA, "error", True),
    CatalogEntryDefinition(IdempotencyPattern.DROP_SEQUENCE, "error", True),
)


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
        One :class:`PatternCatalogEntry` per :data:`PATTERN_CATALOG` entry, in
        the same order. Stable contract — frozen at ``version: "1"``.
    """
    catalog: list[PatternCatalogEntry] = []
    for pdef in PATTERN_CATALOG:
        has_skip = pdef.has_skip_form
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


_ADD_CONSTRAINT_PATTERNS = frozenset(
    {
        IdempotencyPattern.ALTER_TABLE_ADD_CONSTRAINT_CHECK,
        IdempotencyPattern.ALTER_TABLE_ADD_CONSTRAINT_PRIMARY_KEY,
        IdempotencyPattern.ALTER_TABLE_ADD_CONSTRAINT_UNIQUE,
    }
)


_COR_SHAPE_RISK_KINDS: dict[IdempotencyPattern, str] = {
    IdempotencyPattern.CREATE_OR_REPLACE_VIEW_SHAPE_RISK: "VIEW",
    IdempotencyPattern.CREATE_OR_REPLACE_FUNCTION_SHAPE_RISK: "FUNCTION",
    IdempotencyPattern.CREATE_OR_REPLACE_PROCEDURE_SHAPE_RISK: "PROCEDURE",
}


def detect_non_idempotent_patterns(sql: str) -> list[PatternMatch]:
    """Detect non-idempotent SQL patterns in the given SQL.

    Walks the pglast AST; a ``pglast.parser.ParseError`` propagates so the caller
    reports the file as unparseable (ANA-02).

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
    # Raises CONFIG_011 when the installed pglast lacks a member the visitors
    # walk (#192) — a loud stop, never a quiet degrade.
    enums_are_usable()
    # pglast.parser.ParseError propagates: the validator records the file as
    # unparseable (IDEM_UNPARSEABLE), which is a finding, not a clean result.
    return _detect_via_ast(sql)
