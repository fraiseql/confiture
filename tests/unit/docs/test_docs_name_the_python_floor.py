"""No document tells a reader confiture runs on a CPython below its floor.

1.30.0 supports Python 3.14 alone. A guide, an example or a CI snippet that
says "Python 3.11+" or sets up 3.12 sends the reader to an interpreter pip will
not install confiture on. History keeps its versions: the CHANGELOG and the
release notes say what a past release supported.
"""

import re
import tomllib

from command_truth import REPO_ROOT, tracked

FLOOR_MINOR = 14

#: A claim that an interpreter is supported or used, with the minor in group 1.
CLAIMS = (
    re.compile(r"(?<![\w])Python \*{0,2}3\.(\d+)\*{0,2}(?:\+| or (?:higher|newer|later))"),
    re.compile(r"(?<![\w])Python \*{0,2}3\.(\d+),"),
    re.compile(r"python-version:\s*['\"]?3\.(\d+)"),
    re.compile(r"(?:image:\s*|FROM\s+)python:3\.(\d+)"),
    re.compile(r"--python\s+3\.(\d+)"),
)

#: Documents that record what was true, and why they may name an older CPython.
HISTORY = {
    "CHANGELOG.md": "history: what each past release supported",
    "docs/release-notes/": "history: what each past release supported",
}


def test_the_floor_is_the_declared_one() -> None:
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())["project"]
    assert project["requires-python"] == f">=3.{FLOOR_MINOR}"


def test_no_document_names_an_interpreter_below_the_floor() -> None:
    offenders = []
    for path in tracked("*.md", "*.yaml", "*.yml", "*.toml", "*.txt"):
        relative = path.relative_to(REPO_ROOT).as_posix()
        if relative.startswith(".github/") or any(relative.startswith(h) for h in HISTORY):
            continue
        offenders.extend(
            f"{relative}:{number}: {match.group(0)}"
            for number, line in enumerate(path.read_text(errors="replace").splitlines(), start=1)
            for claim in CLAIMS
            for match in claim.finditer(line)
            if int(match.group(1)) < FLOOR_MINOR
        )
    assert offenders == [], f"a document names a CPython confiture does not support: {offenders}"
