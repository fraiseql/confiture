"""Every ``confiture …`` command an example shows is a command that exists.

Three examples had rotted into documentation of a product that was never built:

- ``04-production-sync-anonymization`` invoked ``confiture sync
  production-to-staging`` eighteen times — a positional form the command has
  never had — plus ``confiture audit-pii``.
- ``cicd`` ran ``confiture health check --timeout 60`` in a Jenkinsfile, an Argo
  workflow and a GitLab pipeline, and called four ``migrate`` subcommands that
  do not exist.
- ``02-fraiseql-integration`` passed ``--env`` to ``migrate`` commands that take
  ``--config``.

None of it was caught, because a README is not executed and these examples ship
no ``run.sh``. A command name is the cheapest thing in a document to check
mechanically, so it is checked here.

The extraction and resolution live in :mod:`command_truth`, shared with
``test_docs_reference_real_commands``; this module is the examples corpus and
the record of what it was built to catch.
"""

from __future__ import annotations

import itertools

import pytest
from command_truth import FLAG, INVOCATION, NOT_OURS, WORD, findings, invocations, resolve, tracked

MIN_FILES = 10
MIN_INVOCATIONS = 20


def _example_invocations():
    files = tracked("examples/**", "examples/*")
    assert len(files) >= MIN_FILES, "the examples lost their files"
    found = invocations(files)
    assert len(found) >= MIN_INVOCATIONS, (
        f"only {len(found)} invocations found; the extractor is probably broken"
    )
    return found


def _report(kind: str) -> list[str]:
    return sorted(
        {f"{f.path}: {f.detail}" for f in findings(_example_invocations()) if f.kind == kind}
    )


def test_every_example_command_exists() -> None:
    """No example invokes a confiture command or subcommand that is not registered."""
    failures = _report("command")
    assert failures == [], "examples invoking commands that do not exist:\n" + "\n".join(failures)


def test_leaf_commands_are_not_given_a_subcommand() -> None:
    """``confiture sync production-to-staging`` — a positional a leaf command cannot take.

    ``sync`` takes no arguments at all, so a bare word after it is neither a
    subcommand nor a value; it is a command line that fails to parse. Eighteen
    sites in example 04 were doing exactly this.
    """
    assert _report("positional") == [], "\n".join(_report("positional"))


def test_every_example_flag_exists() -> None:
    """No example passes a confiture command a flag that command does not declare."""
    failures = _report("flag")
    assert failures == [], "examples passing flags that do not exist:\n" + "\n".join(failures)


@pytest.mark.parametrize(
    ("fictional", "reason"),
    [
        ("confiture health check --timeout 60", "no `health` command"),
        ("confiture migrate blue-green", "no `blue-green` subcommand"),
        ("confiture audit-pii --warn-on-new-columns", "no `audit-pii` command"),
        ("confiture sync production-to-staging --anonymize", "`sync` takes no positional"),
        ("confiture migrate up --env local", "`migrate up` has no `--env`"),
    ],
)
def test_the_extractor_would_catch_these(fictional: str, reason: str) -> None:
    """The guard is only worth having if it fails on what it was built for.

    All five were live in ``examples/`` before this test existed. Pinning them
    means a refactor that quietly narrows the extractor — a stricter regex, a
    dropped file type, a shallower walk — fails here rather than going unnoticed
    until the next example rots.
    """
    match = INVOCATION.match(fictional)
    assert match, f"the extractor no longer sees an invocation in {fictional!r} ({reason})"
    words = tuple(itertools.takewhile(WORD.match, match.group(1).split()))
    _resolved, command, leftover = resolve(words)

    if command is None:
        return  # unknown command: caught
    if leftover and getattr(command, "commands", None):
        return  # unknown subcommand: caught
    if leftover and not any(
        getattr(param, "param_type_name", "") == "argument" for param in command.params
    ):
        return  # positional a leaf cannot take: caught
    declared = {
        opt
        for param in command.params
        for opt in [*getattr(param, "opts", []), *getattr(param, "secondary_opts", [])]
        if opt.startswith("--")
    }
    bad_flags = [f for f in FLAG.findall(fictional) if f not in NOT_OURS and f not in declared]
    assert bad_flags, f"{fictional!r} now resolves cleanly, but should not ({reason})"
