"""A model says what a schema holds only for the sections its reader read.

A database read without its views has no views in its model, and a comparison
that took that silence for absence would call every declared view missing. So
each model carries its :class:`Coverage`: a tree covers every section, a live
read the sections it was asked for, a model built by hand the structural ones.
"""

from __future__ import annotations

from confiture.core.schema_model import SECTIONS, Coverage, SchemaModel
from confiture.core.schema_read import read_text


def test_a_tree_covers_every_section() -> None:
    model = read_text("CREATE TABLE t (id int);\n").model
    assert [section for section, _ in model.coverage.sections] == list(SECTIONS)


def test_a_model_built_by_hand_claims_only_the_structural_sections() -> None:
    assert SchemaModel().coverage.depth("views") is None
    assert SchemaModel().coverage.depth("tables") == "definition"


def test_two_readers_share_the_shallower_depth() -> None:
    deep = Coverage.of({"views": "definition"})
    shallow = Coverage.of({"views": "existence"})
    assert deep.shared(shallow, "views") == "existence"
    assert deep.shared(Coverage(), "views") is None


def test_coverage_crosses_the_wire_and_is_no_part_of_the_schema() -> None:
    read = SchemaModel(coverage=Coverage.of({"tables": "definition", "views": "existence"}))
    again = SchemaModel.from_json(read.to_json())
    assert again.coverage == read.coverage
    assert again == SchemaModel()


def test_a_wire_written_before_coverage_claims_the_structural_sections() -> None:
    old = '{"tables": [], "enum_types": [], "sequences": [], "routines": [], "views": [], "triggers": []}'
    assert SchemaModel.from_json(old).coverage == Coverage()
