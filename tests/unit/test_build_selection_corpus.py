"""The shapes this release changes, each pinned against what 1.4.0 did with it.

The compatibility sweep over this repository's own configs and every example
project proves one thing well — that a configuration with every knob at its
default builds exactly what it built before — because all 22 of those
``include_dirs`` entries are plain strings. It is not evidence about any
configuration at risk.

This corpus is that evidence. One minimal project per shape the release
changes, with its 1.4.0 selection and its 1.5.0 selection both recorded in
``expected.json``. The 1.4.0 column was measured once against a ``v1.4.0``
worktree; the 1.5.0 column is recomputed on every run. A shape that stops
differing between the two is a fixture that has rotted into a no-op, and fails
here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from confiture.core.builder import SchemaBuilder
from confiture.exceptions import SchemaError

CORPUS = Path(__file__).resolve().parents[1] / "fixtures" / "build_selection_corpus"
EXPECTED: dict[str, dict] = json.loads((CORPUS / "expected.json").read_text(encoding="utf-8"))


def _selection(project: Path) -> dict:
    builder = SchemaBuilder(env="local", project_dir=project)
    try:
        files = [str(p.relative_to(project)) for p in builder.find_sql_files()]
    except SchemaError as error:
        return {"error": type(error).__name__}
    return {"files": files, "hash": builder.compute_hash()}


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_the_corpus_selects_what_this_release_says_it_does(name: str, monkeypatch) -> None:
    project = CORPUS / name
    monkeypatch.chdir(project)

    assert _selection(project) == EXPECTED[name]["since_1_5_0"]


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_every_at_risk_shape_still_differs_from_1_4_0(name: str) -> None:
    """A shape that no longer changes is a fixture that stopped testing anything."""
    entry = EXPECTED[name]
    differs = entry["before_1_5_0"] != entry["since_1_5_0"]

    assert differs is entry["changed"], (
        f"{name}: recorded changed={entry['changed']}, measured {differs}"
    )


def test_the_corpus_covers_both_directions() -> None:
    """A build can grow as well as shrink, and the corpus holds one of each."""
    grew = [
        name
        for name, entry in EXPECTED.items()
        if "files" in entry["before_1_5_0"]
        and "files" in entry["since_1_5_0"]
        and set(entry["since_1_5_0"]["files"]) - set(entry["before_1_5_0"]["files"])
    ]
    shrank = [
        name
        for name, entry in EXPECTED.items()
        if "files" in entry["before_1_5_0"]
        and "files" in entry["since_1_5_0"]
        and set(entry["before_1_5_0"]["files"]) - set(entry["since_1_5_0"]["files"])
    ]

    assert grew, "no shape in the corpus adds a file to the build"
    assert shrank, "no shape in the corpus removes a file from the build"
