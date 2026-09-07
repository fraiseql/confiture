"""The CLI has no apply loop of its own.

``MigratorSession`` is the one engine: it takes the lock, plans, verifies
checksums and applies. A CLI module that imports the lock or the migration
loaders, or calls the engine's ``apply``/``rollback`` directly, is a second
loop — the one that ran ``--dry-run-execute`` without a SAVEPOINT.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

CLI_ROOT = Path(__file__).resolve().parents[2] / "python" / "confiture" / "cli"

FORBIDDEN_NAMES = {
    "MigrationLock",
    "load_migration_class",
    "load_migration_module",
    "get_migration_class",
    "migrate_up_internal",
    "_migrate_up_internal",
}
ENGINE_CALLS = {"apply", "rollback"}

CLI_FILES = sorted(CLI_ROOT.rglob("*.py"))


def _receiver_names(node: ast.expr) -> set[str]:
    """Every identifier along an attribute chain, lowercased."""
    names: set[str] = set()
    while isinstance(node, ast.Attribute):
        names.add(node.attr.lower())
        node = node.value
    if isinstance(node, ast.Name):
        names.add(node.id.lower())
    return names


def _offences(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            found.append(f"{path.name}:{node.lineno} references {node.id}")
        elif isinstance(node, ast.ImportFrom | ast.Import):
            found.extend(
                f"{path.name}:{node.lineno} imports {alias.name}"
                for alias in node.names
                if alias.name.rsplit(".", 1)[-1] in FORBIDDEN_NAMES
            )
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in ENGINE_CALLS
            and any("migrator" in n for n in _receiver_names(node.func.value))
        ):
            found.append(f"{path.name}:{node.lineno} calls migrator.{node.func.attr}()")
    return found


@pytest.mark.parametrize("path", CLI_FILES, ids=lambda p: str(p.relative_to(CLI_ROOT)))
def test_cli_module_has_no_apply_loop(path: Path) -> None:
    assert _offences(path) == []


def test_guard_sees_the_cli_package() -> None:
    assert any(p.name == "up.py" for p in CLI_FILES)
