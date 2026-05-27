"""Captures-driven suggestion templates for idempotency violations.

The regex and AST detectors both feed a normalized
:class:`~confiture.core.idempotency._captures.Captures` into
:func:`suggestion_for`, which dispatches by
:class:`~confiture.core.idempotency.models.IdempotencyPattern` and
returns a copy-pasteable SQL block with the captured identifiers
inlined.

When a required field on :class:`Captures` is missing (or the pattern
is in :data:`TEMPLATE_NOT_AVAILABLE`), the function returns the
generic pattern suggestion with an explicit
:data:`NO_TEMPLATE_AVAILABLE_MARKER` appended.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeAlias

from confiture.core.idempotency._captures import Captures
from confiture.core.idempotency._naming import qualify
from confiture.core.idempotency.models import IdempotencyPattern

NO_TEMPLATE_AVAILABLE_MARKER = "no auto-template available — manual fix required"


_TemplateFn: TypeAlias = Callable[[Captures], str | None]


def _t_create_table(cap: Captures) -> str | None:
    qname = qualify(cap.schema, cap.table)
    if qname is None:
        return None
    return f"CREATE TABLE IF NOT EXISTS {qname} ( ... );"


def _t_create_index(cap: Captures) -> str | None:
    if not cap.index_name:
        return None
    idx = qualify(None, cap.index_name)
    target = qualify(cap.schema, cap.table)
    target_clause = f" ON {target}" if target else ""
    return f"CREATE INDEX IF NOT EXISTS {idx}{target_clause} ( ... );"


def _t_create_unique_index(cap: Captures) -> str | None:
    if not cap.index_name:
        return None
    idx = qualify(None, cap.index_name)
    target = qualify(cap.schema, cap.table)
    target_clause = f" ON {target}" if target else ""
    return f"CREATE UNIQUE INDEX IF NOT EXISTS {idx}{target_clause} ( ... );"


def _t_create_view(cap: Captures) -> str | None:
    qname = qualify(cap.schema, cap.view)
    if qname is None:
        return None
    return f"DROP VIEW IF EXISTS {qname} CASCADE;\nCREATE VIEW {qname} AS\n    SELECT ...;"


def _t_create_or_replace_view_shape_risk(cap: Captures) -> str | None:
    qname = qualify(cap.schema, cap.view)
    if qname is None:
        return None
    return (
        "-- For shape changes (column add/rename/reorder), use:\n"
        f"DROP VIEW IF EXISTS {qname} CASCADE;\n"
        f"CREATE VIEW {qname} AS\n    SELECT ...;"
    )


def _t_create_type_enum(cap: Captures) -> str | None:
    qname = qualify(cap.schema, cap.type_name)
    if qname is None:
        return None
    return (
        "DO $$ BEGIN\n"
        f"    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = '{cap.type_name}') THEN\n"
        f"        CREATE TYPE {qname} AS ENUM ( ... );\n"
        "    END IF;\n"
        "END $$;"
    )


def _t_create_schema(cap: Captures) -> str | None:
    if not cap.schema:
        return None
    return f"CREATE SCHEMA IF NOT EXISTS {qualify(None, cap.schema)};"


def _t_create_sequence(cap: Captures) -> str | None:
    qname = qualify(cap.schema, cap.sequence)
    if qname is None:
        return None
    return f"CREATE SEQUENCE IF NOT EXISTS {qname};"


def _t_create_extension(cap: Captures) -> str | None:
    if not cap.extension:
        return None
    return f"CREATE EXTENSION IF NOT EXISTS {qualify(None, cap.extension)};"


def _t_alter_add_column(cap: Captures) -> str | None:
    qname = qualify(cap.schema, cap.table)
    if qname is None or not cap.column:
        return None
    col = qualify(None, cap.column)
    return f"ALTER TABLE {qname}\n    ADD COLUMN IF NOT EXISTS {col} <TYPE>;"


def _t_alter_add_constraint_check(cap: Captures) -> str | None:
    qname = qualify(cap.schema, cap.table)
    if qname is None or not cap.constraint:
        return None
    cname = qualify(None, cap.constraint)
    return (
        f"ALTER TABLE {qname}\n"
        f"    DROP CONSTRAINT IF EXISTS {cname};\n"
        f"ALTER TABLE {qname}\n"
        f"    ADD CONSTRAINT {cname} CHECK ( ... );"
    )


def _t_alter_add_constraint_primary_key(cap: Captures) -> str | None:
    qname = qualify(cap.schema, cap.table)
    if qname is None or not cap.constraint:
        return None
    cname = qualify(None, cap.constraint)
    return (
        f"ALTER TABLE {qname}\n"
        f"    DROP CONSTRAINT IF EXISTS {cname};\n"
        f"ALTER TABLE {qname}\n"
        f"    ADD CONSTRAINT {cname} PRIMARY KEY ( ... );"
    )


def _t_alter_add_constraint_unique(cap: Captures) -> str | None:
    qname = qualify(cap.schema, cap.table)
    if qname is None or not cap.constraint:
        return None
    cname = qualify(None, cap.constraint)
    return (
        f"ALTER TABLE {qname}\n"
        f"    DROP CONSTRAINT IF EXISTS {cname};\n"
        f"ALTER TABLE {qname}\n"
        f"    ADD CONSTRAINT {cname} UNIQUE ( ... );"
    )


def _t_alter_rename_column(cap: Captures) -> str | None:
    qname = qualify(cap.schema, cap.table)
    if qname is None or not cap.column or not cap.new_column:
        return None
    old = qualify(None, cap.column)
    new = qualify(None, cap.new_column)
    table_literal = cap.table
    column_literal = cap.column
    new_literal = cap.new_column
    return (
        "DO $$ BEGIN\n"
        "    IF EXISTS (\n"
        "        SELECT 1 FROM information_schema.columns\n"
        f"        WHERE table_name = '{table_literal}' AND column_name = '{column_literal}'\n"
        "    ) AND NOT EXISTS (\n"
        "        SELECT 1 FROM information_schema.columns\n"
        f"        WHERE table_name = '{table_literal}' AND column_name = '{new_literal}'\n"
        "    ) THEN\n"
        f"        ALTER TABLE {qname} RENAME COLUMN {old} TO {new};\n"
        "    END IF;\n"
        "END $$;"
    )


def _t_alter_table_owner(cap: Captures) -> str | None:
    qname = qualify(cap.schema, cap.table)
    if qname is None:
        return None
    schema = cap.schema or "public"
    return (
        "DO $$ BEGIN\n"
        "    IF EXISTS (\n"
        "        SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace\n"
        f"        WHERE n.nspname = '{schema}' AND c.relname = '{cap.table}'\n"
        "    ) THEN\n"
        f"        ALTER TABLE {qname} OWNER TO <new_owner>;\n"
        "    END IF;\n"
        "END $$;"
    )


def _t_alter_view_owner(cap: Captures) -> str | None:
    qname = qualify(cap.schema, cap.view)
    if qname is None:
        return None
    schema = cap.schema or "public"
    return (
        "DO $$ BEGIN\n"
        "    IF EXISTS (\n"
        "        SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace\n"
        f"        WHERE n.nspname = '{schema}' AND c.relname = '{cap.view}'\n"
        "    ) THEN\n"
        f"        ALTER VIEW {qname} OWNER TO <new_owner>;\n"
        "    END IF;\n"
        "END $$;"
    )


def _t_alter_matview_owner(cap: Captures) -> str | None:
    qname = qualify(cap.schema, cap.view)
    if qname is None:
        return None
    schema = cap.schema or "public"
    return (
        "DO $$ BEGIN\n"
        "    IF EXISTS (\n"
        "        SELECT 1 FROM pg_matviews\n"
        f"        WHERE schemaname = '{schema}' AND matviewname = '{cap.view}'\n"
        "    ) THEN\n"
        f"        ALTER MATERIALIZED VIEW {qname} OWNER TO <new_owner>;\n"
        "    END IF;\n"
        "END $$;"
    )


def _t_drop_table(cap: Captures) -> str | None:
    qname = qualify(cap.schema, cap.table)
    if qname is None:
        return None
    return f"DROP TABLE IF EXISTS {qname};"


def _t_drop_index(cap: Captures) -> str | None:
    qname = qualify(cap.schema, cap.table)
    if qname is None:
        return None
    return f"DROP INDEX IF EXISTS {qname};"


def _t_drop_view(cap: Captures) -> str | None:
    qname = qualify(cap.schema, cap.table)
    if qname is None:
        return None
    return f"DROP VIEW IF EXISTS {qname};"


def _t_drop_type(cap: Captures) -> str | None:
    qname = qualify(cap.schema, cap.table)
    if qname is None:
        return None
    return f"DROP TYPE IF EXISTS {qname};"


def _t_drop_schema(cap: Captures) -> str | None:
    if not cap.table:  # drop visitor stores name in .table
        return None
    return f"DROP SCHEMA IF EXISTS {qualify(None, cap.table)};"


def _t_drop_sequence(cap: Captures) -> str | None:
    qname = qualify(cap.schema, cap.table)
    if qname is None:
        return None
    return f"DROP SEQUENCE IF EXISTS {qname};"


_TEMPLATES: dict[IdempotencyPattern, _TemplateFn] = {
    IdempotencyPattern.CREATE_TABLE: _t_create_table,
    IdempotencyPattern.CREATE_INDEX: _t_create_index,
    IdempotencyPattern.CREATE_UNIQUE_INDEX: _t_create_unique_index,
    IdempotencyPattern.CREATE_VIEW: _t_create_view,
    IdempotencyPattern.CREATE_OR_REPLACE_VIEW_SHAPE_RISK: _t_create_or_replace_view_shape_risk,
    IdempotencyPattern.CREATE_TYPE: _t_create_type_enum,
    IdempotencyPattern.CREATE_SCHEMA: _t_create_schema,
    IdempotencyPattern.CREATE_SEQUENCE: _t_create_sequence,
    IdempotencyPattern.CREATE_EXTENSION: _t_create_extension,
    IdempotencyPattern.ALTER_TABLE_ADD_COLUMN: _t_alter_add_column,
    IdempotencyPattern.ALTER_TABLE_ADD_CONSTRAINT_CHECK: _t_alter_add_constraint_check,
    IdempotencyPattern.ALTER_TABLE_ADD_CONSTRAINT_PRIMARY_KEY: _t_alter_add_constraint_primary_key,
    IdempotencyPattern.ALTER_TABLE_ADD_CONSTRAINT_UNIQUE: _t_alter_add_constraint_unique,
    IdempotencyPattern.ALTER_TABLE_RENAME_COLUMN: _t_alter_rename_column,
    IdempotencyPattern.ALTER_TABLE_OWNER: _t_alter_table_owner,
    IdempotencyPattern.ALTER_VIEW_OWNER: _t_alter_view_owner,
    IdempotencyPattern.ALTER_MATVIEW_OWNER: _t_alter_matview_owner,
    IdempotencyPattern.DROP_TABLE: _t_drop_table,
    IdempotencyPattern.DROP_INDEX: _t_drop_index,
    IdempotencyPattern.DROP_VIEW: _t_drop_view,
    IdempotencyPattern.DROP_TYPE: _t_drop_type,
    IdempotencyPattern.DROP_SCHEMA: _t_drop_schema,
    IdempotencyPattern.DROP_SEQUENCE: _t_drop_sequence,
}


def suggestion_for(pattern: IdempotencyPattern, captures: Captures) -> str:
    """Return the filled suggestion for ``pattern`` given ``captures``.

    Dispatch order:

    1. ``pattern`` has a template registered and the template returns a
       non-``None`` filled string → return that.
    2. ``pattern`` has a template but captures are incomplete → return
       the generic :attr:`IdempotencyPattern.suggestion` (no marker).
    3. ``pattern`` has no template registered (it's in
       :data:`TEMPLATE_NOT_AVAILABLE`) → return the generic suggestion
       with :data:`NO_TEMPLATE_AVAILABLE_MARKER` appended.
    """
    template = _TEMPLATES.get(pattern)
    if template is None:
        return f"{pattern.suggestion} ({NO_TEMPLATE_AVAILABLE_MARKER})"
    filled = template(captures)
    if filled is not None:
        return filled
    return pattern.suggestion
