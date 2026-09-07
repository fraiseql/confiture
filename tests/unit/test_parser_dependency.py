"""pglast is the one parser.

A standard install used to classify migrations with a regex backend while
reporting a version indistinguishable from an AST-capable one (#210), and the
deploy-time ``preflight`` that decides ``window_safe`` ran without pglast because
fraisier depends on ``fraiseql-confiture`` without ``[ast]``. pglast is now a
dependency: nothing guards its import, and a pglast whose enum surface confiture
cannot resolve is a configuration error naming the version, not a silent degrade.
"""

from __future__ import annotations

import ast
import tomllib
from importlib import metadata
from pathlib import Path

import pytest

import confiture
from confiture.core import _pglast_enums
from confiture.exceptions import ConfigurationError

REPO = Path(__file__).resolve().parents[2]
PACKAGE = Path(confiture.__file__).resolve().parent


def _project() -> dict:
    return tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]


def test_pglast_is_a_dependency() -> None:
    deps = _project()["dependencies"]
    assert any(d.startswith("pglast") for d in deps), deps


def test_the_ast_extra_is_an_empty_alias() -> None:
    """Kept for one release so ``fraiseql-confiture[ast]`` still resolves."""
    extras = _project()["optional-dependencies"]
    assert extras["ast"] == []


def _imports_pglast(node: ast.AST) -> bool:
    for n in ast.walk(node):
        if isinstance(n, ast.Import) and any(a.name.split(".")[0] == "pglast" for a in n.names):
            return True
        if isinstance(n, ast.ImportFrom) and (n.module or "").split(".")[0] == "pglast":
            return True
    return False


def find_guarded_pglast_imports(root: Path) -> list[str]:
    """``try: import pglast`` and ``find_spec("pglast")`` — the shapes that made pglast optional."""
    findings: list[str] = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Try) and any(_imports_pglast(stmt) for stmt in node.body):
                findings.append(f"{path.relative_to(root)}:{node.lineno} try-guarded pglast import")
            if (
                isinstance(node, ast.Call)
                and ast.unparse(node.func).endswith("find_spec")
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == "pglast"
            ):
                findings.append(f"{path.relative_to(root)}:{node.lineno} find_spec('pglast')")
    return findings


def test_no_module_guards_the_pglast_import() -> None:
    findings = find_guarded_pglast_imports(PACKAGE)
    assert findings == [], "pglast is required; import it plainly:\n  " + "\n  ".join(findings)


def test_enums_are_usable_on_this_install() -> None:
    assert _pglast_enums.enums_are_usable() is True


def test_missing_enum_members_are_a_configuration_error_naming_the_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_pglast_enums, "MISSING_MEMBERS", ["AlterTableType.AT_DropColumn"])
    with pytest.raises(ConfigurationError) as excinfo:
        _pglast_enums.enums_are_usable()
    message = str(excinfo.value)
    assert metadata.version("pglast") in message
    assert "AlterTableType.AT_DropColumn" in message
