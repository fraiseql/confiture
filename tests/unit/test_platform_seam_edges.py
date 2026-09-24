"""The edges the seam's first caller hit (#374), each stated and held.

A frozen model whose mappings could still be written to; an INSERT writer that
wrote an empty file where the COPY writer wrote a header; a column list that
could name one column twice; a profile's name the applier never recorded.
"""

from __future__ import annotations

import copy
import dataclasses
import pickle
from pathlib import Path

import pytest

from confiture import platform
from confiture.config.environment import SeedConfig

MODEL = platform.parse_schema(
    "CREATE SCHEMA app;\n"
    "CREATE TYPE app.mood AS ENUM ('ok');\n"
    "CREATE SEQUENCE app.counter;\n"
    "CREATE TABLE app.item (id INT PRIMARY KEY, label TEXT);\n"
    "CREATE VIEW app.v AS SELECT id FROM app.item;\n"
    "CREATE FUNCTION app.f() RETURNS INT LANGUAGE sql AS 'SELECT 1';\n"
)
MAPPINGS = [f.name for f in dataclasses.fields(platform.SchemaModel)]


@pytest.mark.parametrize("name", MAPPINGS)
def test_a_models_mappings_cannot_be_written_to(name: str) -> None:
    mapping = getattr(MODEL, name)
    key = next(iter(MODEL.tables))
    with pytest.raises(TypeError):
        mapping[key] = None
    with pytest.raises((TypeError, AttributeError)):
        mapping.clear()


def test_a_model_does_not_follow_the_dict_it_was_built_from() -> None:
    tables = dict(MODEL.tables)
    model = platform.SchemaModel(tables=tables)
    tables.clear()
    assert len(model.tables) == 1


def test_a_model_copies_pickles_and_compares_as_it_did() -> None:
    """Nothing in confiture copies a model; a caller may, and a read-only view must let it."""
    assert copy.deepcopy(MODEL) == MODEL
    assert copy.copy(MODEL) == MODEL
    assert pickle.loads(pickle.dumps(MODEL)) == MODEL
    # ``asdict`` turns a ``dict``'s dataclass keys into dicts, which cannot be keys:
    # it raised on the model while its mappings were dicts. A mapping it copies whole.
    assert dataclasses.asdict(MODEL)["tables"] == MODEL.tables
    assert platform.SchemaModel.from_json(MODEL.to_json()) == MODEL
    assert dataclasses.replace(MODEL) == MODEL


def test_a_model_prints_its_objects() -> None:
    assert "item" in repr(MODEL.tables)


def test_an_insert_seed_of_no_rows_names_its_table_and_columns(tmp_path: Path) -> None:
    """As the COPY writer's file does: a reader sees what the empty file is for."""
    for write in (platform.write_copy_seed, platform.write_insert_seed):
        seed = write(
            tmp_path / f"{write.__name__}.sql", "app.item", ["id", "label"], [], model=MODEL
        )
        text = seed.path.read_text()
        assert "app.item (id, label)" in text, text
        assert seed.rows == 0


@pytest.mark.parametrize("write", [platform.write_copy_seed, platform.write_insert_seed])
def test_a_column_named_twice_is_refused(write, tmp_path: Path) -> None:
    path = tmp_path / "twice.sql"
    with pytest.raises(platform.SeedError, match=r"'id'.*twice"):
        write(path, "app.item", ["id", "label", "id"], [{"id": 1, "label": "a"}], model=MODEL)
    assert not path.exists()


def test_a_configured_profile_knows_its_name() -> None:
    config = SeedConfig.model_validate({"profiles": {"lean": {"exclude": ["*_big.sql"]}}})
    assert config.get_profile("lean").name == "lean"


def test_a_profile_named_unlike_its_key_is_refused() -> None:
    with pytest.raises(ValueError, match="lean"):
        SeedConfig.model_validate({"profiles": {"lean": {"name": "fat"}}})
