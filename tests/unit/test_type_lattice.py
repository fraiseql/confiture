"""Narrowing vs widening for `ALTER COLUMN … TYPE` (issue #199).

`bigint`→`int` loses data and can abort mid-migration; `int`→`bigint` cannot.
Preflight could not tell them apart because `ChangeColumnType` carried only the
table and column.

Two answers are kept separate on purpose: the *semantic* direction (is data at
risk) and whether PostgreSQL *rewrites* the heap. `varchar(50)`→`text` is
widening **and** rewrite-free; `int`→`bigint` is widening but still rewrites.
"""

from __future__ import annotations

import pytest

from confiture.core.type_lattice import (
    TypeChange,
    changes_rewrite_table,
    compare_types,
    parse_type,
)


@pytest.mark.parametrize(
    ("raw", "name", "precision", "scale"),
    [
        ("bigint", "bigint", None, None),
        ("int8", "bigint", None, None),
        ("INTEGER", "integer", None, None),
        ("varchar(50)", "varchar", 50, None),
        ("character varying(50)", "varchar", 50, None),
        ("numeric(10,2)", "numeric", 10, 2),
        ("text", "text", None, None),
        ("timestamp with time zone", "timestamptz", None, None),
    ],
)
def test_parse_type(raw: str, name: str, precision: int | None, scale: int | None) -> None:
    parsed = parse_type(raw)
    assert parsed is not None
    assert (parsed.name, parsed.precision, parsed.scale) == (name, precision, scale)


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        # integers
        ("integer", "bigint", TypeChange.WIDENING),
        ("bigint", "integer", TypeChange.NARROWING),
        ("smallint", "integer", TypeChange.WIDENING),
        ("integer", "integer", TypeChange.IDENTICAL),
        ("int4", "int8", TypeChange.WIDENING),
        # strings
        ("varchar(50)", "varchar(100)", TypeChange.WIDENING),
        ("varchar(100)", "varchar(50)", TypeChange.NARROWING),
        ("varchar(50)", "text", TypeChange.WIDENING),
        ("text", "varchar(50)", TypeChange.NARROWING),
        ("varchar(50)", "varchar(50)", TypeChange.IDENTICAL),
        # numeric precision/scale
        ("numeric(10,2)", "numeric(12,2)", TypeChange.WIDENING),
        ("numeric(12,2)", "numeric(10,2)", TypeChange.NARROWING),
        ("numeric(10,2)", "numeric(10,4)", TypeChange.NARROWING),
        ("integer", "numeric(20,0)", TypeChange.WIDENING),
        ("numeric", "integer", TypeChange.NARROWING),
        # temporal
        ("date", "timestamp", TypeChange.WIDENING),
        ("timestamp", "date", TypeChange.NARROWING),
        ("timestamp", "timestamptz", TypeChange.LATERAL),
        # floats
        ("real", "double precision", TypeChange.WIDENING),
        ("double precision", "real", TypeChange.NARROWING),
        # cross-family
        ("integer", "text", TypeChange.LATERAL),
        # unknown / user-defined
        ("mood", "text", TypeChange.UNKNOWN),
        ("text", "mood", TypeChange.UNKNOWN),
    ],
)
def test_compare_types(old: str, new: str, expected: TypeChange) -> None:
    assert compare_types(old, new) is expected


def test_missing_old_type_is_unknown() -> None:
    """SQL never carries the old type; absence must never read as safe."""
    assert compare_types(None, "bigint") is TypeChange.UNKNOWN
    assert compare_types("bigint", None) is TypeChange.UNKNOWN
    assert compare_types(None, None) is TypeChange.UNKNOWN


@pytest.mark.parametrize(
    ("old", "new", "rewrites"),
    [
        # PostgreSQL's documented binary-coercible cases: no rewrite.
        ("varchar(50)", "varchar(100)", False),
        ("varchar(50)", "text", False),
        ("varchar", "text", False),
        ("integer", "integer", False),
        # Everything else rewrites, including a semantic widening.
        ("integer", "bigint", True),
        ("varchar(100)", "varchar(50)", True),
        ("text", "varchar(50)", True),
        ("numeric(10,2)", "numeric(12,2)", True),
        # Unknown must not read as free.
        ("mood", "text", True),
        (None, "bigint", True),
    ],
)
def test_changes_rewrite_table(old: str | None, new: str | None, rewrites: bool) -> None:
    assert changes_rewrite_table(old, new) is rewrites


def test_narrowing_is_not_symmetric_with_widening() -> None:
    """A guard against a lattice that accidentally reports both directions alike."""
    assert compare_types("integer", "bigint") is not compare_types("bigint", "integer")


# --------------------------------------------------------------------------- #
# The classifier carries the target type (cycle 3)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("force_regex", [False, True], ids=["ast", "regex"])
@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        ("ALTER TABLE t ALTER COLUMN c TYPE bigint;", "bigint"),
        ("ALTER TABLE t ALTER COLUMN c TYPE varchar(50);", "varchar(50)"),
        ("ALTER TABLE t ALTER COLUMN c TYPE numeric(10,2);", "numeric(10, 2)"),
        ("ALTER TABLE t ALTER COLUMN c SET DATA TYPE text;", "text"),
        ("ALTER TABLE t ALTER COLUMN c TYPE integer USING c::integer;", "integer"),
    ],
)
def test_classifier_carries_new_type(
    sql: str, expected: str, force_regex: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both backends record the target type; the parsed form must agree."""
    from confiture.core.replica.classifier import OperationClassifier

    if force_regex:
        monkeypatch.setenv("CONFITURE_REPLICA_FORCE_REGEX", "1")

    [op] = OperationClassifier().classify(sql)
    assert parse_type(op.new_type) == parse_type(expected)


def test_old_type_is_absent_from_sql() -> None:
    """SQL states only the target, so the direction stays unknown by default."""
    from confiture.core.replica.classifier import OperationClassifier

    [op] = OperationClassifier().classify("ALTER TABLE t ALTER COLUMN c TYPE bigint;")
    assert op.old_type is None
    assert compare_types(op.old_type, op.new_type) is TypeChange.UNKNOWN
