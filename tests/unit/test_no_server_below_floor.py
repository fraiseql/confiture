"""No code for a PostgreSQL server confiture does not support.

PostgreSQL 16 is the oldest server confiture supports
(``core/connection.MINIMUM_SERVER_MAJOR``). A branch taken only by an older server
is code no supported deployment runs and no test on CI exercises: it reads as a
behaviour confiture has, and it has not. This test fails on

* a comparison of a server version — a name holding ``server_version``,
  ``server_major``, ``version_num`` or ``pg_major``, or any comparison inside a
  function so named — with a PostgreSQL release below the floor, written as a
  major (``11``) or as a ``server_version_num`` (``130000``), directly or through
  a module constant;
* a ``*_SINCE`` constant naming a release at or below the floor: every supported
  server is past it, so a comparison with it has one answer.

A release kept as a *fact* a payload reports (``LockProfile.since_version``) is
neither: it is never compared.
"""

import ast
import re
from pathlib import Path

from confiture.core.connection import MINIMUM_SERVER_MAJOR

REPO = Path(__file__).resolve().parents[2]
PACKAGE = REPO / "python" / "confiture"
VERSION_NAME = re.compile(r"server_version|server_major|version_num|pg_major")

#: ``module:line`` → why that comparison is not a branch for an unsupported server.
ALLOWED: dict[str, str] = {}


def _major(value: object) -> int | None:
    """The PostgreSQL major ``value`` names, or ``None`` when it names no release."""
    if not isinstance(value, int) or isinstance(value, bool):
        return None
    if 7 <= value < 100:
        return value
    if value >= 70000:
        return value // 10000
    return None


def _module_constants(tree: ast.Module) -> dict[str, object]:
    constants: dict[str, object] = {}
    for node in tree.body:
        target, value = None, None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign):
            target, value = node.target, node.value
        if isinstance(target, ast.Name) and isinstance(value, ast.Constant):
            constants[target.id] = value.value
    return constants


def _trees() -> dict[str, ast.Module]:
    return {
        path.relative_to(REPO).as_posix(): ast.parse(path.read_text(encoding="utf-8"))
        for path in sorted(PACKAGE.rglob("*.py"))
    }


def _package_constants(trees: dict[str, ast.Module]) -> dict[str, object]:
    """Every module-level constant, by name; a name two modules bind differently is dropped."""
    seen: dict[str, set[object]] = {}
    for tree in trees.values():
        for name, value in _module_constants(tree).items():
            seen.setdefault(name, set()).add(value)
    return {name: next(iter(values)) for name, values in seen.items() if len(values) == 1}


def _names(node: ast.expr) -> list[str]:
    return [
        n.id if isinstance(n, ast.Name) else n.attr
        for n in ast.walk(node)
        if isinstance(n, (ast.Name, ast.Attribute))
    ]


def _value(node: ast.expr, constants: dict[str, object]) -> object:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return constants.get(node.id)
    if isinstance(node, ast.Attribute):
        return constants.get(node.attr)
    return None


class _Scan(ast.NodeVisitor):
    def __init__(self, constants: dict[str, object]) -> None:
        self.constants = constants
        self.functions: list[str] = []
        self.lines: list[int] = []

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.functions.append(node.name)
        self.generic_visit(node)
        self.functions.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Compare(self, node: ast.Compare) -> None:
        operands = [node.left, *node.comparators]
        in_version_function = any(VERSION_NAME.search(name) for name in self.functions)
        for operand in operands:
            major = _major(_value(operand, self.constants))
            if major is None or major >= MINIMUM_SERVER_MAJOR:
                continue
            others = [o for o in operands if o is not operand]
            if in_version_function or any(
                VERSION_NAME.search(name) for other in others for name in _names(other)
            ):
                self.lines.append(node.lineno)
                break
        self.generic_visit(node)


def _since_constants(tree: ast.Module) -> list[int]:
    return sorted(
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
        if isinstance(target, ast.Name)
        and target.id.endswith("_SINCE")
        and isinstance(node.value, ast.Constant)
        and (major := _major(node.value.value)) is not None
        and major <= MINIMUM_SERVER_MAJOR
    )


def _findings() -> set[str]:
    trees = _trees()
    constants = _package_constants(trees)
    found: set[str] = set()
    for module, tree in trees.items():
        scan = _Scan({**constants, **_module_constants(tree)})
        scan.visit(tree)
        found.update(f"{module}:{line}" for line in scan.lines)
        found.update(f"{module}:{line}" for line in _since_constants(tree))
    return found


def test_the_floor_is_postgresql_16() -> None:
    assert MINIMUM_SERVER_MAJOR == 16


def test_no_branch_is_taken_only_by_a_server_below_the_floor() -> None:
    found = _findings() - ALLOWED.keys()
    assert not found, (
        f"a server below PostgreSQL {MINIMUM_SERVER_MAJOR} never connects; delete the "
        f"branch (a known server vs None is what remains): {sorted(found)}"
    )


def test_every_allowed_entry_still_matches() -> None:
    assert ALLOWED.keys() <= _findings(), "delete the allow-list entries that match nothing"


def test_the_scan_sees_each_shape() -> None:
    """The scan itself: each shape it must refuse, and the ones it must not."""
    source = (
        "OLD_SINCE = 11\n"
        "NEW_SINCE = 18\n"
        "NUM_SINCE = 150000\n"
        "def f(conn, server_version):\n"
        "    if server_version >= OLD_SINCE: pass\n"
        "    if conn.info.server_version >= 130000: pass\n"
        "    if server_version >= 18: pass\n"
        "    if server_version is None or server_version >= 16: pass\n"
        "    if count >= 12: pass\n"
        "def _server_version(number):\n"
        "    return number // 10000 if number >= 100000 else 0\n"
        "def g(number):\n"
        "    return number <= 0\n"
    )
    tree = ast.parse(source)
    scan = _Scan(_module_constants(tree))
    scan.visit(tree)
    assert scan.lines == [5, 6, 11]
    assert _since_constants(tree) == [1, 3]
