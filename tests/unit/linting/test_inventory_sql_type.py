"""A column's expected type is the type PostgreSQL will store, spelled as SQL.

``_sql_type`` was a bare ``RawStream()(typeName)``, which keeps two things the
author did not write and PostgreSQL will not store:

* the ``pg_catalog.`` qualifier pglast attaches — exactly two of the builtin
  spellings get it, ``json`` and ``bit(n)``, and a ``doc_002`` finding once told
  an author to write ``pg_catalog.json`` (#275);
* array **dimensionality**. PostgreSQL records that a column is an array, never
  how many ``[]`` the DDL wrote: ``INTEGER[][]`` *is* ``_int4``, and
  ``format_type`` says ``integer[]``.

The dimension collapse belongs here and not in ``canonical_type``:
``SqlType.dimensions`` is part of a type's identity there — ``text`` and
``text[]`` are two types — and a lattice that dropped the suffix answered
IDENTICAL for a change that rewrites every page.
"""

from __future__ import annotations

import pytest

from confiture.core.linting.inventory import build_inventory


def type_of(ddl: str) -> str | None:
    table = build_inventory(f"CREATE TABLE t ({ddl});").find(None, "t")
    assert table is not None
    return table.columns[0].type_text


@pytest.mark.parametrize(
    ("written", "expected"),
    [
        # The parser's qualifier, dropped.
        ("a JSON", "json"),
        ("a BIT(3)", "bit(3)"),
        ("a JSON[]", "json[]"),
        # Dimensionality, collapsed to one.
        ("a INTEGER[][]", "integer[]"),
        ("a TEXT[][][]", "text[]"),
        ("a INTEGER[]", "integer[]"),
        # Everything else, as written.
        ("a VARCHAR(50)", "varchar(50)"),
        ("a NUMERIC(10, 2)", "numeric(10, 2)"),
        ("a TIMESTAMPTZ", "timestamptz"),
        ("a BIGINT", "bigint"),
        ("a CHAR", "char"),
        ("a BIT VARYING(8)", "bit varying(8)"),
        # A *user* schema qualifier stays: `app.custom_t` and `other.custom_t`
        # are two types, and only `pg_catalog` is the parser's doing.
        ("a core.pos", "core.pos"),
        ("a public.citext", "public.citext"),
    ],
)
def test_the_type_a_column_will_have(written: str, expected: str) -> None:
    assert type_of(written) == expected


def test_a_retyping_alter_renders_the_same_way() -> None:
    """The fold reads `_sql_type` too, so both paths spell a type once."""
    table = build_inventory(
        "CREATE TABLE t (a int); ALTER TABLE t ALTER COLUMN a TYPE INTEGER[][];"
    ).find(None, "t")
    assert table is not None
    assert table.columns[0].type_text == "integer[]"
