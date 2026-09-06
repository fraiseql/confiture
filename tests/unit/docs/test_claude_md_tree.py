"""CLAUDE.md's project tree is generated, and its prose carries no line counts.

``scripts/gen_tree.py`` renders the tree from the repository; the block between the
``<!-- BEGIN GENERATED: tree -->`` / ``<!-- END GENERATED: tree -->`` markers in
CLAUDE.md must equal that rendering byte for byte. Line counts in prose go stale the
day after they are written, so none are allowed anywhere in the file.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"
BEGIN = "<!-- BEGIN GENERATED: tree -->"
END = "<!-- END GENERATED: tree -->"


@pytest.fixture(scope="module")
def gen_tree():
    script = REPO_ROOT / "scripts" / "gen_tree.py"
    assert script.exists(), "scripts/gen_tree.py does not exist"
    spec = importlib.util.spec_from_file_location("gen_tree", script)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _generated_block(text: str) -> str:
    assert BEGIN in text and END in text, "CLAUDE.md has no generated tree markers"
    start = text.index(BEGIN) + len(BEGIN)
    return text[start : text.index(END)].strip("\n")


def test_claude_md_tree_matches_the_generator(gen_tree) -> None:
    current = _generated_block(CLAUDE_MD.read_text(encoding="utf-8"))
    assert current == gen_tree.render_tree(REPO_ROOT).strip("\n"), (
        "CLAUDE.md tree is stale; run scripts/gen_tree.py --write"
    )


def test_claude_md_tree_lists_only_existing_paths(gen_tree) -> None:
    for path in gen_tree.listed_paths(REPO_ROOT):
        assert (REPO_ROOT / path).exists(), f"tree lists {path}, which does not exist"


def test_claude_md_prose_has_no_line_counts() -> None:
    offenders = [
        f"{n}: {line.strip()[:100]}"
        for n, line in enumerate(CLAUDE_MD.read_text(encoding="utf-8").splitlines(), 1)
        if re.search(r"(≤|<=|\b)\d{2,}\s*(body )?lines\b", line)
    ]
    assert not offenders, "line counts in CLAUDE.md:\n" + "\n".join(offenders)
