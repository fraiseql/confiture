"""One seed package (Phase 08, Cycle 2): applier, executor, bridge, paths, validation under ``core/seed/``.

Seed logic lived in five places — ``core/seed/``, ``core/seed_applier.py``,
``core/seed_bridge.py``, ``core/seed_executor.py`` and ``core/seed_validation/``.
Everything is under ``confiture.core.seed`` now. The old import paths stay as
thin shims for one release (removed at 1.0.0) so an embedder's import does not
break overnight, but nothing inside the package uses them.
"""

from __future__ import annotations

import ast
import importlib
import inspect
from pathlib import Path

import pytest

import confiture

_PACKAGE_ROOT = Path(confiture.__file__).resolve().parent
_OLD_TO_NEW = {
    "confiture.core.seed_applier": "confiture.core.seed.applier",
    "confiture.core.seed_executor": "confiture.core.seed.executor",
    "confiture.core.seed_bridge": "confiture.core.seed.bridge",
    "confiture.core.seed_validation": "confiture.core.seed.validation",
    "confiture.core.seed_validation.prep_seed.orchestrator": (
        "confiture.core.seed.validation.prep_seed.orchestrator"
    ),
}
_SHIM_FILES = {
    "core/seed_applier.py",
    "core/seed_executor.py",
    "core/seed_bridge.py",
}


def test_the_seed_package_holds_every_seed_module() -> None:
    from confiture.core.seed import applier, bridge, executor, paths, validation

    assert applier.SeedApplier and executor and bridge and paths and validation
    orchestrator = importlib.import_module("confiture.core.seed.validation.prep_seed.orchestrator")
    assert orchestrator.PrepSeedOrchestrator


@pytest.mark.parametrize(("old", "new"), sorted(_OLD_TO_NEW.items()))
def test_the_old_path_is_a_shim_over_the_new_module(old: str, new: str) -> None:
    shim = importlib.import_module(old)
    home = importlib.import_module(new)
    # A shim re-exports the module's public names: ``__all__`` when it declares one,
    # otherwise every non-underscore name that is not a submodule.
    public = list(getattr(home, "__all__", None) or []) or [
        n for n in dir(home) if not n.startswith("_") and not inspect.ismodule(getattr(home, n))
    ]
    assert public, new
    for name in public:
        assert getattr(shim, name) is getattr(home, name), f"{old}.{name} is not {new}.{name}"
    assert "shim" in (shim.__doc__ or "").lower() and "1.0.0" in (shim.__doc__ or ""), (
        f"{old} must say it is a shim removed at 1.0.0"
    )


def test_nothing_in_the_package_imports_the_old_paths() -> None:
    offenders: list[str] = []
    for path in sorted(_PACKAGE_ROOT.rglob("*.py")):
        rel = path.relative_to(_PACKAGE_ROOT).as_posix()
        if rel in _SHIM_FILES or rel.startswith("core/seed_validation/"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.ImportFrom) and node.module:
                modules.append(node.module)
            elif isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            for module in modules:
                if any(module == old or module.startswith(old + ".") for old in _OLD_TO_NEW):
                    offenders.append(f"{rel}:{node.lineno}: {module}")
    assert offenders == [], "old seed paths still imported inside the package:\n" + "\n".join(
        offenders
    )


def test_the_lazy_public_api_points_at_the_new_home() -> None:
    from confiture import _LAZY_IMPORTS

    assert _LAZY_IMPORTS["SeedApplier"][0] == "confiture.core.seed.applier"
