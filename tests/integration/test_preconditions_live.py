"""Every schema precondition, asked of a real database through ``live_catalog``.

The unit tests stub the probes and test what each precondition does with the
answer; this is what the probes answer. Each precondition is checked once where it
must hold and once where it must not, so a probe that always says yes — or always
no — fails here.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

import psycopg
import pytest

from confiture.core.preconditions import (
    ColumnExists,
    ColumnNotExists,
    ColumnType,
    ConstraintExists,
    ConstraintNotExists,
    ForeignKeyExists,
    IndexExists,
    IndexNotExists,
    Precondition,
    SchemaExists,
    SchemaNotExists,
    TableExists,
    TableNotExists,
)

DDL = """
CREATE SCHEMA app;
CREATE TABLE app.parent (id BIGINT PRIMARY KEY);
CREATE TABLE app.child (
    id BIGINT PRIMARY KEY,
    parent_id BIGINT CONSTRAINT fk_parent REFERENCES app.parent (id),
    name VARCHAR(255),
    tags TEXT[],
    ratio FLOAT,
    CONSTRAINT ck_name CHECK (name <> '')
);
CREATE INDEX ix_child_name ON app.child (name);
CREATE VIEW app.v AS SELECT id FROM app.child;
CREATE TABLE public.solo (id INT);
"""


@pytest.fixture
def conn(fresh_database_factory: Callable[[str], str]) -> Iterator[psycopg.Connection]:
    with psycopg.connect(fresh_database_factory("confiture_precond"), autocommit=True) as c:
        c.execute(DDL)
        yield c


HOLDS: list[Precondition] = [
    TableExists("child", schema="app"),
    TableExists("v", schema="app"),
    TableExists("solo"),
    TableNotExists("absent", schema="app"),
    ColumnExists("child", "name", schema="app"),
    ColumnNotExists("child", "absent", schema="app"),
    ColumnType("child", "name", "varchar", schema="app"),
    ColumnType("child", "name", "character varying", schema="app"),
    ColumnType("child", "id", "int8", schema="app"),
    ColumnType("child", "tags", "text[]", schema="app"),
    ColumnType("child", "ratio", "double precision", schema="app"),
    ColumnType("child", "ratio", "float", schema="app"),
    ConstraintExists("child", "ck_name", schema="app"),
    ConstraintExists("child", "fk_parent", schema="app"),
    ConstraintNotExists("child", "absent", schema="app"),
    ForeignKeyExists("child", "parent_id", "parent", "id", schema="app", references_schema="app"),
    IndexExists("child", "ix_child_name", schema="app"),
    IndexNotExists("child", "absent", schema="app"),
    SchemaExists("app"),
    SchemaNotExists("absent"),
]

FAILS: list[Precondition] = [
    TableExists("absent", schema="app"),
    TableNotExists("child", schema="app"),
    ColumnExists("child", "absent", schema="app"),
    ColumnNotExists("child", "name", schema="app"),
    ColumnType("child", "name", "integer", schema="app"),
    ColumnType("child", "tags", "text", schema="app"),
    ConstraintExists("child", "absent", schema="app"),
    ConstraintNotExists("child", "ck_name", schema="app"),
    ForeignKeyExists("child", "parent_id", "solo", "id", schema="app"),
    ForeignKeyExists("child", "name", "parent", "id", schema="app", references_schema="app"),
    IndexExists("parent", "ix_child_name", schema="app"),
    IndexNotExists("child", "ix_child_name", schema="app"),
    SchemaExists("absent"),
    SchemaNotExists("app"),
]


@pytest.mark.parametrize("precondition", HOLDS, ids=str)
def test_a_precondition_that_holds_passes(
    precondition: Precondition, conn: psycopg.Connection
) -> None:
    passed, message = precondition.check(conn)
    assert passed, message


@pytest.mark.parametrize("precondition", FAILS, ids=str)
def test_a_precondition_that_does_not_hold_fails(
    precondition: Precondition, conn: psycopg.Connection
) -> None:
    passed, message = precondition.check(conn)
    assert not passed, message
