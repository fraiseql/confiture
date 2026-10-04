"""No module defers its annotations: Python 3.14 evaluates them lazily already.

``from __future__ import annotations`` turned every annotation into its source
text so it could name what was not yet defined; PEP 649 makes that the
default, and the import now only changes what a reader gets back (a string
instead of the value).
"""

import ast
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _defers(path: Path) -> bool:
    try:
        tree = ast.parse(path.read_text())
    except SyntaxError:
        return False
    return any(
        isinstance(node, ast.ImportFrom)
        and node.module == "__future__"
        and any(alias.name == "annotations" for alias in node.names)
        for node in tree.body
    )


def test_no_module_defers_its_annotations() -> None:
    tracked = subprocess.run(
        ["git", "ls-files", "--", "*.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    deferring = [name for name in tracked if _defers(REPO_ROOT / name)]
    assert deferring == []
