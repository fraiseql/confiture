"""Every ``confiture …`` command ``docs/`` shows is a command that exists.

``examples/`` got this guard first, and it found three examples documenting a
product that was never built. ``docs/`` was never asked the same question. It
answered worse: **50 command sites and 77 flag sites**, the largest of them a
Migration Wizard that ``git log -S wizard -- python/`` shows has never existed
in the codebase at any commit, documented across 1090 lines in two files that
were both in the published mkdocs nav.

The corpus is the documents that tell a reader what to run *today*:
``docs/`` outside ``release-notes/``, plus the root ``README.md``, ``PRD.md``,
``ARCHITECTURE.md`` and ``CLAUDE.md``.

``CHANGELOG.md`` and ``docs/release-notes/`` are deliberately **out**. They
record what shipped at a version — ``confiture verify`` was real until 0.51.0
removed it — and editing them to satisfy a guard would falsify the record rather
than fix a document. They are not instructions, so they are not checked.

The guard shipped with a `KNOWN_ROT` allow-list of all 127 sites, grouped by
cause, and four phases emptied it. It is gone with the rot it described; what
survives is the shape of the repair, in this module's git history and in the
mutation pins at the bottom.
"""

from __future__ import annotations

import itertools

import pytest
from command_truth import (
    FLAG,
    INVOCATION,
    NOT_OURS,
    REPO_ROOT,
    WORD,
    findings,
    invocations,
    logical_lines,
    resolve,
    tracked,
)

MIN_FILES = 100
MIN_INVOCATIONS = 800

ROOT_DOCUMENTS = ("README.md", "PRD.md", "ARCHITECTURE.md", "CLAUDE.md")

# Text that names a command in order to say it is *not* a command. A guard that
# cannot tell these from an instruction would push the docs into silence about
# their own history, which is worse than the rot it removes.
NOT_INSTRUCTIONS: dict[tuple[str, str], str] = {
    ("docs/reference/cli.md", "confiture verify"): (
        "the sentence documents its removal — `confiture verify` was a deprecated "
        "alias from 0.19.0 and v0.51.0 (a real tag) deleted it"
    ),
}


def _doc_invocations():
    files = [path for path in tracked("docs/**") if "/release-notes/" not in str(path)]
    files += [REPO_ROOT / name for name in ROOT_DOCUMENTS]
    assert len(files) >= MIN_FILES, f"only {len(files)} doc files; the corpus is probably broken"
    found = invocations(files)
    assert len(found) >= MIN_INVOCATIONS, (
        f"only {len(found)} invocations found; the extractor is probably broken"
    )
    return found


def _found() -> set[tuple[str, str]]:
    return {(f.path, f.what) for f in findings(_doc_invocations())}


def test_docs_invoke_only_commands_and_flags_that_exist() -> None:
    """Nothing in the corpus disagrees with the CLI."""
    new = sorted(
        f"{f.path}: {f.detail}"
        for f in findings(_doc_invocations())
        if (f.path, f.what) not in NOT_INSTRUCTIONS
    )
    assert new == [], "docs naming commands or flags that do not exist:\n" + "\n".join(new)


def test_no_exemption_outlives_its_sentence() -> None:
    """A deleted sentence must free its exemption.

    Without this the list becomes a second document to forget to update — the
    exact failure the guard exists to catch, one level up.
    """
    found = _found()
    stale = sorted(
        f"{path} — {what} ({reason})"
        for (path, what), reason in NOT_INSTRUCTIONS.items()
        if (path, what) not in found
    )
    assert stale == [], "exemptions that no longer match anything:\n" + "\n".join(stale)


@pytest.mark.parametrize(
    ("fictional", "reason"),
    [
        ("confiture migrate wizard --review", "the wizard was never built"),
        ("confiture migrate drift-detect", "drift detection is top-level `confiture drift`"),
        ("confiture pool stats", "no `pool` command"),
        ("confiture admin install-helpers --env local", "`install-helpers` is top-level"),
        ("confiture migrate generate --name add_user_bio", "`generate` takes a positional name"),
        ("confiture init --force", "`init` declares no options at all"),
    ],
)
def test_the_guard_would_catch_these(fictional: str, reason: str) -> None:
    """Six that were live in ``docs/`` when this guard was written.

    Pinning them means a refactor that quietly narrows the extractor — a
    stricter regex, a wider placeholder rule, a shallower walk — fails here
    rather than going unnoticed until the next document rots.
    """
    match = INVOCATION.match(fictional)
    assert match, f"the extractor no longer sees an invocation in {fictional!r} ({reason})"
    tokens = tuple(match.group(1).split())
    words = tuple(itertools.takewhile(WORD.match, tokens))
    _resolved, command, leftover = resolve(words)

    if command is None or (leftover and getattr(command, "commands", None)):
        return  # unknown command or subcommand: caught
    declared = {
        opt
        for param in command.params
        for opt in [*getattr(param, "opts", []), *getattr(param, "secondary_opts", [])]
        if opt.startswith("--")
    }
    bad = [f for f in FLAG.findall(fictional) if f not in NOT_OURS and f not in declared]
    assert bad, f"{fictional!r} now resolves cleanly, but should not ({reason})"


def test_a_flag_on_a_continuation_line_is_read() -> None:
    """Read line by line, the guard never saw a flag after a ``\\``: that is how
    ``confiture build --copy-format`` — a flag ``build`` has never had — lived in two
    guides. The command is one logical line."""
    (line,) = logical_lines("confiture build \\\n  --sequential \\\n  --copy-format\n")

    assert "--copy-format" in FLAG.findall(line)


def test_a_flag_inside_a_subshell_is_not_ours() -> None:
    """``$(git diff --name-only)`` inside a command line runs git, not confiture."""
    (line,) = logical_lines("confiture lint --env $(git diff --name-only | head -1)\n")

    assert "--name-only" not in FLAG.findall(line)
