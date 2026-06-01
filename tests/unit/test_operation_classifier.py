"""Tests for the replica-safety DDL classifier (issue #139, Phase 1)."""

from __future__ import annotations

import pytest

from confiture.core.replica.classifier import (
    AddColumn,
    AddConstraint,
    ChangeColumnType,
    CreateIndex,
    CreateTable,
    DropColumn,
    OperationClassifier,
    RenameColumn,
)

_COLUMN_CASES = [
    (
        "ALTER TABLE t ADD COLUMN c int;",
        AddColumn(table="t", column="c", nullable=True, has_default=False),
    ),
    (
        "ALTER TABLE t ADD COLUMN c int NOT NULL DEFAULT 0;",
        AddColumn(table="t", column="c", nullable=False, has_default=True),
    ),
    ("ALTER TABLE t DROP COLUMN c;", DropColumn(table="t", column="c")),
    ("ALTER TABLE t RENAME COLUMN a TO b;", RenameColumn(table="t", old="a", new="b")),
    ("ALTER TABLE t ALTER COLUMN c TYPE bigint;", ChangeColumnType(table="t", column="c")),
]

_OTHER_CASES = [
    ("CREATE INDEX idx ON t (c);", CreateIndex(table="t", concurrently=False)),
    ("CREATE INDEX CONCURRENTLY idx ON t (c);", CreateIndex(table="t", concurrently=True)),
    (
        "ALTER TABLE t ADD CONSTRAINT ck CHECK (c > 0);",
        AddConstraint(table="t", kind="check", not_valid=False),
    ),
    (
        "ALTER TABLE t ADD CONSTRAINT ck CHECK (c > 0) NOT VALID;",
        AddConstraint(table="t", kind="check", not_valid=True),
    ),
    ("CREATE TABLE t (id int);", CreateTable(table="t")),
]


@pytest.mark.parametrize(("sql", "expected"), _COLUMN_CASES + _OTHER_CASES)
def test_classify(sql: str, expected) -> None:
    assert OperationClassifier().classify(sql) == [expected]


@pytest.mark.parametrize("sql", [c[0] for c in _COLUMN_CASES + _OTHER_CASES])
def test_pglast_and_regex_agree(sql: str, monkeypatch) -> None:
    via_ast = OperationClassifier().classify(sql)
    monkeypatch.setattr("confiture.core.replica.classifier._HAS_PGLAST", False)
    via_regex = OperationClassifier().classify(sql)
    assert via_ast == via_regex, sql


def test_multi_statement_preserves_order() -> None:
    sql = "ALTER TABLE t ADD COLUMN c int; ALTER TABLE t DROP COLUMN d;"
    ops = OperationClassifier().classify(sql)
    assert [type(o).__name__ for o in ops] == ["AddColumn", "DropColumn"]


def test_add_column_nullable_with_default_is_nullable() -> None:
    [op] = OperationClassifier().classify("ALTER TABLE t ADD COLUMN c int DEFAULT 5;")
    assert isinstance(op, AddColumn)
    assert op.nullable is True and op.has_default is True


def test_schema_qualified_table() -> None:
    [op] = OperationClassifier().classify("ALTER TABLE public.t DROP COLUMN c;")
    assert op.table == "public.t"
