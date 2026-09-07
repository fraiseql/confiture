"""The schema exporter serves the one packaged source."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import confiture
from confiture.core.schema_exporter import (
    CLI_BUILT_SCHEMAS,
    MODEL_SCHEMAS,
    SCHEMA_NAMES,
    docs_out_of_sync,
    export_all,
    generate_schema,
    load_schema,
    schema_files,
)

REPO = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("name", SCHEMA_NAMES)
def test_generate_schema_loads_the_mapped_file(name: str) -> None:
    schema = generate_schema(name)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema == load_schema(MODEL_SCHEMAS[name])


def test_generate_schema_unknown_raises() -> None:
    with pytest.raises(KeyError):
        generate_schema("NonExistentModel")


def test_export_all_writes_every_packaged_schema(tmp_path: Path) -> None:
    written = export_all(tmp_path)
    assert sorted(p.name for p in written) == schema_files()
    for path in written:
        json.loads(path.read_text())  # valid JSON


def test_every_packaged_schema_is_a_model_schema_or_cli_built_or_shared() -> None:
    public = {n for n in schema_files() if not n.startswith("_")}
    assert public == set(MODEL_SCHEMAS.values()) | set(CLI_BUILT_SCHEMAS)


def test_docs_copy_is_in_sync() -> None:
    """``docs/reference/json-schemas/`` is written by ``scripts/gen_schemas.py``; CI checks it too."""
    assert docs_out_of_sync(REPO / "docs" / "reference" / "json-schemas") == []


def test_export_all_in_public_api(tmp_path: Path) -> None:
    assert "export_all" in confiture.__all__
    written = confiture.export_all(tmp_path)
    assert len(written) == len(schema_files())
