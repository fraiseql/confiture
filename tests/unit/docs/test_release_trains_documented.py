"""The release cadence is a document, and the document states the rules consumers rely on.

Two consumers pin confiture by range, and one of them upgrades by lifting a cap
on a green suite. They can only plan that if the rules for *when a version number
is spent* are written down: which releases carry which change, that a JSON
envelope only grows, and that a withdrawn release is withdrawn as a tag — never by
reverting ``main``, whose changes are not independently revertible.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DOC = REPO_ROOT / "docs" / "operations" / "release-trains.md"


def _text() -> str:
    assert DOC.is_file(), "docs/operations/release-trains.md is missing"
    return DOC.read_text(encoding="utf-8")


def test_the_three_trains_are_named() -> None:
    text = _text()
    for version in ("1.15.0", "1.16.0", "1.17.0"):
        assert version in text, f"the release-trains policy does not name {version}"


def test_a_train_ships_when_its_thesis_is_whole() -> None:
    assert "thesis" in _text().lower()


def test_the_additive_envelope_rule_is_stated() -> None:
    text = _text().lower()
    assert "additive" in text
    assert "additionalproperties" in text, (
        "the rule must say why additive is not free: schemas that forbid extra keys"
    )


def test_the_rollback_rule_is_stated() -> None:
    text = _text().lower()
    assert "yank" in text
    assert "never" in text and "revert" in text


def test_the_exit_code_universe_is_stated() -> None:
    assert "0..8" in _text()
