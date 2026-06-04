"""Shared constants for the ``_migrator`` package.

Pure data extracted from ``engine.py`` so the concern
modules (engine / apply / baseline) can share one copy without a runtime
import cycle.
"""

from __future__ import annotations

import re

# Matches the psycopg error raised when an ALTER would rename a view column,
# used to attach a dependent-views resolution hint to the migration failure.
_VIEW_COLUMN_RENAME_RE = re.compile(r"cannot change name of view column", re.IGNORECASE)

# Allows 'table_name' or 'schema.table_name' (letters, digits, underscores only).
_VALID_TABLE_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)?$")

# PostgreSQL reserved words that must never be used as bare table names.
# pgsql.Identifier quotes them correctly in SQL, but they would confuse anyone
# writing ad-hoc queries against the tracking table.
_POSTGRES_RESERVED_WORDS = frozenset(
    {
        "all",
        "analyse",
        "analyze",
        "and",
        "any",
        "array",
        "as",
        "asc",
        "asymmetric",
        "both",
        "case",
        "cast",
        "check",
        "collate",
        "column",
        "constraint",
        "create",
        "cross",
        "current_catalog",
        "current_date",
        "current_role",
        "current_schema",
        "current_time",
        "current_timestamp",
        "current_user",
        "default",
        "deferrable",
        "desc",
        "distinct",
        "do",
        "else",
        "end",
        "except",
        "false",
        "fetch",
        "for",
        "foreign",
        "from",
        "full",
        "grant",
        "group",
        "having",
        "ilike",
        "in",
        "initially",
        "inner",
        "intersect",
        "into",
        "is",
        "isnull",
        "join",
        "lateral",
        "leading",
        "left",
        "like",
        "limit",
        "localtime",
        "localtimestamp",
        "natural",
        "not",
        "notnull",
        "null",
        "offset",
        "on",
        "only",
        "or",
        "order",
        "outer",
        "overlaps",
        "placing",
        "primary",
        "references",
        "returning",
        "right",
        "row",
        "select",
        "session_user",
        "similar",
        "some",
        "symmetric",
        "table",
        "tablesample",
        "then",
        "to",
        "trailing",
        "true",
        "union",
        "unique",
        "user",
        "using",
        "variadic",
        "verbose",
        "when",
        "where",
        "window",
        "with",
    }
)
