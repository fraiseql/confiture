"""``NULLS NOT DISTINCT`` is in the schema model: read, compared and generated (#623).

PostgreSQL 15+ lets a unique key treat ``NULL`` as a value: with the clause, two
roots of a tree (``fk_parent IS NULL``) cannot share a name. The model held
neither form, so a key that gained or lost the clause was the same key to
``migrate diff`` and to drift, and generated DDL never wrote it. PostgreSQL has no
statement that changes the clause in place, so a change is the key's drop and add.
"""

from __future__ import annotations

import json
from pathlib import Path

import pglast
import pytest
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.ddl_clauses import constraint_body
from confiture.core.differ import SchemaDiffer
from confiture.core.differ_sql import DifferSQLGenerator
from confiture.core.schema_change import (
    IndexAdded,
    IndexDropped,
    UniqueConstraintAdded,
    UniqueConstraintDropped,
)
from confiture.core.schema_model import Constraint, SchemaModel

TABLE = "CREATE TABLE tb_node (id int PRIMARY KEY, fk_parent int, name text);\n"
OLD_INDEX = TABLE + "CREATE UNIQUE INDEX ux_node ON tb_node (fk_parent, name);\n"
NEW_INDEX = TABLE + "CREATE UNIQUE INDEX ux_node ON tb_node (fk_parent, name) NULLS NOT DISTINCT;\n"

KEYED = "CREATE TABLE tb_node (id int PRIMARY KEY, fk_parent int, name text, {key});\n"
OLD_KEY = KEYED.format(key="CONSTRAINT uq_node UNIQUE (fk_parent, name)")
NEW_KEY = KEYED.format(key="CONSTRAINT uq_node UNIQUE NULLS NOT DISTINCT (fk_parent, name)")


def _table(sql: str):
    (table,) = SchemaDiffer().parse_schema(sql).tables
    return table


def _uniques(sql: str) -> list[Constraint]:
    return list(_table(sql).constraints_of("unique"))


class TestTheModelHoldsIt:
    def test_an_index(self) -> None:
        (index,) = _table(NEW_INDEX).indexes
        assert index.nulls_not_distinct is True

    def test_an_index_without_it(self) -> None:
        (index,) = _table(OLD_INDEX).indexes
        assert index.nulls_not_distinct is False

    def test_a_partial_index(self) -> None:
        sql = TABLE + (
            "CREATE UNIQUE INDEX ux ON tb_node (name) NULLS NOT DISTINCT WHERE fk_parent IS NULL;"
        )
        (index,) = _table(sql).indexes
        assert (index.nulls_not_distinct, index.where) == (True, "fk_parent IS NULL")

    def test_a_table_level_constraint(self) -> None:
        (key,) = _uniques(NEW_KEY)
        assert (key.name, key.nulls_not_distinct) == ("uq_node", True)

    def test_a_column_constraint(self) -> None:
        (key,) = _uniques("CREATE TABLE t (id int, code text UNIQUE NULLS NOT DISTINCT);")
        assert (key.columns, key.nulls_not_distinct) == (("code",), True)

    def test_a_constraint_added_by_alter(self) -> None:
        sql = (
            "CREATE TABLE t (id int, code text);\n"
            "ALTER TABLE t ADD CONSTRAINT uq_t UNIQUE NULLS NOT DISTINCT (code);\n"
        )
        (key,) = _uniques(sql)
        assert (key.name, key.nulls_not_distinct) == ("uq_t", True)

    def test_nulls_distinct_spelled_out_is_the_default(self) -> None:
        (key,) = _uniques("CREATE TABLE t (id int, code text UNIQUE NULLS DISTINCT);")
        assert key == Constraint(kind="unique", columns=("code",))

    def test_a_primary_key_never_holds_it(self) -> None:
        (key,) = _table(OLD_KEY).constraints_of("primary_key")
        assert key.nulls_not_distinct is False


class TestTheWire:
    def test_it_travels(self) -> None:
        both = NEW_INDEX + "ALTER TABLE tb_node ADD UNIQUE NULLS NOT DISTINCT (name);"
        model = SchemaDiffer().parse_schema(both).model
        (table,) = json.loads(model.to_json())["tables"]
        assert [i["nulls_not_distinct"] for i in table["indexes"]] == [True]
        assert [c["nulls_not_distinct"] for c in table["constraints"]] == [False, True]
        assert SchemaModel.from_json(model.to_json()) == model

    def test_a_wire_written_before_it_reads_as_distinct(self) -> None:
        sql = OLD_KEY + "CREATE INDEX ix ON tb_node (name);"
        model = SchemaDiffer().parse_schema(sql).model
        wire = json.loads(model.to_json())
        (table,) = wire["tables"]
        for held in (*table["indexes"], *table["constraints"]):
            del held["nulls_not_distinct"]
        assert SchemaModel.from_json(json.dumps(wire)) == model


def _changes(old: str, new: str) -> list:
    return SchemaDiffer().compare(old, new).changes


def _parsed_up(change) -> list:
    sql = DifferSQLGenerator().generate_up(change)
    assert sql is not None
    return [raw.stmt for raw in pglast.parse_sql(sql)]


class TestAChangeIsADropThenAnAdd:
    @pytest.mark.parametrize(("old", "new"), [(OLD_INDEX, NEW_INDEX), (NEW_INDEX, OLD_INDEX)])
    def test_an_index(self, old: str, new: str) -> None:
        assert [type(c) for c in _changes(old, new)] == [IndexDropped, IndexAdded]

    @pytest.mark.parametrize(("old", "new"), [(OLD_KEY, NEW_KEY), (NEW_KEY, OLD_KEY)])
    def test_a_constraint(self, old: str, new: str) -> None:
        assert [type(c) for c in _changes(old, new)] == [
            UniqueConstraintDropped,
            UniqueConstraintAdded,
        ]

    def test_an_unnamed_constraint(self) -> None:
        old = "CREATE TABLE t (id int, code text UNIQUE);"
        new = "CREATE TABLE t (id int, code text UNIQUE NULLS NOT DISTINCT);"
        assert [type(c) for c in _changes(old, new)] == [
            UniqueConstraintDropped,
            UniqueConstraintAdded,
        ]

    def test_unchanged_is_no_change(self) -> None:
        assert _changes(NEW_INDEX, NEW_INDEX) == []
        assert _changes(NEW_KEY, NEW_KEY) == []


class TestTheGeneratedDDLWritesIt:
    def test_the_index_it_creates(self) -> None:
        dropped, added = _changes(OLD_INDEX, NEW_INDEX)
        (create,) = _parsed_up(added)
        assert (create.idxname, create.unique, create.nulls_not_distinct) == ("ux_node", True, True)
        (drop,) = _parsed_up(dropped)
        assert type(drop).__name__ == "DropStmt"

    def test_the_index_it_restores_on_the_way_down(self) -> None:
        dropped, _ = _changes(NEW_INDEX, OLD_INDEX)
        sql = DifferSQLGenerator().generate_down(dropped)
        assert sql is not None
        (create,) = [raw.stmt for raw in pglast.parse_sql(sql)]
        assert create.nulls_not_distinct is True

    def test_a_partial_index_keeps_both_clauses(self) -> None:
        new = TABLE + (
            "CREATE UNIQUE INDEX ux ON tb_node (name) NULLS NOT DISTINCT WHERE fk_parent IS NULL;"
        )
        (added,) = _changes(TABLE, new)
        (create,) = _parsed_up(added)
        assert create.nulls_not_distinct is True
        assert create.whereClause is not None

    def test_the_constraint_it_adds(self) -> None:
        _, added = _changes(OLD_KEY, NEW_KEY)
        (alter,) = _parsed_up(added)
        key = alter.cmds[0].def_
        assert (key.conname, key.nulls_not_distinct) == ("uq_node", True)

    def test_a_new_tables_create_table(self) -> None:
        (added,) = _changes("", NEW_KEY)
        (create,) = _parsed_up(added)
        (key,) = [e for e in create.tableElts if type(e).__name__ == "Constraint" and e.conname]
        assert key.nulls_not_distinct is True

    def test_the_clause_round_trips(self) -> None:
        (key,) = _uniques(NEW_KEY)
        body = constraint_body(key)
        (alter,) = [raw.stmt for raw in pglast.parse_sql(f"ALTER TABLE t ADD {body}")]
        assert alter.cmds[0].def_.nulls_not_distinct is True


def test_migrate_diff_reports_the_issues_two_trees(tmp_path: Path) -> None:
    """The reproduction in #623: ``migrate diff --from old/ --to new/`` saw no change."""
    for side, sql in (("old", OLD_INDEX), ("new", NEW_INDEX)):
        (tmp_path / side).mkdir()
        (tmp_path / side / "schema.sql").write_text(sql)
    result = CliRunner().invoke(
        app,
        [
            "migrate",
            "diff",
            "--from",
            str(tmp_path / "old"),
            "--to",
            str(tmp_path / "new"),
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert [c["type"] for c in payload["changes"]] == ["DROP_INDEX", "ADD_INDEX"]
