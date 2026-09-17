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

:data:`KNOWN_ROT` is the rot this guard was introduced on top of, grouped by
cause, shrinking to nothing. A stale entry fails, so it cannot outlive its fix.
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

# Every disagreement this guard found on the day it was written (2026-09-17),
# grouped by what is actually wrong. Each group is one phase of the repair.
KNOWN_ROT: dict[str, tuple[tuple[str, str], ...]] = {
    "the Migration Wizard was never built (no `wizard` in python/ at any commit)": (
        ("docs/api/wizard.md", "confiture migrate --dry-run"),
        ("docs/api/wizard.md", "confiture migrate --schedule"),
        ("docs/api/wizard.md", "confiture migrate --target"),
        ("docs/api/wizard.md", "confiture migrate --wizard"),
        ("docs/api/wizard.md", "confiture migrate cancel"),
        ("docs/api/wizard.md", "confiture migrate list-scheduled"),
        ("docs/api/wizard.md", "confiture migrate run-scheduled"),
        ("docs/guides/interactive-migration-wizard.md", "confiture migrate up --env"),
        ("docs/guides/interactive-migration-wizard.md", "confiture migrate up --non-interactive"),
        (
            "docs/guides/interactive-migration-wizard.md",
            "confiture migrate up --require-confirmation",
        ),
        ("docs/guides/interactive-migration-wizard.md", "confiture migrate wizard"),
    ),
    "the operations runbooks were written against an imagined CLI": (
        ("docs/operations/disaster-recovery.md", "confiture init --force"),
        ("docs/operations/disaster-recovery.md", "confiture migrate down --force"),
        ("docs/operations/disaster-recovery.md", "confiture migrate drift-detect"),
        ("docs/operations/disaster-recovery.md", "confiture migrate rollback-blue-green"),
        ("docs/operations/disaster-recovery.md", "confiture migrate status --verbose"),
        ("docs/operations/disaster-recovery.md", "confiture migrate sync-history"),
        ("docs/operations/performance-tuning.md", "confiture benchmark"),
        ("docs/operations/performance-tuning.md", "confiture pool"),
        ("docs/operations/runbook.md", "confiture health"),
        ("docs/operations/runbook.md", "confiture init --force"),
        ("docs/operations/runbook.md", "confiture migrate checksum"),
        ("docs/operations/runbook.md", "confiture migrate create"),
        ("docs/operations/runbook.md", "confiture migrate down --skip-checksums"),
        ("docs/operations/runbook.md", "confiture migrate down --target"),
        ("docs/operations/runbook.md", "confiture migrate drift-detect"),
        ("docs/operations/runbook.md", "confiture migrate status --verbose"),
        ("docs/operations/runbook.md", "confiture migrate sync-history"),
        ("docs/operations/runbook.md", "confiture migrate update-checksum"),
    ),
    "the command exists, but not at the path the document spells": (
        ("PRD.md", "confiture status"),
        ("docs/getting-started.md", "confiture coordinate complete"),
        ("docs/getting-started.md", "confiture coordinate init"),
        ("docs/guides/git-aware-validation.md", "confiture doc"),
        ("docs/guides/integrations.md", "confiture coordinate complete"),
        ("docs/guides/migration-decision-tree.md", "confiture schema-to-schema"),
        ("docs/guides/notifications.md", "confiture validate"),
        ("docs/guides/view-helpers.md", "confiture admin"),
    ),
    "the command is real and the flag it is given is not": (
        ("PRD.md", "confiture migrate generate --auto-detect"),
        ("PRD.md", "confiture migrate generate --name"),
        ("PRD.md", "confiture migrate schema-to-schema --strategy"),
        ("PRD.md", "confiture migrate up --env"),
        ("docs/api/linting.md", "confiture lint --database"),
        ("docs/api/linting.md", "confiture lint --fix"),
        ("docs/api/linting.md", "confiture lint --rule"),
        ("docs/comparison-with-alembic.md", "confiture migrate generate --name"),
        ("docs/error-reference.md", "confiture seed apply --dry-run"),
        ("docs/guides/01-build-from-ddl.md", "confiture build --dry-run"),
        ("docs/guides/02-incremental-migrations.md", "confiture migrate down --target"),
        ("docs/guides/04-schema-to-schema.md", "confiture build --from-ddl"),
        ("docs/guides/copy-format-examples.md", "confiture build --copy-format"),
        ("docs/guides/copy-format-index.md", "confiture build --copy-format"),
        ("docs/guides/copy-format-loading.md", "confiture build --copy-format"),
        ("docs/guides/copy-format-loading.md", "confiture build --copy-threshold"),
        ("docs/guides/git-aware-validation.md", "confiture migrate up --env"),
        ("docs/guides/legacy-bootstrap.md", "confiture migrate generate --name"),
        ("docs/guides/named-schemas.md", "confiture migrate generate --name"),
        ("docs/guides/prep-seed-validation.md", "confiture seed validate --comprehensive"),
        ("docs/guides/schema-linting.md", "confiture lint --rules"),
        ("docs/guides/seed-loading-decision-tree.md", "confiture build --copy-format"),
        ("docs/guides/seed-validation.md", "confiture seed validate --strict"),
        ("docs/guides/superuser-migrations.md", "confiture migrate up --env"),
        ("docs/index.md", "confiture migrate generate --name"),
        ("docs/index.md", "confiture migrate schema-to-schema --source"),
        ("docs/index.md", "confiture migrate schema-to-schema --target"),
        ("docs/linting.md", "confiture lint --no-fail-on-error"),
        ("docs/linting.md", "confiture migrate up --env"),
        ("docs/organizing-sql-files.md", "confiture migrate generate --name"),
        ("docs/troubleshooting.md", "confiture migrate up --statement-timeout"),
    ),
}


def _allowed() -> set[tuple[str, str]]:
    return {entry for group in KNOWN_ROT.values() for entry in group}


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
    """Nothing in the corpus disagrees with the CLI, beyond the rot listed above."""
    known = _allowed() | set(NOT_INSTRUCTIONS)
    new = sorted(
        f"{f.path}: {f.detail}"
        for f in findings(_doc_invocations())
        if (f.path, f.what) not in known
    )
    assert new == [], "docs naming commands or flags that do not exist:\n" + "\n".join(new)


def test_no_entry_outlives_its_fix() -> None:
    """A repaired document must take its allow-list entry with it.

    Without this the list becomes a second document to forget to update — the
    exact failure the guard exists to catch, one level up.
    """
    found = _found()
    stale = sorted(
        f"{cause}: {path} — {what}"
        for cause, group in KNOWN_ROT.items()
        for path, what in group
        if (path, what) not in found
    )
    assert stale == [], "allow-list entries that no longer match anything:\n" + "\n".join(stale)


def test_no_exemption_outlives_its_sentence() -> None:
    """Same for the permanent exemptions: a deleted sentence must free its entry."""
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
