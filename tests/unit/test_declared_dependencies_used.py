"""Every runtime dependency declared in pyproject.toml is imported by the package.

A declared-but-unused dependency is installed on every user's machine, audited in
every security review and pinned in every lockfile for nothing. The check is
syntactic (AST ``import`` / ``from … import`` under ``python/confiture``), so a
dependency used only through ``importlib`` needs an entry in ``IMPORTED_DYNAMICALLY``
with the reason.
"""

from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE = REPO_ROOT / "python" / "confiture"

# Distribution name → top-level import name, where they differ.
IMPORT_NAMES: dict[str, str] = {
    "pyyaml": "yaml",
}
# Distribution → reason it is legitimately not imported by name.
IMPORTED_DYNAMICALLY: dict[str, str] = {}


def _declared_dependencies() -> list[str]:
    with (REPO_ROOT / "pyproject.toml").open("rb") as fh:
        pyproject = tomllib.load(fh)
    names = []
    for spec in pyproject["project"]["dependencies"]:
        match = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)", spec)
        assert match, f"unparseable dependency spec {spec!r}"
        names.append(match.group(1).lower())
    return names


def _imported_top_level_names() -> set[str]:
    names: set[str] = set()
    for path in PACKAGE.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                names.add(node.module.split(".")[0])
    return names


def test_every_declared_runtime_dependency_is_imported() -> None:
    imported = _imported_top_level_names()
    unused = [
        dist
        for dist in _declared_dependencies()
        if dist not in IMPORTED_DYNAMICALLY
        and IMPORT_NAMES.get(dist, dist.replace("-", "_")) not in imported
    ]
    assert unused == [], (
        f"declared in [project.dependencies] but never imported under python/confiture: {unused}"
    )


def test_dynamic_import_allowlist_names_declared_dependencies_only() -> None:
    declared = set(_declared_dependencies())
    stale = sorted(set(IMPORTED_DYNAMICALLY) - declared)
    assert stale == [], f"IMPORTED_DYNAMICALLY names dependencies no longer declared: {stale}"
