"""``cli/helpers.py`` is a helpers module, not a second command layer."""

from __future__ import annotations

from pathlib import Path

HELPERS = Path(__file__).resolve().parents[3] / "python" / "confiture" / "cli" / "helpers.py"


def test_helpers_is_at_most_600_lines() -> None:
    lines = len(HELPERS.read_text().splitlines())
    assert lines <= 600, f"cli/helpers.py is {lines} lines"
