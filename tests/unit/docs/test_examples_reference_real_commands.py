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

Resolution goes through the live Typer app, never a hand-maintained list of
command names: a list is the same rot one level up, and would have to be updated
by exactly the person who forgot to update the docs.
"""

from __future__ import annotations

import functools
import itertools
import re
import subprocess
from pathlib import Path

import pytest
from typer.main import get_command

from confiture.cli.main import app

REPO_ROOT = Path(__file__).resolve().parents[3]

# Prose says things like "confiture builds from DDL", "# Common confiture lint
# commands" and "the DDL confiture builds from". A naive extractor reads those as
# the commands `builds`, `lint commands` and `builds` — and all three occur in
# this repository, two of them inside fenced code blocks, so looking only at code
# is not enough on its own.
#
# What separates an invocation from a mention is position: a command starts a
# line. Everything allowed before it is a bounded set of prefixes — a list
# bullet, a shell prompt, a pipeline operator, `uv run`, an inline environment
# assignment — and never an English word. Prose that mentions confiture
# mid-sentence is thereby excluded without modelling English.
_PREFIX = r"(?:[-*>]\s+|\$\s+|sh\s+['\"]?|run:\s*|uv\s+run\s+|&&\s*|\|\|\s*|;\s*|\w+=\S*\s+)*"
# Capture the whole tail, not a fixed number of words: `confiture migrate
# schema-to-schema setup` is three levels deep, and a guard that assumes two
# reports `schema-to-schema has no --source` against a correct command line.
_INVOCATION = re.compile(rf"^\s*{_PREFIX}confiture\s+(.*)$")
_WORD = re.compile(r"^[a-z][a-z0-9-]*$")

_FENCED = re.compile(r"```[a-z]*\n(.*?)```", re.S)
_INLINE_CODE = re.compile(r"`([^`\n]+)`")

# Files whose whole content is code.
_CODE_SUFFIXES = {".sh", ".yml", ".yaml", ".sql", ".py"}

MIN_FILES = 10
MIN_INVOCATIONS = 20


def _tracked(*patterns: str) -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "--", *patterns],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return sorted(REPO_ROOT / line for line in out.splitlines() if line)


def _code_regions(path: Path) -> list[str]:
    """The parts of *path* that are code rather than prose."""
    text = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix in _CODE_SUFFIXES or path.name == "Jenkinsfile":
        return [text]
    if path.suffix != ".md":
        return [text]
    regions = _FENCED.findall(text)
    regions.extend(_INLINE_CODE.findall(text))
    return regions


def _invocation_lines() -> list[tuple[Path, str, tuple[str, ...]]]:
    """``(path, line, words)`` for every invocation in tracked example files."""
    files = _tracked("examples/**", "examples/*")
    assert len(files) >= MIN_FILES, "the examples lost their files"
    found: list[tuple[Path, str, tuple[str, ...]]] = []
    for path in files:
        if not path.is_file():
            continue
        for region in _code_regions(path):
            for line in region.splitlines():
                match = _INVOCATION.match(line)
                if match:
                    words = list(itertools.takewhile(_WORD.match, match.group(1).split()))
                    if words:
                        found.append((path, line, tuple(words)))
    return found


@functools.cache
def _root():
    """The built Typer app. Cached: building it per invocation cost ~17s."""
    return get_command(app)


@functools.cache
def _resolve(words: tuple[str, ...]):
    """Walk the command tree as far as *words* name subcommands.

    Returns ``(path, command, unconsumed)``: the dotted path actually resolved,
    the click command it reached, and the words left over. A word that names no
    subcommand of the current group ends the walk — it is an argument, or a
    mistake, and the caller decides which.
    """
    node = _root()
    path: list[str] = []
    for index, word in enumerate(words):
        children = getattr(node, "commands", None)
        if not children or word not in children:
            return path, (node if path else None), words[index:]
        node = children[word]
        path.append(word)
    return path, node, ()


def test_every_example_command_exists() -> None:
    """No example invokes a confiture command or subcommand that is not registered."""
    invocations = _invocation_lines()
    assert len(invocations) >= MIN_INVOCATIONS, (
        f"only {len(invocations)} invocations found; the extractor is probably broken"
    )

    failures: list[str] = []
    for path, _line, words in invocations:
        resolved, command, leftover = _resolve(words)
        if command is None:
            failures.append(
                f"{path.relative_to(REPO_ROOT)}: `confiture {words[0]}` is not a command"
            )
            continue
        # Words left over against a *group* are a subcommand that does not exist.
        # Against a leaf they are arguments, which the next test judges.
        if leftover and getattr(command, "commands", None):
            failures.append(
                f"{path.relative_to(REPO_ROOT)}: `confiture {' '.join([*resolved, leftover[0]])}` "
                "is not a subcommand"
            )
    assert failures == [], "examples invoking commands that do not exist:\n" + "\n".join(
        sorted(set(failures))
    )


def test_leaf_commands_are_not_given_a_subcommand() -> None:
    """``confiture sync production-to-staging`` — a positional a leaf command cannot take.

    ``sync`` takes no arguments at all, so a bare word after it is neither a
    subcommand nor a value; it is a command line that fails to parse. Eighteen
    sites in example 04 were doing exactly this.
    """
    failures: list[str] = []
    for path, _line, words in _invocation_lines():
        resolved, command, leftover = _resolve(words)
        if command is None or not leftover or getattr(command, "commands", None):
            continue
        takes_arguments = any(
            getattr(param, "param_type_name", "") == "argument" for param in command.params
        )
        if not takes_arguments:
            failures.append(
                f"{path.relative_to(REPO_ROOT)}: `confiture {' '.join(resolved)}` takes no "
                f"positional argument, but is shown with `{leftover[0]}`"
            )
    assert failures == [], "\n".join(sorted(set(failures)))


# A command name is only half of an invocation. `confiture migrate up --env
# local`, `confiture sync … --columns emails`, `confiture coordinate resolve
# --intent-id …` all name real commands and pass real-looking flags those
# commands do not have. The first was in example 02 six times and in 01 and 05
# besides; `--env` reads as plausible because it appears in `migrate --help` —
# inside prose describing precedence, never as an option.
_FLAG = re.compile(r"(?<![\w-])--[a-z][a-z0-9-]*")
_NOT_OURS = frozenset({"--help", "--version"})


def test_every_example_flag_exists() -> None:
    """No example passes a confiture command a flag that command does not declare."""
    failures: list[str] = []
    checked = 0
    for path, line, words in _invocation_lines():
        resolved, command, _leftover = _resolve(words)
        if command is None:
            continue  # the command guard above already reports this
        declared: set[str] = set()
        for param in command.params:
            declared.update(o for o in getattr(param, "opts", []) if o.startswith("--"))
            declared.update(o for o in getattr(param, "secondary_opts", []) if o.startswith("--"))
        for flag in _FLAG.findall(line):
            if flag in _NOT_OURS:
                continue
            checked += 1
            if flag not in declared:
                failures.append(
                    f"{path.relative_to(REPO_ROOT)}: "
                    f"`confiture {' '.join(resolved)}` has no `{flag}`"
                )
    assert checked > 0, "no flags found; the extractor is probably broken"
    assert failures == [], "examples passing flags that do not exist:\n" + "\n".join(
        sorted(set(failures))
    )


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
    match = _INVOCATION.match(fictional)
    assert match, f"the extractor no longer sees an invocation in {fictional!r} ({reason})"
    words = tuple(itertools.takewhile(_WORD.match, match.group(1).split()))
    _resolved, command, leftover = _resolve(words)

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
    bad_flags = [f for f in _FLAG.findall(fictional) if f not in _NOT_OURS and f not in declared]
    assert bad_flags, f"{fictional!r} now resolves cleanly, but should not ({reason})"
