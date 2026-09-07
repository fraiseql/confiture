"""The CLI does not reach into core objects' private attributes.

``migrator._version_from_filename(...)`` from a command is a dependency on an
implementation detail. What the CLI needs is public or moved to where the CLI is.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

CLI_ROOT = Path(__file__).resolve().parents[3] / "python" / "confiture" / "cli"
FILES = sorted(CLI_ROOT.rglob("*.py"))


def _reach_ins(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    found: list[str] = []
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Attribute)
            and node.attr.startswith("_")
            and not node.attr.startswith("__")
        ):
            continue
        base = node.value
        # `self._x` / `cls._x` are the module's own business; `_m.name` is a module alias.
        if isinstance(base, ast.Name) and base.id in {"self", "cls"}:
            continue
        found.append(f"{path.name}:{node.lineno} reaches into `{ast.unparse(base)}.{node.attr}`")
    return found


@pytest.mark.parametrize("path", FILES, ids=lambda p: str(p.relative_to(CLI_ROOT)))
def test_no_private_attribute_reach_in(path: Path) -> None:
    assert _reach_ins(path) == []
