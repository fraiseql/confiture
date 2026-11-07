"""The psycopg confiture declares can execute the SQL confiture hands it.

confiture executes PEP 750 template strings (``cursor.execute(t"…")``), which
psycopg accepts from 3.3.0. A floor below that resolves to a psycopg that raises
``TypeError`` on the first such call, and the lockfile hid it: CI installs the
pinned 3.3.x, never the floor (#814).
"""

import re
import tomllib
from pathlib import Path

from packaging.requirements import Requirement
from packaging.version import Version

import confiture

REPO = Path(__file__).resolve().parents[2]
PACKAGE = Path(confiture.__file__).resolve().parent

#: The first psycopg whose ``execute`` takes a ``string.templatelib.Template``.
TEMPLATE_STRINGS_SINCE = Version("3.3.0")

_EXECUTES_TEMPLATE = re.compile(r"\bexecute(?:many)?\(\s*t\"")


def _psycopg_requirement() -> Requirement:
    project = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    found = [Requirement(d) for d in project["dependencies"] if Requirement(d).name == "psycopg"]
    assert len(found) == 1, project["dependencies"]
    return found[0]


def _declared_floor(requirement: Requirement) -> Version | None:
    floors = [Version(s.version) for s in requirement.specifier if s.operator in {">=", "==", "~="}]
    return max(floors, default=None)


def _modules_executing_templates() -> list[str]:
    return sorted(
        str(path.relative_to(PACKAGE))
        for path in PACKAGE.rglob("*.py")
        if _EXECUTES_TEMPLATE.search(path.read_text(encoding="utf-8"))
    )


def test_confiture_executes_template_strings() -> None:
    """The premise: without it the floor below would be a guess."""
    assert _modules_executing_templates()


def test_declared_psycopg_floor_executes_template_strings() -> None:
    floor = _declared_floor(_psycopg_requirement())
    users = _modules_executing_templates()
    assert floor is not None and floor >= TEMPLATE_STRINGS_SINCE, (
        f"pyproject.toml declares psycopg floor {floor}, but {len(users)} modules execute "
        f"template strings, which psycopg accepts from {TEMPLATE_STRINGS_SINCE} "
        f"(first: {users[0]})"
    )
