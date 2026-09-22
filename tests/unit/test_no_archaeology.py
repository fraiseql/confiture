"""No development archaeology in what ships: campaign references, TODO/FIXME/HACK.

A repository should read as if written in one session. Under ``python/`` and ``tests/``
nothing may name the plan that produced it: a numbered phase (hyphenated or not), a
numbered cycle, an owner's decision by number, a review finding id (``ARC-02``,
``LINT-07``, ``SEC-M1``), a plan step (``(P4)``), a path under the gitignored plan
directory, or "this campaign". Nor may it carry a ``TODO`` / ``FIXME`` / ``HACK``
marker — a real follow-up lives in the issue tracker or in a shrink-only budget.

The *word* phase is domain vocabulary and stays: ``HookPhase``, ``restore``'s three
phases, expand/contract, the superuser build phases. ``docs/`` also uses "Phase 1"
for its own concepts (blue-green phases, the TDD cycle, a lint adoption path), so
there only the two-digit campaign phases, the other shapes above and review ids are
forbidden; release notes are history and exempt.

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
_PHASE = "Phase" + r"[ -][0-9]"
_BRACKET_PHASE = r"\[" + "Phase" + r" [0-9]"
_CYCLE = r"\b" + "Cycle" + r" [0-9]"
_DECISION = r"\b[Oo]wner " + "decision"
_PLAN_DIR = r"\." + "phases/"
_CAMPAIGN = r"\b[Tt](?:his|he) " + "campaign" + r"\b"
_PLAN_STEP = r"\(" + "P" + r"[0-9][,)]"
_MARKERS = r"\b(?:" + "|".join(("TO" + "DO", "FIX" + "ME", "HA" + "CK")) + r")\b"
_REVIEW_IDS = (
    r"\b(?:ENG|ARC|ARCH|LED|SEC|DOCS|LINT|ANA|TST|OD)-[A-Z]?[0-9]{1,2}\b|\b" + "QW" + r"[0-9]\b"
)
_CAMPAIGN_SHAPES = (
    _BRACKET_PHASE,
    _CYCLE,
    _DECISION,
    _PLAN_DIR,
    _CAMPAIGN,
    _PLAN_STEP,
    _REVIEW_IDS,
)
CODE_PATTERN = re.compile("|".join((rf"\b{_PHASE}", *_CAMPAIGN_SHAPES, _MARKERS)))
DOCS_PATTERN = re.compile(
    "|".join(
        (
            r"\b" + "Phase" + r"[ -][0-9]{2}\b",
            r"\b" + "Phase" + r" [0-9] M[0-9]",
            *_CAMPAIGN_SHAPES,
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


#: One sample per campaign shape; each must be caught, or its family is off.
#: Assembled from pieces for the same reason as the patterns.
CAUGHT = (
    "Phase" + " 03",
    "the " + "Phase" + "-05 warn posture",
    "[" + "Phase" + " 11, Cycle 2]",
    "# " + "Cycle" + " 3: scoping",
    "(owner " + "decision" + " 13)",
    "see ." + "phases/.../test-conventions.md",
    "the " + "campaign's central test",
    "(" + "P4" + ", Cycle 4)",
    "(" + "LINT" + "-07)",
    "(" + "SEC" + "-M1)",
    "QW" + "4 did-you-mean",
)

#: The domain word, which stays.
NOT_CAUGHT = (
    "HookPhase.BEFORE_EXECUTE",
    "restore runs in three phases: pre-data, data, post-data",
    "the expand phase adds the column; the contract phase drops it",
    "an import cycle through the migrator",
    "an OpsGenie priority of P2",
    "CONFIG_011 names the installed pglast",
)


def test_every_campaign_shape_is_caught_and_the_domain_word_is_not() -> None:
    missed = [s for s in CAUGHT if not CODE_PATTERN.search(s)]
    wrong = [s for s in NOT_CAUGHT if CODE_PATTERN.search(s) or DOCS_PATTERN.search(s)]
    assert (missed, wrong) == ([], [])
