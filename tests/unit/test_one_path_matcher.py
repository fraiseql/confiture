"""One path matcher: ``core/path_globs.py`` is the only module that globs a path.

``PurePath.match``, ``PurePath.full_match`` and ``fnmatch`` each have their own
idea of what ``**`` means, where a pattern is anchored and whether a separator
can be crossed. Two of them in one codebase is two answers to "is this file in
the build", which is how the reference manual came to print exclusion examples
that excluded a different set of files from the one they name (#256).

Matching an *object* name — ``schema.relname``, a bare filename from a flat
listing — is a different job: there is no path, ``**`` has no meaning, and
``fnmatch`` is the right tool. Those modules are listed below with the reason,
and a listed module that no longer matches anything fails the test, as in the
one-lexer guard.
"""

from __future__ import annotations

import ast
from pathlib import Path

import confiture

PACKAGE = Path(confiture.__file__).resolve().parent
REPO = Path(__file__).resolve().parents[2]
MATCHER = PACKAGE / "core" / "path_globs.py"

# Modules that glob something that is not a path, with the reason. D6.
ALLOWED: dict[str, str] = {
    "core/seed/applier.py": (
        "`SeedProfile.include`/`.exclude` select from a flat `glob('*.sql')` listing where a "
        "path never appears; the patterns match a bare filename and `**` has no meaning there"
    ),
    "core/drift.py": (
        "`--check-acls` / `--check-ownership` scope by object name — `relname` and "
        "`schema.name` — never by file path"
    ),
    "core/linting/unresolved.py": (
        "`lint.ignore_objects` excuses an object `build_003` cannot find, matched against "
        "`schema.name`"
    ),
    "core/linting/libraries/acl.py": (
        "`acls`/`ignore` scope the `acl_001` grant lint by relation name"
    ),
    "core/linting/libraries/functions.py": (
        "`function_coverage.apply_to`/`.ignore` scope the uniqueness check by schema and "
        "qualified routine name"
    ),
    "core/linting/libraries/ownership.py": (
        "the `own_001` ownership expectation is scoped by relation name"
    ),
    "core/linting/libraries/security_definer.py": (
        "`security_lint.apply_to`/`ignore` scope `sec_002` by schema and routine name"
    ),
}


def _receiver_tail(node: ast.expr) -> str:
    """The identifier a call's receiver ends in, for telling a regex from a path."""
    if isinstance(node, ast.Attribute):
        return node.attr
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else ""


def _is_regex_constant(tail: str) -> bool:
    """A compiled-regex constant is spelled in upper case in this package."""
    return bool(tail) and tail.replace("_", "").isupper()


def _glob_call_sites(path: Path) -> list[str]:
    """Lines in *path* that match a pattern against something with a shape."""
    found: list[str] = []
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [alias.name for alias in node.names]
            if isinstance(node, ast.ImportFrom) and node.module:
                names.append(node.module)
            if any(name.split(".")[0] == "fnmatch" for name in names):
                found.append(f"{node.lineno}: fnmatch")
            continue
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in ("match", "full_match"):
            continue
        tail = _receiver_tail(node.func.value)
        if tail == "re" or _is_regex_constant(tail):
            continue
        found.append(f"{node.lineno}: {ast.unparse(node)[:70]}")
    return found


def _by_module() -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        if path == MATCHER:
            continue
        sites = _glob_call_sites(path)
        if sites:
            result[path.relative_to(PACKAGE).as_posix()] = sites
    return result


def test_no_module_outside_the_matcher_globs_a_path() -> None:
    offenders = [
        f"{module}:{site}"
        for module, sites in _by_module().items()
        if module not in ALLOWED
        for site in sites
    ]
    assert offenders == [], "second path matchers:\n  " + "\n  ".join(offenders)


def test_allow_list_is_current() -> None:
    present = set(_by_module())
    stale = sorted(module for module in ALLOWED if module not in present)
    assert stale == [], f"allow-list entries with nothing left to allow: {stale}"


def test_every_allow_list_entry_states_a_reason() -> None:
    vague = [module for module, reason in ALLOWED.items() if len(reason) < 40]
    assert vague == [], f"entries that explain nothing: {vague}"
