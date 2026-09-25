"""Where a column and a constraint become DDL text: one clause each, every place it is written.

A column is written in a ``CREATE TABLE``, in an ``ADD COLUMN`` and in the
declaration a dropped column's change carries; a constraint after ``ADD`` in an
``ALTER TABLE`` and as an element of a ``CREATE TABLE``. One rendering per
clause is what keeps those places from drifting apart — two renderings of one
CHECK are two chances to write something other than its expression (#316).
Here they take the schema model's own objects, so what a clause says is what
the model holds.

A leaf: the change union serialises a column with :func:`column_body` and the
renderer writes one, so neither may be where the other has to import from.
"""

from __future__ import annotations

from confiture.core.schema_model import Column, Constraint

#: What a column with no written type is called in DDL — none from a parse.
_UNKNOWN_TYPE = "UNKNOWN"


def column_type(column: Column) -> str:
    """The column's type as generated DDL writes it: the spelling, else the identity."""
    return column.raw_sql_type or column.type_key or _UNKNOWN_TYPE


def column_body(column: Column) -> str:
    """The text after a column's name: ``BIGINT NOT NULL GENERATED ALWAYS AS IDENTITY``.

    An identity column and a generated one are written as the schema declared
    them; without that the generated table held a plain column where the schema
    held a sequence or an expression.
    """
    parts = [column_type(column)]
    if column.not_null:
        parts.append("NOT NULL")
    if column.default is not None:
        parts.append(f"DEFAULT {column.default}")
    if column.generated is not None:
        held = "VIRTUAL" if column.generated_kind == "virtual" else "STORED"
        parts.append(f"GENERATED ALWAYS AS ({column.generated}) {held}")
    if column.identity:
        parts.append(f"GENERATED {column.identity.upper()} AS IDENTITY")
    return " ".join(parts)


def column_element(column: Column) -> str:
    """A column as a ``CREATE TABLE`` element: its name, then its body."""
    return f"{column.folded} {column_body(column)}"


def named(name: str, body: str) -> str:
    """``CONSTRAINT n <body>``, or the body alone when the schema named nothing.

    PostgreSQL lets a constraint go unnamed and generates the name at apply time
    — the same name for the DDL confiture writes as for the DDL the author wrote.
    Writing ``child_pid_fkey`` here would be inventing an identifier; omitting it
    is what the author did.
    """
    return f"CONSTRAINT {name} {body}" if name else body


def _columns(names: tuple[str, ...]) -> str:
    return ", ".join(names)


def references(fk: Constraint) -> str | None:
    """``b.parent (id) ON DELETE CASCADE``, as the schema wrote it.

    ``REFERENCES b.parent`` names the parent's primary key, and an empty column
    list is not how PostgreSQL spells that: ``REFERENCES b.parent ()`` is a
    syntax error. The referential actions are rendered because a generated
    foreign key that silently stops cascading applies cleanly and is wrong.
    """
    if not fk.ref_table:
        return None
    clause = f"{fk.ref_table} ({_columns(fk.ref_columns)})" if fk.ref_columns else fk.ref_table
    for keyword, action in (("ON DELETE", fk.on_delete), ("ON UPDATE", fk.on_update)):
        if action:
            clause += f" {keyword} {action}"
    return clause


def index_element(key: str, options: str) -> str:
    """One element of an index or an EXCLUDE: a column bare, an expression in parentheses."""
    element = key if key.isidentifier() else f"({key})"
    return f"{element} {options}" if options else element


def _exclusion(constraint: Constraint) -> str | None:
    """``EXCLUDE USING gist (room_id WITH =, during WITH &&) WHERE (…)``."""
    if not constraint.columns or len(constraint.operators) != len(constraint.columns):
        return None
    options = constraint.key_options or ("",) * len(constraint.columns)
    elements = ", ".join(
        f"{index_element(key, option)} WITH {operator}"
        for key, option, operator in zip(
            constraint.columns, options, constraint.operators, strict=True
        )
    )
    method = f" USING {constraint.method}" if constraint.method else ""
    where = f" WHERE ({constraint.where})" if constraint.where else ""
    return f"EXCLUDE{method} ({elements}){where}"


def _body(constraint: Constraint) -> str | None:
    match constraint.kind:
        case "foreign_key":
            reference = references(constraint)
            if not constraint.columns or reference is None:
                return None
            return f"FOREIGN KEY ({_columns(constraint.columns)}) REFERENCES {reference}"
        case "check":
            return f"CHECK ({constraint.expression})" if constraint.expression else None
        case "unique" | "primary_key":
            keyword = "UNIQUE" if constraint.kind == "unique" else "PRIMARY KEY"
            return f"{keyword} ({_columns(constraint.columns)})" if constraint.columns else None
        case "exclusion":
            return _exclusion(constraint)
    return None


def constraint_body(constraint: Constraint) -> str | None:
    """The text after ``ADD`` in an ``ALTER``, and the element in a ``CREATE TABLE``.

    One clause, both places: a constraint written two ways can disagree with
    itself (#316). ``None`` when the constraint does not hold what the clause
    needs — a CHECK with no expression, a foreign key with no referenced table —
    because writing ``CHECK ()`` produces a migration that fails at apply, and
    inventing the missing half one that succeeds and is wrong. A deferrable
    constraint says so, and when it is checked.
    """
    body = _body(constraint)
    if body is None or constraint.deferrable is None:
        return body
    return f"{body} DEFERRABLE INITIALLY {constraint.deferrable.upper()}"
