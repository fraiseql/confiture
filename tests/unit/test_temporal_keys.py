"""A temporal key is not a plain key: ``WITHOUT OVERLAPS`` and ``PERIOD`` are modelled (#604).

PostgreSQL 18's ``PRIMARY KEY (id, valid WITHOUT OVERLAPS)`` is an exclusion over
the period, not a btree uniqueness: two rows may share ``id`` when their periods
do not overlap. Read as ``PRIMARY KEY (id, valid)`` it told a reader of the model
there was a uniqueness that is not there, drift saw no change between the two,
and generated DDL wrote the plain key.
"""

import re
from dataclasses import replace
from typing import Any
from unittest.mock import MagicMock

import pglast
import pytest

from confiture.core.ddl_clauses import constraint_body
from confiture.core.differ import SchemaDiffer
from confiture.core.differ_sql import DifferSQLGenerator
from confiture.core.drift import DriftReport, DriftSeverity, DriftType, SchemaDriftDetector
from confiture.core.fk_extractor import extract_and_strip_fks, generate_alter_statements
from confiture.core.schema_change import (
    ForeignKeyAdded,
    ForeignKeyDropped,
    PrimaryKeyAdded,
    PrimaryKeyDropped,
    UniqueConstraintAdded,
    UniqueConstraintDropped,
)
from confiture.core.schema_model import Constraint, RelationName, SchemaModel
from confiture.core.schema_read import read_text
from tests.unit._schema_models import column, model, table

PARENT = "CREATE TABLE p (id INT4RANGE, valid DATERANGE, CONSTRAINT p_pkey {key});\n"
TEMPORAL_PK = PARENT.format(key="PRIMARY KEY (id, valid WITHOUT OVERLAPS)")
PLAIN_PK = PARENT.format(key="PRIMARY KEY (id, valid)")

CHILD = "CREATE TABLE c (id INT4RANGE, valid DATERANGE, CONSTRAINT c_fk {key});\n"
TEMPORAL_FK = CHILD.format(key="FOREIGN KEY (id, PERIOD valid) REFERENCES p (id, PERIOD valid)")
PLAIN_FK = CHILD.format(key="FOREIGN KEY (id, valid) REFERENCES p (id, valid)")

UNIQUE = "CREATE TABLE u (id INT4RANGE, valid DATERANGE, CONSTRAINT u_key {key});\n"
TEMPORAL_UNIQUE = UNIQUE.format(key="UNIQUE (id, valid WITHOUT OVERLAPS)")
PLAIN_UNIQUE = UNIQUE.format(key="UNIQUE (id, valid)")


def _constraint(sql: str) -> Constraint:
    (table_,) = SchemaDiffer().parse_schema(sql).tables
    (constraint,) = table_.constraints
    return constraint


def _parsed(sql: str) -> Any:
    """The one ``Constraint`` node an ``ALTER TABLE … ADD`` statement in *sql* adds."""
    (statement,) = pglast.parse_sql(sql)
    return statement.stmt.cmds[0].def_


class TestTheModelHoldsIt:
    @pytest.mark.parametrize(
        ("sql", "temporal"),
        [
            pytest.param(TEMPORAL_PK, True, id="primary-key-without-overlaps"),
            pytest.param(PLAIN_PK, False, id="primary-key"),
            pytest.param(TEMPORAL_UNIQUE, True, id="unique-without-overlaps"),
            pytest.param(PLAIN_UNIQUE, False, id="unique"),
            pytest.param(TEMPORAL_FK, True, id="foreign-key-period"),
            pytest.param(PLAIN_FK, False, id="foreign-key"),
        ],
    )
    def test_a_temporal_key_says_so(self, sql: str, temporal: bool) -> None:
        assert _constraint(sql).temporal is temporal

    def test_a_temporal_key_and_a_plain_one_are_not_one_constraint(self) -> None:
        assert _constraint(TEMPORAL_PK) != _constraint(PLAIN_PK)

    def test_one_added_by_alter(self) -> None:
        sql = (
            "CREATE TABLE u (id INT4RANGE, valid DATERANGE);\n"
            "ALTER TABLE u ADD CONSTRAINT u_key UNIQUE (id, valid WITHOUT OVERLAPS);\n"
        )
        assert _constraint(sql) == Constraint(
            kind="unique", name="u_key", columns=("id", "valid"), temporal=True
        )

    def test_a_foreign_key_to_the_referenced_key_keeps_its_period(self) -> None:
        sql = CHILD.format(key="FOREIGN KEY (id, PERIOD valid) REFERENCES p")
        assert _constraint(sql) == Constraint(
            kind="foreign_key",
            name="c_fk",
            columns=("id", "valid"),
            ref_table=RelationName(None, "p"),
            temporal=True,
        )

    def test_a_model_written_before_it_reads_as_plain(self) -> None:
        wire = read_text(PLAIN_PK).model.to_json()
        assert '"temporal": false' in wire
        wire = re.sub(r',?\s*"temporal": false', "", wire)
        assert '"temporal"' not in wire
        (table_,) = SchemaModel.from_json(wire).tables.values()
        assert table_.constraints[0].temporal is False


class TestTheClauseWritesIt:
    @pytest.mark.parametrize(
        "sql",
        [
            pytest.param(TEMPORAL_PK, id="primary-key"),
            pytest.param(TEMPORAL_UNIQUE, id="unique"),
            pytest.param(TEMPORAL_FK, id="foreign-key"),
            pytest.param(
                CHILD.format(key="FOREIGN KEY (id, PERIOD valid) REFERENCES p"),
                id="foreign-key-to-the-key",
            ),
        ],
    )
    def test_the_clause_reads_back_as_the_constraint(self, sql: str) -> None:
        constraint = _constraint(sql)
        body = constraint_body(constraint)
        assert body is not None
        assert _constraint(
            f"{sql.split('CONSTRAINT', maxsplit=1)[0]}CONSTRAINT {constraint.name} {body});"
        ) == (constraint)

    def test_a_key_writes_without_overlaps_on_its_last_column(self) -> None:
        node = _parsed(f"ALTER TABLE p ADD {constraint_body(_constraint(TEMPORAL_PK))}")
        assert node.without_overlaps is True
        assert [k.sval for k in node.keys] == ["id", "valid"]

    def test_a_foreign_key_writes_period_on_both_sides(self) -> None:
        node = _parsed(f"ALTER TABLE c ADD {constraint_body(_constraint(TEMPORAL_FK))}")
        assert (node.fk_with_period, node.pk_with_period) == (True, True)

    def test_a_two_pass_build_moves_the_key_with_its_period(self) -> None:
        _stripped, moved = extract_and_strip_fks(TEMPORAL_FK)
        node = _parsed(generate_alter_statements(moved))
        assert (node.fk_with_period, node.pk_with_period) == (True, True)

    def test_a_plain_key_writes_no_period(self) -> None:
        node = _parsed(f"ALTER TABLE p ADD {constraint_body(_constraint(PLAIN_PK))}")
        assert node.without_overlaps is False


def _changes(old: str, new: str) -> list[Any]:
    return SchemaDiffer().compare(old, new).changes


class TestTheDiffSeesIt:
    @pytest.mark.parametrize(
        ("plain", "temporal", "dropped", "added"),
        [
            pytest.param(
                PLAIN_PK, TEMPORAL_PK, PrimaryKeyDropped, PrimaryKeyAdded, id="primary-key"
            ),
            pytest.param(
                PLAIN_UNIQUE,
                TEMPORAL_UNIQUE,
                UniqueConstraintDropped,
                UniqueConstraintAdded,
                id="unique",
            ),
            pytest.param(PLAIN_FK, TEMPORAL_FK, ForeignKeyDropped, ForeignKeyAdded, id="fk"),
        ],
    )
    def test_becoming_temporal_replaces_the_constraint(
        self, plain: str, temporal: str, dropped: type, added: type
    ) -> None:
        old, new = _constraint(plain), _constraint(temporal)
        changes = _changes(plain, temporal)
        assert [type(c) for c in changes] == [dropped, added]
        assert (changes[0].constraint, changes[1].constraint) == (old, new)

    def test_the_same_temporal_key_is_no_change(self) -> None:
        assert _changes(TEMPORAL_PK, TEMPORAL_PK) == []

    def test_unnamed_keys_beside_each_other_pair_with_their_own(self) -> None:
        both = "CREATE TABLE u (id INT4RANGE, valid DATERANGE, {}, {});"
        temporal, plain = "UNIQUE (id, valid WITHOUT OVERLAPS)", "UNIQUE (id, valid)"
        assert _changes(both.format(temporal, plain), both.format(plain, temporal)) == []

    @pytest.mark.parametrize(
        ("old", "new", "temporal_after_up"),
        [
            pytest.param(PLAIN_PK, TEMPORAL_PK, True, id="plain-to-temporal"),
            pytest.param(TEMPORAL_PK, PLAIN_PK, False, id="temporal-to-plain"),
        ],
    )
    def test_the_generated_ddl_writes_the_new_key_and_its_rollback_the_old(
        self, old: str, new: str, temporal_after_up: bool
    ) -> None:
        changes = _changes(old, new)
        generator = DifferSQLGenerator()
        up = "".join(filter(None, (generator.generate_up(c) for c in changes)))
        down = "".join(filter(None, (generator.generate_down(c) for c in reversed(changes))))

        def adds(sql: str) -> list[bool]:
            return [
                cmd.def_.without_overlaps
                for statement in pglast.parse_sql(sql)
                for cmd in getattr(statement.stmt, "cmds", None) or ()
                if cmd.def_ is not None
            ]

        assert adds(up) == [temporal_after_up]
        assert adds(down) == [not temporal_after_up]

    def test_the_wire_says_temporal_only_where_it_is(self) -> None:
        dropped, added = _changes(PLAIN_PK, TEMPORAL_PK)
        assert "temporal" not in (dropped.to_wire().details or {})
        assert (added.to_wire().details or {})["temporal"] is True


def _drift(expected: SchemaModel, actual: SchemaModel) -> DriftReport:
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value.fetchone.return_value = ("db",)
    return SchemaDriftDetector(conn).compare_schemas(expected, actual)


class TestDriftSeesIt:
    KEY = Constraint(kind="primary_key", name="p_pkey", columns=("id", "valid"), temporal=True)
    FK = Constraint(
        kind="foreign_key",
        name="c_fk",
        columns=("id", "valid"),
        ref_table=RelationName(None, "p"),
        ref_columns=("id", "valid"),
        temporal=True,
    )

    def _users(self, constraint: Constraint) -> SchemaModel:
        columns = (column("id", "int4range", nullable=False), column("valid", "daterange"))
        return model(table("p", *columns, constraints=[constraint]))

    @pytest.mark.parametrize("declared", [KEY, FK], ids=["primary-key", "foreign-key"])
    def test_a_temporal_key_the_database_holds_plain_is_a_mismatch(
        self, declared: Constraint
    ) -> None:
        report = _drift(self._users(declared), self._users(replace(declared, temporal=False)))
        assert [(i.drift_type, i.severity) for i in report.drift_items] == [
            (DriftType.CONSTRAINT_MISMATCH, DriftSeverity.CRITICAL)
        ]

    def test_the_finding_carries_both_definitions(self) -> None:
        (item,) = _drift(
            self._users(self.KEY), self._users(replace(self.KEY, temporal=False))
        ).drift_items
        assert (item.expected, item.actual) == (
            "PRIMARY KEY (id, valid WITHOUT OVERLAPS)",
            "PRIMARY KEY (id, valid)",
        )
