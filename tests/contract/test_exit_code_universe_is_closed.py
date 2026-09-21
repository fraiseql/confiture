"""The exit-code universe is closed: exactly ``0..8``, and every change is visible.

Two consumers branch on confiture's exit integers without reading its source.
fraisier's Python adapter reads ``confiture --exit-codes-json`` at run time;
fraisier-core's Rust adapter **vendors** that output in
``crates/fraisier-adapter-confiture/src/exit_codes.vendored.json`` and diffs it in
its own test. A ninth integer would be a class neither adapter has, and a moved
symbolic code is a changed vendored file in someone else's repository.

So the integers are pinned, every symbolic code must land on one of them, and the
CLI's payload is recorded here: a difference fails with the regeneration command
for both sides, which turns fraisier-core's red CI into an obligation stated in
this one.
"""

from __future__ import annotations

import difflib
from pathlib import Path

from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.error_codes import (
    CANONICAL_EXIT_CODES,
    EXIT_CODE_MEANINGS,
    EXIT_CODE_SEMANTIC_CLASS,
)

EXIT_CODES = frozenset(range(9))
REPO_ROOT = Path(__file__).resolve().parents[2]
RECORDED = REPO_ROOT / "tests" / "fixtures" / "error_codes" / "exit_codes.json"
VENDORED = "fraisier-core:crates/fraisier-adapter-confiture/src/exit_codes.vendored.json"


def test_exit_code_integers_are_exactly_zero_to_eight() -> None:
    assert set(EXIT_CODE_MEANINGS) == EXIT_CODES
    assert set(EXIT_CODE_SEMANTIC_CLASS) == EXIT_CODES


def test_every_symbolic_code_maps_onto_an_existing_integer() -> None:
    """A new symbolic code is allowed; a new integer is not."""
    stray = {code: exit_ for code, exit_ in CANONICAL_EXIT_CODES.items() if exit_ not in EXIT_CODES}
    assert not stray, f"symbolic codes outside 0..8: {stray}"


def test_exit_codes_json_matches_the_recorded_payload() -> None:
    """``confiture --exit-codes-json`` is byte-identical to the recorded payload."""
    result = CliRunner().invoke(app, ["--exit-codes-json"])
    assert result.exit_code == 0, result.output
    live = result.output
    print(live)
    recorded = RECORDED.read_text()
    if live != recorded:
        diff = "".join(
            difflib.unified_diff(
                recorded.splitlines(keepends=True),
                live.splitlines(keepends=True),
                fromfile=str(RECORDED.name),
                tofile="confiture --exit-codes-json",
            )
        )
        raise AssertionError(
            "the exit-code contract changed. If deliberate, regenerate BOTH:\n"
            f"  uv run confiture --exit-codes-json > {RECORDED.relative_to(REPO_ROOT)}\n"
            f"  confiture --exit-codes-json > {VENDORED.split(':', 1)[1]}  (in fraisier-core)\n"
            f"and name the change in CHANGELOG.md.\n{diff}"
        )
