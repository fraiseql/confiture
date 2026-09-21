"""A column's length and precision reach the comparison and the DDL.

``Column.raw_sql_type`` held the written spelling only when the canonical type
map *missed*, so every recognised type arrived stripped of its typmod:
``VARCHAR(50)`` became ``VARCHAR`` and ``NUMERIC(10,2)`` became ``NUMERIC``.
Two failures, the pair this campaign keeps finding together:

* generated DDL declared a **different column** than the schema did — an
  unbounded ``varchar`` where the schema said fifty characters;
* and ``VARCHAR(50)`` -> ``VARCHAR(100)`` reported **no change at all**, so
  ``migrate validate --require-migration`` did not ask for a migration.

``type_lattice.same_type`` is the predicate for the second, and says so in its
own docstring: *a column type must keep [typmods] or ``varchar(50)`` and
``varchar(100)`` compare equal*.
"""

from __future__ import annotations

from dataclasses import replace

import pglast
import pytest

from confiture.core.differ import SchemaDiffer
from confiture.core.differ_sql import DifferSQLGenerator
from confiture.core.schema_change import (
    CheckConstraintDropped,
    ColumnAdded,
    ForeignKeyDropped,
    IndexDropped,
    SchemaChange,
    UniqueConstraintDropped,
)
from confiture.core.schema_model import Column


def _column(sql: str, name: str) -> Column:
    column = SchemaDiffer().parse_schema(sql).tables[0].column(name)
    assert column is not None
    return column


def _changes(old: str, new: str) -> list[tuple[str, str | None, str | None]]:
    return [(c.type, c.old_value, c.new_value) for c in SchemaDiffer().compare(old, new).wire()]


class TestTheTypmodSurvivesParsing:
    @pytest.mark.parametrize(
        ("declared", "expected"),
        [
            ("a VARCHAR(50)", "VARCHAR(50)"),
            ("a NUMERIC(10,2)", "NUMERIC(10,2)"),
            ("a NUMERIC(5)", "NUMERIC(5)"),
            ("a CHAR(2)", "bpchar(2)"),
        ],
    )
    def test_a_declared_length_is_kept(self, declared: str, expected: str) -> None:
        assert _column(f"CREATE TABLE t ({declared});", "a").raw_sql_type == expected

    @pytest.mark.parametrize(
        ("declared", "expected"),
        [
            ("a INT", "INTEGER"),
            ("a BOOLEAN", "BOOLEAN"),
            ("a DOUBLE PRECISION", "DOUBLE PRECISION"),
            ("a TEXT", "TEXT"),
        ],
    )
    def test_a_recognised_type_keeps_its_readable_name(self, declared: str, expected: str) -> None:
        """pglast folds the author's keywords into PostgreSQL's internal names —
        ``INT`` arrives as ``int4`` — and writing those back is valid DDL that
        nobody wants to read. Only the typmod comes from the parser."""
        assert _column(f"CREATE TABLE t ({declared});", "a").raw_sql_type == expected

    @pytest.mark.parametrize(
        ("declared", "expected"),
        [
            ("a citext", "citext"),
            ('a "MyType"', "MyType"),
            ("a app.custom_t", "app.custom_t"),
            ("a INT[]", "int4[]"),
        ],
    )
    def test_a_type_the_map_does_not_know_is_left_alone(self, declared: str, expected: str) -> None:
        """Including its case: a quoted ``"MyType"`` is not ``mytype``."""
        assert _column(f"CREATE TABLE t ({declared});", "a").raw_sql_type == expected


class TestAChangedTypmodIsAChange:
    def test_a_widened_varchar_is_reported(self) -> None:
        assert _changes("CREATE TABLE t (a VARCHAR(50));", "CREATE TABLE t (a VARCHAR(100));") == [
            ("CHANGE_COLUMN_TYPE", "VARCHAR(50)", "VARCHAR(100)")
        ]

    def test_a_changed_numeric_scale_is_reported(self) -> None:
        assert _changes(
            "CREATE TABLE t (a NUMERIC(10,2));", "CREATE TABLE t (a NUMERIC(10,4));"
        ) == [("CHANGE_COLUMN_TYPE", "NUMERIC(10,2)", "NUMERIC(10,4)")]

    def test_an_unchanged_type_is_not_a_change(self) -> None:
        assert (
            _changes(
                "CREATE TABLE t (a VARCHAR(50), b NUMERIC(10,2));",
                "CREATE TABLE t (a VARCHAR(50), b NUMERIC(10,2));",
            )
            == []
        )

    @pytest.mark.parametrize(
        ("old", "new"),
        [
            ("INT", "INTEGER"),
            ("INT4", "INTEGER"),
            ("VARCHAR(50)", "CHARACTER VARYING(50)"),
            ("BOOL", "BOOLEAN"),
            ("DECIMAL(5,2)", "NUMERIC(5,2)"),
        ],
    )
    def test_two_spellings_of_one_type_are_not_a_change(self, old: str, new: str) -> None:
        """Deciding that is ``type_lattice``'s job, not a second alias table."""
        assert _changes(f"CREATE TABLE t (a {old});", f"CREATE TABLE t (a {new});") == []

    def test_a_widened_base_type_still_reports_its_readable_names(self) -> None:
        assert _changes("CREATE TABLE t (a INT);", "CREATE TABLE t (a BIGINT);") == [
            ("CHANGE_COLUMN_TYPE", "INTEGER", "BIGINT")
        ]


class TestTheTypmodReachesGeneratedDDL:
    def test_an_added_column_declares_its_length(self) -> None:
        change = next(
            c
            for c in SchemaDiffer()
            .compare("CREATE TABLE t (id INT);", "CREATE TABLE t (id INT, a VARCHAR(50));")
            .changes
            if isinstance(c, ColumnAdded)
        )
        sql = DifferSQLGenerator().generate_up(change)
        pglast.parse_sql(sql)
        assert "a VARCHAR(50)" in sql

    def test_a_new_table_declares_its_lengths(self) -> None:
        declared = "CREATE TABLE tenant.t (a VARCHAR(50), b NUMERIC(10,2), c CHAR(2), d INT);"
        change = SchemaDiffer().compare("", declared).changes[0]
        sql = DifferSQLGenerator().generate_up(change)
        pglast.parse_sql(sql)
        regenerated = SchemaDiffer().parse_schema(sql).tables[0]

        # `line` and `type_text` are where and how each file wrote the column, not
        # what it declares: `CHAR(2)` regenerates as `bpchar(2)`, one type.
        def declared_facts(columns):
            return [replace(c, line=0, type_text=None) for c in columns]

        assert declared_facts(regenerated.columns) == declared_facts(
            SchemaDiffer().parse_schema(declared).tables[0].columns
        )

    def test_an_altered_type_carries_the_length_into_the_statement(self) -> None:
        change = (
            SchemaDiffer()
            .compare(
                "CREATE TABLE tenant.t (a VARCHAR(50));", "CREATE TABLE tenant.t (a VARCHAR(100));"
            )
            .changes[0]
        )
        sql = DifferSQLGenerator().generate_up(change)
        pglast.parse_sql("\n".join(line.split("--")[0] for line in sql.splitlines()))
        assert "TYPE VARCHAR(100)" in sql


class TestEveryDropHasTheDownItCanDerive:
    """``DROP_FOREIGN_KEY`` and its three siblings each carry everything their
    ``ADD`` needs and answered ``-- WARNING: No automatic rollback``.

    The consequence was visible one kind over: a restored column came back
    without the foreign key that hung off it.
    """

    OLD = (
        "CREATE TABLE b.parent (id INT PRIMARY KEY);\n"
        "CREATE TABLE a.t (id INT, u INT, x INT,\n"
        "  CONSTRAINT fk FOREIGN KEY (id) REFERENCES b.parent(id) ON DELETE CASCADE,\n"
        "  CONSTRAINT ck CHECK (id > 0),\n"
        "  CONSTRAINT uq UNIQUE (u));\n"
        "CREATE INDEX ix ON a.t (x);\n"
    )
    NEW = "CREATE TABLE b.parent (id INT PRIMARY KEY);\nCREATE TABLE a.t (id INT, u INT, x INT);\n"

    def _down(self, kind: type[SchemaChange]) -> str:
        change = next(
            c for c in SchemaDiffer().compare(self.OLD, self.NEW).changes if isinstance(c, kind)
        )
        sql = DifferSQLGenerator(force_destructive=True).generate_down(change)
        pglast.parse_sql("\n".join(line.split("--")[0] for line in sql.splitlines()))
        return sql

    def test_a_dropped_foreign_key_comes_back_with_its_action(self) -> None:
        down = self._down(ForeignKeyDropped)
        assert (
            "ADD CONSTRAINT fk FOREIGN KEY (id) REFERENCES b.parent (id) ON DELETE CASCADE" in down
        )

    def test_a_dropped_check_comes_back_with_its_expression(self) -> None:
        assert "ADD CONSTRAINT ck CHECK (id > 0)" in self._down(CheckConstraintDropped)

    def test_a_dropped_unique_constraint_comes_back(self) -> None:
        assert "ADD CONSTRAINT uq UNIQUE (u)" in self._down(UniqueConstraintDropped)

    def test_a_dropped_index_comes_back(self) -> None:
        assert "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix ON a.t (x)" in self._down(IndexDropped)


class TestTheIdentityDecidesTheType:
    def test_two_spellings_of_one_identity_are_one_type_without_a_written_type(self) -> None:
        """A column the model holds with no written spelling compares by ``type_key``.

        Through the lattice, never by string equality: ``int4`` and ``integer``
        are one type whichever side carries which spelling.
        """
        from confiture.core.differ import _types_differ

        old = Column(name="a", folded="a", line=1, type_key="int4")
        new = Column(name="a", folded="a", line=1, type_key="integer")
        assert not _types_differ(old, new)
        assert _types_differ(old, Column(name="a", folded="a", line=1, type_key="bigint"))
