"""Every error path is ``fail()`` (ARC-02).

An error envelope built by hand — ``{"error": …}``, ``{"status": "error", …}`` —
has its own shape, stream and exit code. The one envelope is
``cli/error_json.emit_error_json``; every CLI error goes through ``fail()``.
And ``raise SystemExit`` bypasses Typer's exit handling entirely.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

CLI_ROOT = Path(__file__).resolve().parents[3] / "python" / "confiture" / "cli"
ENVELOPE_MODULE = CLI_ROOT / "error_json.py"
FILES = sorted(p for p in CLI_ROOT.rglob("*.py") if p != ENVELOPE_MODULE)


def _const_keys(node: ast.Dict) -> dict[str, ast.expr]:
    return {
        k.value: v
        for k, v in zip(node.keys, node.values, strict=False)
        if isinstance(k, ast.Constant) and isinstance(k.value, str)
    }


def _offences(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            keys = _const_keys(node)
            status = keys.get("status")
            # ``errors`` is a legitimate payload field (a count, a list of findings);
            # an ``error`` key or ``status: error`` is an envelope built by hand.
            if "error" in keys:
                found.append(f"{path.name}:{node.lineno} builds an error envelope by hand")
            elif isinstance(status, ast.Constant) and status.value == "error":
                found.append(f"{path.name}:{node.lineno} builds a status=error payload by hand")
        elif isinstance(node, ast.Raise) and node.exc is not None:
            target = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
            if isinstance(target, ast.Name) and target.id == "SystemExit":
                found.append(f"{path.name}:{node.lineno} raises SystemExit")
    return found


@pytest.mark.parametrize("path", FILES, ids=lambda p: str(p.relative_to(CLI_ROOT)))
def test_no_hand_built_error_envelope(path: Path) -> None:
    assert _offences(path) == []


def test_guard_covers_the_cli_package() -> None:
    assert any(p.name == "up.py" for p in FILES)
    assert ENVELOPE_MODULE.exists()
