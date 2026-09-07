"""Test doubles for the core orchestration objects carry a spec (TST-04).

``patch("confiture.core.migrator.Migrator", autospec=True)`` with no spec hands the code under
test a mock that answers *any* attribute with another mock. When the real
class loses a method or changes a signature, such tests keep passing — the
The engine refactor needs guards that fail, not guards that agree with
whatever is there. Every patch of ``Migrator``, ``MigratorSession`` or
``SchemaBuilder`` therefore passes ``autospec=True``, a ``spec``/``spec_set``,
or a double built by ``tests/unit/_doubles.py`` (which is itself autospecced).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

TESTS_ROOT = Path(__file__).resolve().parents[1]
_GUARDED = re.compile(r"\.(Migrator|MigratorSession|SchemaBuilder)$")
_DOUBLE_FACTORIES = {"migrator_double", "session_double", "builder_double", "create_autospec"}


def _target_of(call: ast.Call) -> str | None:
    """The dotted target of ``patch("...")`` / ``mock.patch("...")``, else None."""
    func = call.func
    name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
    if name != "patch" or not call.args:
        return None
    first = call.args[0]
    return first.value if isinstance(first, ast.Constant) and isinstance(first.value, str) else None


def _is_specced(call: ast.Call) -> bool:
    for kw in call.keywords:
        if kw.arg in ("autospec", "spec", "spec_set"):
            return True
        if kw.arg in ("new", "return_value", "side_effect") and isinstance(kw.value, ast.Call):
            fn = kw.value.func
            fn_name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", "")
            if fn_name in _DOUBLE_FACTORIES:
                return True
    return False


def find_spec_less_patches(root: Path) -> list[str]:
    findings: list[str] = []
    for path in sorted(root.rglob("test_*.py")):
        if path.name == Path(__file__).name:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            target = _target_of(node)
            if target and _GUARDED.search(target) and not _is_specced(node):
                rel = path.relative_to(root.parent).as_posix()
                findings.append(f"{rel}:{node.lineno}: patch({target!r})")
    return findings


def find_hand_built_stand_ins(root: Path) -> list[str]:
    """Helpers named like ``_make_migrator_mock`` that build a bare ``MagicMock()``.

    A local helper may exist as a thin wrapper over the doubles module; what it
    may not do is construct the stand-in from an unspecced mock itself.
    """
    findings: list[str] = []
    name_re = re.compile(r"_?(make_)?(migrator|session|builder)_(mock|double)")
    for path in sorted(list(root.rglob("test_*.py")) + list(root.rglob("conftest.py"))):
        if path.name == Path(__file__).name or "fixtures" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.FunctionDef) and name_re.search(node.name)):
                continue
            for sub in ast.walk(node):
                fn = getattr(sub, "func", None)
                fn_name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", None)
                if (
                    isinstance(sub, ast.Call)
                    and fn_name in ("MagicMock", "Mock")
                    and not any(kw.arg in ("spec", "spec_set") for kw in sub.keywords)
                ):
                    rel = path.relative_to(root.parent).as_posix()
                    findings.append(f"{rel}:{sub.lineno}: {node.name} builds a bare {fn_name}()")
    return findings


def test_every_core_object_patch_is_specced() -> None:
    findings = find_spec_less_patches(TESTS_ROOT)
    assert findings == [], (
        f"{len(findings)} spec-less patches of core objects:\n  "
        + "\n  ".join(findings)
        + "\nPass autospec=True, or return_value=migrator_double(...) from tests/unit/_doubles.py."
    )


def test_no_hand_built_stand_in_outside_the_doubles_module() -> None:
    assert find_hand_built_stand_ins(TESTS_ROOT) == []


def test_detector_shapes() -> None:
    def scan(src: str) -> int:
        tree = ast.parse(src)
        return sum(
            1
            for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and (t := _target_of(n))
            and _GUARDED.search(t)
            and not _is_specced(n)
        )

    assert scan('patch("confiture.core.migrator.Migrator")') == 1
    assert scan('patch("confiture.core.migrator.Migrator", return_value=MagicMock())') == 1
    assert scan('patch("confiture.core.migrator.Migrator", autospec=True)') == 0
    assert scan('patch("confiture.core.migrator.Migrator", return_value=migrator_double())') == 0
    assert scan('patch("confiture.core.builder.SchemaBuilder", spec=SchemaBuilder)') == 0
    assert scan('patch("confiture.core.connection.dsn_from_config")') == 0
