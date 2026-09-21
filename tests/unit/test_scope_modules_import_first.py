"""Each module of the migrator, the models, the config and the exceptions imports first.

A function-local import that defers a cycle keeps the process from failing only for
the import orders someone tried: the cycle is still there, and the module that is
imported *first* in a fresh interpreter is the one that finds a partially
initialised name. ``test_import_graph_has_no_scc.py`` says the cycles are gone; this
says so where it would hurt — every module in that scope, imported alone, by a new
interpreter.
"""

from __future__ import annotations

import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import confiture

PACKAGE = Path(confiture.__file__).resolve().parent
SCOPE = ("core/_migrator", "models", "config")
SINGLE = ("exceptions.py", "error_codes.py", "core/migrator.py")


def _modules() -> list[str]:
    paths = [p for scope in SCOPE for p in (PACKAGE / scope).rglob("*.py")]
    paths += [PACKAGE / single for single in SINGLE]
    names = []
    for path in sorted(paths):
        parts = path.relative_to(PACKAGE.parent).with_suffix("").parts
        names.append(".".join(parts[:-1] if parts[-1] == "__init__" else parts))
    return names


def _imports_first(module: str) -> tuple[str, str]:
    result = subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        capture_output=True,
        text=True,
        check=False,
        env={"PYTHONPATH": str(PACKAGE.parent)},
    )
    return module, result.stderr.strip().splitlines()[-1] if result.returncode else ""


def test_every_module_in_scope_imports_first_in_a_fresh_interpreter() -> None:
    with ThreadPoolExecutor() as pool:
        failures = {
            module: error for module, error in pool.map(_imports_first, _modules()) if error
        }
    assert failures == {}, failures
