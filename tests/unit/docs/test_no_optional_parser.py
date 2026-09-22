"""pglast is a dependency, so nothing may tell a reader to install it.

`sqlparse` and a regex backend were real once. 0.50.0 (D13) made pglast the one
parser and a **hard dependency**; `[ast]` survives only as an empty alias so an
older `fraiseql-confiture[ast]` still resolves. `tests/unit/test_single_parser.py`
already forbids the *code* from asking whether pglast is available: no
availability flag, no probe function, no environment variable that forces a
regex backend. (Naming those three identifiers here would fail that very
guard: corrective prose that names what it forbids trips the check it
corrects.)

Nothing was asking the same of the prose, and it had drifted for two releases:
four guides told the reader to `pip install "fraiseql-confiture[ast]"` to enable
a rule; `acl-coverage.md` described a sqlparse fallback and "both code paths …
exercised by parameterized unit tests"; five CLI `--help` strings said "Requires
the [ast] extra (pglast)", which `docs/reference/cli.md` is generated from, so
the untruth was published twice; and two module docstrings described a skip
notice for an absent parser that cannot be emitted.

The guard is conditional on the fact, not on the wording: it reads
`pyproject.toml` and only applies while pglast is a **dependency**. Were pglast
to become optional again, these sentences would become true and this test would
stop asking for them.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest
from command_truth import REPO_ROOT, tracked

#: Sentences that present the parser as something the reader supplies. Each is a
#: *claim about installation or availability* — not a mention of the name, which
#: history and incident records legitimately make.
FALSE_WHILE_PGLAST_IS_A_DEPENDENCY = (
    re.compile(r"requires?\s+(?:the\s+)?[`']?\[ast\]", re.I),
    re.compile(r"\[ast\][^.\n]{0,24}\brequired\b", re.I),
    re.compile(r"install[^.\n]{0,40}\[ast\]", re.I),
    re.compile(r"\bwhen pglast is (?:not installed|absent)", re.I),
    re.compile(r"\bwithout pglast\b", re.I),
    re.compile(r"\bpglast[^.\n]{0,20}\bwhen available\b", re.I),
    re.compile(r"falls? back to sqlparse", re.I),
)

#: Documents that record what was true at a version rather than instruct.
#: `release-notes/` and `CHANGELOG.md` are out for the reason they are out of the
#: command guard; the two below name the old behaviour to say it is gone.
RECORDS = {
    "docs/reference/fraisier-adapter-contract.md": (
        "an incident report: it names who was affected in 2026-07, when the extra "
        "and the regex fallback both still existed"
    ),
    "tests/unit/test_parser_dependency.py": (
        "the test that pins pglast as a dependency; its docstring says what a "
        "standard install *used to* do, which is the reason the pin exists"
    ),
    "tests/unit/docs/test_no_optional_parser.py": (
        "this module — its patterns are the sentences it forbids"
    ),
}

#: Directories that evaluate alternatives rather than describe confiture. The
#: research notes weigh sqlparse against pglast and show code for each; that is
#: the decision D13 records, not a claim about what confiture does.
RECORD_DIRS = ("docs/research/",)


def pglast_is_a_dependency() -> bool:
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())["project"]
    return any(d.startswith("pglast") for d in project["dependencies"])


def test_pglast_really_is_a_dependency():
    """The premise. If this fails, the rest of the module is asking the wrong thing."""
    assert pglast_is_a_dependency()


def test_the_ast_extra_is_still_an_empty_alias():
    """What makes `pip install "…[ast]"` harmless rather than an error."""
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())["project"]
    assert project["optional-dependencies"]["ast"] == []


def corpus() -> list[Path]:
    files = [
        p
        for p in tracked("docs/**/*.md")
        if "release-notes" not in p.relative_to(REPO_ROOT).as_posix()
    ]
    files += tracked("README.md", "PRD.md", "ARCHITECTURE.md", "CLAUDE.md")
    files += tracked("python/confiture/**/*.py")
    # Tests too: a module docstring is the documentation a maintainer reads
    # first, and three of them still promised a skip notice for an absent
    # parser — one pointing at a test module deleted with the path it covered.
    files += tracked("tests/**/*.py")
    return sorted(set(files))


def findings() -> list[tuple[str, str, str]]:
    """``(file, pattern, line)`` for every sentence that sells pglast as optional."""
    out = []
    for path in corpus():
        rel = path.relative_to(REPO_ROOT).as_posix()
        if rel in RECORDS or rel.startswith(RECORD_DIRS):
            continue
        # The whole document, not just its code regions. The claim this guard
        # exists for — "uses pglast when available and falls back to sqlparse
        # + regex" — was a *prose sentence*, and a code-regions scan copied
        # from the import guard could not see it. An import lives in code; a
        # promise about installation lives in a paragraph.
        for line in path.read_text().splitlines():
            out.extend(
                (rel, pattern.pattern, line.strip()[:110])
                for pattern in FALSE_WHILE_PGLAST_IS_A_DEPENDENCY
                if pattern.search(line)
            )
    return out


def test_no_document_or_help_string_sells_pglast_as_optional():
    if not pglast_is_a_dependency():
        pytest.skip("pglast is optional again; these sentences would be true")
    bad = findings()
    assert bad == [], "pglast is a dependency; these say otherwise:\n" + "\n".join(
        f"  {f}: {line}" for f, _p, line in bad
    )


def test_the_corpus_is_not_empty():
    """A floor: an empty corpus would make the assertion above vacuous."""
    assert len(corpus()) > 200


def test_every_record_exemption_still_names_a_real_file():
    """A reason cannot outlive the thing it explains."""
    missing = sorted(r for r in RECORDS if not (REPO_ROOT / r).exists())
    assert missing == []


def test_every_record_exemption_would_otherwise_fire():
    """An exemption for a file that no longer says anything is a stale reason."""
    idle = []
    for rel in RECORDS:
        text = (REPO_ROOT / rel).read_text()
        if not any(p.search(text) for p in FALSE_WHILE_PGLAST_IS_A_DEPENDENCY):
            idle.append(rel)
    assert idle == [], f"exemptions that no longer exempt anything: {idle}"
