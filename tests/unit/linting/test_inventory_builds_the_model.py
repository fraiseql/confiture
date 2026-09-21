"""The inventory builds the schema model: tables with their indexes, enums, sequences.

An index is a table's fact and arrives in a statement of its own, so it is folded
onto the table the tree declared — including its access method, which the differ's
model never read: two indexes that differ only in ``USING`` were one index to it.
"""

from __future__ import annotations

from confiture.core.linting.inventory import build_model
from confiture.core.schema_model import EnumType, Index, Sequence, ref_for

DDL = """\
CREATE TABLE a.t (n INT, m TEXT);
CREATE INDEX ix_n ON a.t (n);
CREATE UNIQUE INDEX ux_m ON a.t (m);
CREATE INDEX hx_n ON a.t USING hash (n);
CREATE INDEX px_n ON a.t (n) WHERE n > 0;
CREATE INDEX ex_m ON a.t (lower(m));
CREATE TYPE a.e AS ENUM ('x', 'y');
CREATE SEQUENCE a.s START WITH 10 INCREMENT BY 5;
CREATE SEQUENCE plain;
"""


def _model():
    return build_model(DDL)


def test_every_index_reaches_its_table() -> None:
    table = _model().tables[ref_for("table", "a", "t")]
    assert table.indexes == (
        Index(name="ix_n", table="a.t", columns=("n",), method="btree"),
        Index(name="ux_m", table="a.t", columns=("m",), unique=True, method="btree"),
        Index(name="hx_n", table="a.t", columns=("n",), method="hash"),
        Index(name="px_n", table="a.t", columns=("n",), where="n > 0", method="btree"),
        Index(name="ex_m", table="a.t", columns=("lower(m)",), method="btree"),
    )


def test_an_index_differing_only_in_its_method_is_another_index() -> None:
    by_name = {ix.name: ix for ix in _model().tables[ref_for("table", "a", "t")].indexes}
    assert by_name["ix_n"].columns == by_name["hx_n"].columns
    assert by_name["ix_n"].method != by_name["hx_n"].method


def test_an_enum_keeps_its_labels_in_order() -> None:
    assert _model().enum_types[ref_for("type", "a", "e")] == EnumType(
        name="e", schema="a", values=("x", "y")
    )


def test_a_sequence_keeps_its_options() -> None:
    model = _model()
    assert model.sequences[ref_for("sequence", "a", "s")] == Sequence(
        name="s", schema="a", start=10, increment=5
    )
    assert model.sequences[ref_for("sequence", None, "plain")] == Sequence(
        name="plain", start=1, increment=1
    )


def test_a_dropped_index_leaves_its_table() -> None:
    model = build_model("CREATE TABLE t (n INT);\nCREATE INDEX ix ON t (n);\nDROP INDEX ix;\n")
    assert model.tables[ref_for("table", None, "t")].indexes == ()


def test_an_unqualified_relation_and_its_public_spelling_are_one() -> None:
    model = build_model("CREATE TABLE t (n INT);")
    assert ref_for("table", "public", "t") in model.tables
