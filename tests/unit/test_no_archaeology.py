"""No development archaeology in what ships: phase references, TODO/FIXME/HACK, review ids.

A repository should read as if written in one session. Under ``python/`` and ``tests/``
nothing may mention a development phase (``Phase 03``, ``[Phase 11, Cycle 2]``), a
review finding id (``ARC-02``, ``ENG-11``), or carry a ``TODO`` / ``FIXME`` / ``HACK``
marker — a real follow-up lives in the issue tracker or in a shrink-only budget.
``docs/`` may use "Phase 1" for its own concepts (blue-green phases, the TDD cycle),
so there only two-digit remediation phases and review ids are forbidden; release
notes are history and exempt.

One line is exempt, by exact path and name: ``DEFAULT_STATUS_WORDS`` is the
vocabulary ``tree_008`` *reports* in a filename, which the rule cannot look for
without writing down. It is declared once and read from there everywhere else,
so the exemption is one line rather than a family of files.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
THIS_FILE = Path(__file__).relative_to(REPO_ROOT).as_posix()

# Built from pieces so this file does not match its own pattern.
_PHASE = "Phase" + r" [0-9]"
_BRACKET_PHASE = r"\[" + "Phase" + r" [0-9]"
_MARKERS = r"\b(?:" + "|".join(("TO" + "DO", "FIX" + "ME", "HA" + "CK")) + r")\b"
_REVIEW_IDS = r"\b(?:ENG|ARC|LED|SEC|DOCS)-[0-9]{2}\b"
CODE_PATTERN = re.compile("|".join((rf"\b{_PHASE}", _BRACKET_PHASE, _MARKERS, _REVIEW_IDS)))
DOCS_PATTERN = re.compile(
    "|".join(
        (
            r"\(" + "Phase" + r" [0-9]{2}",
            "Phase" + r" [0-9]{2},? Cycle",
            _BRACKET_PHASE,
            _REVIEW_IDS,
        )
    )
)


def _tracked(*pathspecs: str) -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "-z", "--", *pathspecs], cwd=REPO_ROOT, capture_output=True, check=True
    ).stdout.decode()
    return [REPO_ROOT / p for p in out.split("\0") if p]


#: (path, name) of the one declaration whose markers are data, not archaeology.
VOCABULARY_DECLARATION = ("python/confiture/config/environment.py", "DEFAULT_STATUS_WORDS")


def _hits(files: list[Path], pattern: re.Pattern[str]) -> list[str]:
    found: list[str] = []
    for path in files:
        rel = path.relative_to(REPO_ROOT).as_posix()
        if rel == THIS_FILE or path.suffix not in {".py", ".md", ".sql", ".yaml", ".yml", ".toml"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        exempt_path, exempt_name = VOCABULARY_DECLARATION
        for lineno, line in enumerate(text.splitlines(), 1):
            if rel == exempt_path and line.startswith(exempt_name):
                continue
            if pattern.search(line):
                found.append(f"{rel}:{lineno}: {line.strip()[:100]}")
    return found


def test_code_and_tests_carry_no_archaeology() -> None:
    hits = _hits(_tracked("python", "tests"), CODE_PATTERN)
    assert hits == [], "development archaeology in code or tests:\n" + "\n".join(hits)


def test_docs_do_not_reference_the_remediation_phases() -> None:
    files = [p for p in _tracked("docs") if "docs/release-notes/" not in p.as_posix()]
    hits = _hits(files, DOCS_PATTERN)
    assert hits == [], "remediation-phase references in docs:\n" + "\n".join(hits)
