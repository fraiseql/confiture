"""A generated index keeps the author's name.

``_compare_indexes`` wrote ``details["index_name"]``; every reader in
``differ_sql`` asked for ``details["name"]``. The key was never present, so
every read took its fallback — and the fallback fabricated one.

Indexes were the one kind spelled differently across that seam: foreign keys,
check constraints and unique constraints all emit ``{"name": obj.name, …}`` and
all read ``details.get("name")``.
"""

from __future__ import annotations

import pglast
import pytest

from confiture.core.differ import SchemaDiffer
from confiture.core.differ_sql import DifferSQLGenerator
from confiture.models.schema import SchemaChange


def _index_changes(old: str, new: str) -> list[SchemaChange]:
    return [c for c in SchemaDiffer().compare(old, new).changes if "INDEX" in c.type]


class TestTheGeneratedIndexHasTheAuthorsName:
    def test_an_added_index_is_created_under_its_own_name(self) -> None:
        (change,) = _index_changes(
            "CREATE TABLE tenant.t (id INT, x TEXT);",
            "CREATE TABLE tenant.t (id INT, x TEXT);\nCREATE INDEX ix ON tenant.t (x);",
        )
        sql = DifferSQLGenerator().generate_up(change)
        assert sql == "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix ON tenant.t (x);\n"
        pglast.parse_sql(sql)

    def test_two_added_indexes_on_one_table_keep_two_names(self) -> None:
        changes = _index_changes(
            "CREATE TABLE t (id INT, x TEXT);",
            "CREATE TABLE t (id INT, x TEXT);\n"
            "CREATE INDEX ix_one ON t (x);\nCREATE INDEX ix_two ON t (id);",
        )
        generator = DifferSQLGenerator()
        assert sorted(generator.generate_up(c) for c in changes) == [
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_one ON t (x);\n",
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_two ON t (id);\n",
        ]

    def test_a_dropped_index_generates_ddl(self) -> None:
        (change,) = _index_changes(
            "CREATE TABLE t (id INT);\nCREATE INDEX ix ON t (id);", "CREATE TABLE t (id INT);"
        )
        assert DifferSQLGenerator().generate_up(change) == (
            "DROP INDEX CONCURRENTLY IF EXISTS ix;\n"
        )

    def test_a_unique_index_is_generated_unique(self) -> None:
        (change,) = _index_changes(
            "CREATE TABLE t (id INT);",
            "CREATE TABLE t (id INT);\nCREATE UNIQUE INDEX ix ON t (id);",
        )
        assert "CREATE UNIQUE INDEX" in DifferSQLGenerator().generate_up(change)

    def test_the_down_of_an_added_index_drops_it_by_name(self) -> None:
        (change,) = _index_changes(
            "CREATE TABLE t (id INT);", "CREATE TABLE t (id INT);\nCREATE INDEX ix ON t (id);"
        )
        assert DifferSQLGenerator().generate_down(change) == (
            "DROP INDEX CONCURRENTLY IF EXISTS ix;\n"
        )

    def test_the_report_still_names_the_index(self) -> None:
        (change,) = _index_changes(
            "CREATE TABLE t (id INT);", "CREATE TABLE t (id INT);\nCREATE INDEX ix ON t (id);"
        )
        assert str(change) == "ADD INDEX ix ON t"


class TestAFabricatedNameIsNotAName:
    """A name confiture made up is indistinguishable from one the author chose."""

    @pytest.mark.parametrize("method", ["generate_up", "generate_down"])
    def test_an_index_change_with_no_name_warns_rather_than_inventing_one(
        self, method: str
    ) -> None:
        change = SchemaChange(type="ADD_INDEX", table="tenant.t", details={"columns": ["x"]})
        sql = getattr(DifferSQLGenerator(), method)(change)
        assert sql.startswith("-- WARNING:")
        assert "idx_" not in sql


class TestNoConstraintNameIsInventedEither:
    """The same rule, one kind over: ``fk_{table}`` / ``chk_{table}`` / ``uq_{table}``.

    Reachable only from a hand-built change — every ``detail_fn`` in the differ
    emits ``name`` — but the fallbacks were written for a bare table and a
    qualified one turns them into illegal identifiers.

    Since #315 a constraint the schema left unnamed is *rendered* unnamed, which
    invents nothing either: PostgreSQL generates the name at apply time. So what
    warns here is a change with nothing to render — no columns, no expression —
    which is what a change carrying no details is. ``tests/unit/
    test_differ_sql_constraints.py`` holds the unnamed-but-complete cases.
    """

    @pytest.mark.parametrize(
        "change_type",
        ["ADD_CONSTRAINT", "ADD_FOREIGN_KEY", "ADD_CHECK_CONSTRAINT", "ADD_UNIQUE_CONSTRAINT"],
    )
    def test_a_nameless_constraint_change_warns(self, change_type: str) -> None:
        sql = DifferSQLGenerator().generate_up(SchemaChange(type=change_type, table="tenant.t"))
        assert sql.startswith("-- WARNING:")
        assert "tenant.t" in sql
