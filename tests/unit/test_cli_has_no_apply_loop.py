"""The CLI has no apply loop of its own, and no driver.

``MigratorSession`` is the one engine: it takes the lock, plans, verifies
checksums and applies. A CLI module that imports the lock or the migration
loaders, or calls the engine's ``apply``/``rollback`` directly, is a second
loop — the one that ran ``--dry-run-execute`` without a SAVEPOINT.

The same holds one layer down: a command that imports ``psycopg`` or ``pglast``
is doing ``core``'s work. Twelve ``cli/`` modules imported the driver — to open
a connection from a DSN, to catch its error class, and three to run SQL of their
own (a ledger read, a ledger probe, the dry-run row estimates). ``core.connection``
has ``connect_url`` and ``DatabaseError`` for the first two; the SQL moved to
``core``.
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


#: Drivers and parsers ``cli/`` reaches only through ``core``: a module under ``cli/``
#: that imports one is doing core's work in a command.
DRIVERS = {"psycopg", "pglast"}

#: Modules that keep their own driver import, and why.
DRIVER_EXEMPT: dict[str, str] = {}


def _driver_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module]
        else:
            continue
        found.extend(
            f"{path.relative_to(CLI_ROOT).as_posix()}:{node.lineno} imports {name}"
            for name in names
            if name.split(".")[0] in DRIVERS
        )
    return found


def test_cli_imports_no_driver_and_no_parser() -> None:
    """``psycopg`` and ``pglast`` are ``core``'s: at module level, in a function, or for types."""
    found = [
        hit
        for path in CLI_FILES
        if path.relative_to(CLI_ROOT).as_posix() not in DRIVER_EXEMPT
        for hit in _driver_imports(path)
    ]
    assert found == [], "\n".join(found)


def test_every_driver_exemption_still_imports_one() -> None:
    for module in DRIVER_EXEMPT:
        assert _driver_imports(CLI_ROOT / module), f"{module} is exempt but imports none"
