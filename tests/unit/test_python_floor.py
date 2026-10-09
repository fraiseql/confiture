"""One interpreter, one parser major: nothing is written for a version below the floor.

confiture declares Python 3.14 and pglast 8. Code for an older interpreter — a
``sys.version_info`` branch, a CI job on 3.11, a wheel tag nobody can install —
is code no supported install runs, so it is never tested and only ever wrong.
The same holds for prose that explains behaviour by a pglast major confiture no
longer accepts.
"""

import ast
import re
import subprocess
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FLOOR = (3, 14)
PGLAST_FLOOR = "pglast>=8.5"

#: Where a CPython is named for a job, a venv or a wheel.
_NAMED_INTERPRETER = re.compile(
    r"(?:python-version:\s*['\"]?|--python\s+['\"]?|PY_VERSION\s*=\s*['\"]|python)"
    r"3\.(?P<minor>\d+)\b"
    r"|\bcp3(?P<tag>\d{2})\b"
)
_OLDER_PGLAST = re.compile(r"pglast(?:\s+|>=)[67](?:\.\d+)*\b")


def _tracked(*pathspecs: str) -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "--", *pathspecs],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [REPO_ROOT / line for line in out.splitlines() if line]


def _pyproject(path: Path) -> dict:
    return tomllib.loads(path.read_text())


def test_the_package_requires_the_floor() -> None:
    assert _pyproject(REPO_ROOT / "pyproject.toml")["project"]["requires-python"] == ">=3.14"


def test_the_plugin_requires_the_floor() -> None:
    plugin = REPO_ROOT / "plugins" / "fraiseql-confiture-pggit" / "pyproject.toml"
    assert _pyproject(plugin)["project"]["requires-python"] == ">=3.14"


def test_ruff_and_ty_read_the_floor() -> None:
    tool = _pyproject(REPO_ROOT / "pyproject.toml")["tool"]
    assert tool["ruff"]["target-version"] == "py314"
    assert tool["ty"]["environment"]["python-version"] == "3.14"


def test_pglast_is_one_major() -> None:
    dependencies = _pyproject(REPO_ROOT / "pyproject.toml")["project"]["dependencies"]
    assert [d for d in dependencies if d.startswith("pglast")] == [PGLAST_FLOOR]


def _version_comparisons(tree: ast.AST) -> list[tuple[int, tuple[int, ...]]]:
    """``sys.version_info`` compared with a literal tuple, as ``(line, version)``."""
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        operands = [node.left, *node.comparators]
        if not any("version_info" in ast.unparse(operand) for operand in operands):
            continue
        for operand in operands:
            if not isinstance(operand, ast.Tuple):
                continue
            values = [
                e.value
                for e in operand.elts
                if isinstance(e, ast.Constant) and isinstance(e.value, int)
            ]
            if values and len(values) == len(operand.elts):
                found.append((node.lineno, tuple(values)))
    return found


def _parsed(path: Path) -> ast.AST:
    """The module's tree; a fixture written to be unparseable branches on nothing."""
    try:
        return ast.parse(path.read_text())
    except SyntaxError:
        return ast.Module(body=[], type_ignores=[])


def test_no_code_branches_on_an_interpreter_below_the_floor() -> None:
    offenders = [
        f"{path.relative_to(REPO_ROOT)}:{line}: {version}"
        for path in _tracked("python/*.py", "tests/*.py", "scripts/*.py", "plugins/*.py")
        for line, version in _version_comparisons(_parsed(path))
        if version[:2] <= FLOOR
    ]
    assert offenders == [], (
        "every supported interpreter takes the same side of these comparisons, so the "
        f"other side is code nothing runs: {offenders}"
    )


def test_no_workflow_names_an_interpreter_below_the_floor() -> None:
    offenders = []
    for path in _tracked(".github/*", "ci/*", ".python-version"):
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            for match in _NAMED_INTERPRETER.finditer(line):
                minor = int(match["minor"] or match["tag"])
                if minor < FLOOR[1]:
                    offenders.append(f"{path.relative_to(REPO_ROOT)}:{number}: {match[0]}")
    assert offenders == [], f"a job, venv or wheel for an unsupported CPython: {offenders}"


def test_no_module_explains_itself_by_an_older_pglast() -> None:
    offenders = [
        f"{path.relative_to(REPO_ROOT)}:{number}: {match[0]}"
        for path in _tracked("python/*.py")
        for number, line in enumerate(path.read_text().splitlines(), start=1)
        for match in _OLDER_PGLAST.finditer(line)
    ]
    assert offenders == [], f"confiture supports pglast 8 alone: {offenders}"
