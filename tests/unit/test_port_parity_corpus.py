"""The parity corpus: each tree's model as the bytes a second reader must reproduce.

``tests/fixtures/model_goldens/model/*.json`` hold, for ``db/schema`` and every
example tree, ``SchemaModel.to_json()`` — the wire ``confiture schema dump-model``
writes. A port of the reader (the 2027 crate) is accepted when it writes the same
bytes for every file here, so this test holds Python to them first, byte for byte:
a change to what a tree parses to is an edit to these files, refreshed with
``scripts/refresh_model_goldens.py --write --only model`` and named with its reason
under ``## [Unreleased]`` in ``CHANGELOG.md``. It runs in the ``pglast-matrix`` leg:
the corpus is the one artefact that notices a pglast major changing what a tree
parses to.

``CONFITURE_SCHEMA_CORPUS_DIR`` adds real trees with no recorded bytes: each
directory under it — a schema tree, not its seeds, which the model ignores and the
parser still reads — is read twice and must write one text that reads back to the
same model and validates against the published schema. It is not
``CONFITURE_CORPUS_DIR``, which names a directory of ``.py`` migrations for the
static evaluator's floor test. printoptim's 8.4 MB ``db/0_schema`` passes in 36 s.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from confiture.core.schema_exporter import load_schema
from confiture.platform import SchemaModel, parse_schema

REPO = Path(__file__).resolve().parents[2]
MODEL_GOLDENS = REPO / "tests" / "fixtures" / "model_goldens" / "model"


def _recorder():
    script = REPO / "scripts" / "refresh_model_goldens.py"
    spec = importlib.util.spec_from_file_location("refresh_model_goldens", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # a dataclass resolves its annotations through it
    spec.loader.exec_module(module)
    return module


TREES = _recorder().TREES


def _model(tree) -> SchemaModel:
    if tree.env is not None:
        return parse_schema(env=tree.env, project_dir=REPO / tree.project_dir)
    return parse_schema("\n".join([tree.preamble, *((REPO / f).read_text() for f in tree.files)]))


def test_every_recorded_tree_is_in_the_corpus() -> None:
    assert {f"{tree.name}.json" for tree in TREES} == {p.name for p in MODEL_GOLDENS.glob("*.json")}


@pytest.mark.parametrize("tree", TREES, ids=lambda tree: tree.name)
def test_the_reader_writes_the_recorded_bytes(tree) -> None:
    recorded = (MODEL_GOLDENS / f"{tree.name}.json").read_bytes().decode("utf-8")
    assert _model(tree).to_json() + "\n" == recorded


def _corpus() -> list[Path]:
    root = os.environ.get("CONFITURE_SCHEMA_CORPUS_DIR")
    if not root:
        return []
    return sorted(p for p in Path(root).iterdir() if p.is_dir() and any(p.rglob("*.sql")))


@pytest.mark.skipif(
    not os.environ.get("CONFITURE_SCHEMA_CORPUS_DIR"),
    reason="set CONFITURE_SCHEMA_CORPUS_DIR to a directory of schema trees",
)
@pytest.mark.parametrize("tree", _corpus(), ids=lambda p: p.name)
def test_a_real_tree_writes_one_text(tree: Path) -> None:
    text = parse_schema(tree).to_json()
    assert parse_schema(tree).to_json() == text
    assert SchemaModel.from_json(text).to_json() == text
    validator = Draft202012Validator(load_schema("schema-model.schema.json"))
    assert list(validator.iter_errors(json.loads(text))) == []
