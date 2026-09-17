"""Resolving a ``confiture …`` command line written in a document against the CLI.

The examples campaign built this extractor to prove that a command an example
shows is a command that exists. ``docs/`` needed exactly the same question asked
of it, so the extractor lives here and the two corpora differ only in which
files they hand it — a second copy would have rotted apart from the first.

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
from typing import NamedTuple

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
PREFIX = r"(?:[-*>]\s+|\$\s+|sh\s+['\"]?|run:\s*|uv\s+run\s+|&&\s*|\|\|\s*|;\s*|\w+=\S*\s+)*"
# Capture the whole tail, not a fixed number of words: `confiture migrate
# schema-to-schema setup` is three levels deep, and a guard that assumes two
# reports `schema-to-schema has no --source` against a correct command line.
INVOCATION = re.compile(rf"^\s*{PREFIX}confiture\s+(.*)$")
WORD = re.compile(r"^[a-z][a-z0-9-]*$")

# A usage template names its subcommand with a placeholder — `confiture migrate
# <subcommand> --format json`, `confiture migrate schema-to-schema [SUBCOMMAND]
# --source <db>`. The command is under-determined, so the word after it is not a
# missing subcommand and the flags on the line belong to a subcommand this line
# does not name. Both judgements are suspended; see `_declared_flags`.
PLACEHOLDER = re.compile(r"^[<\[]|^[A-Z][A-Z0-9_-]*$")

FENCED = re.compile(r"```[a-z]*\n(.*?)```", re.S)
INLINE_CODE = re.compile(r"`([^`\n]+)`")

# Files whose whole content is code.
CODE_SUFFIXES = {".sh", ".yml", ".yaml", ".sql", ".py"}

# A command name is only half of an invocation. `confiture migrate up --env
# local`, `confiture sync … --columns emails`, `confiture coordinate resolve
# --intent-id …` all name real commands and pass real-looking flags those
# commands do not have. `--env` reads as plausible because it appears in
# `migrate --help` — inside prose describing precedence, never as an option.
FLAG = re.compile(r"(?<![\w-])--[a-z][a-z0-9-]*")
NOT_OURS = frozenset({"--help", "--version"})


class Invocation(NamedTuple):
    """One ``confiture …`` line found in a document."""

    path: str
    """Repo-relative path of the file it was found in."""
    line: str
    words: tuple[str, ...]
    """The leading lower-case words, which is as far as a command name can run."""
    tokens: tuple[str, ...]
    """Every whitespace-separated token after ``confiture``. ``words`` is a prefix.

    A placeholder is never a ``words`` entry — the lower-case takewhile stops
    before it — so template detection has to read the tokens.
    """


class Finding(NamedTuple):
    """One way a written command line disagrees with the CLI."""

    path: str
    kind: str
    """``command``, ``positional`` or ``flag``."""
    what: str
    """The offending command or flag, as the allow-lists key on it."""
    detail: str


def tracked(*patterns: str) -> list[Path]:
    """Every tracked file matching *patterns*, as absolute paths."""
    out = subprocess.run(
        ["git", "ls-files", "--", *patterns],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return sorted(REPO_ROOT / line for line in out.splitlines() if line)


def code_regions(path: Path) -> list[str]:
    """The parts of *path* that are code rather than prose."""
    text = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix in CODE_SUFFIXES or path.name == "Jenkinsfile":
        return [text]
    if path.suffix != ".md":
        return [text]
    regions = FENCED.findall(text)
    regions.extend(INLINE_CODE.findall(text))
    return regions


def invocations(files: list[Path]) -> list[Invocation]:
    """Every ``confiture …`` invocation in the code regions of *files*."""
    found: list[Invocation] = []
    for path in files:
        if not path.is_file():
            continue
        rel = str(path.relative_to(REPO_ROOT))
        for region in code_regions(path):
            for line in region.splitlines():
                match = INVOCATION.match(line)
                if not match:
                    continue
                tokens = tuple(match.group(1).split())
                words = tuple(itertools.takewhile(WORD.match, tokens))
                if words:
                    found.append(Invocation(rel, line.strip(), words, tokens))
    return found


@functools.cache
def root():
    """The built Typer app. Cached: building it per invocation cost ~17s."""
    return get_command(app)


@functools.cache
def resolve(words: tuple[str, ...]):
    """Walk the command tree as far as *words* name subcommands.

    Returns ``(path, command, unconsumed)``: the dotted path actually resolved,
    the click command it reached, and the words left over. A word that names no
    subcommand of the current group ends the walk — it is an argument, or a
    mistake, and the caller decides which.
    """
    node = root()
    path: list[str] = []
    for index, word in enumerate(words):
        children = getattr(node, "commands", None)
        if not children or word not in children:
            return path, (node if path else None), words[index:]
        node = children[word]
        path.append(word)
    return path, node, ()


def _takes_positional(command) -> bool:
    return any(getattr(p, "param_type_name", "") == "argument" for p in command.params)


def _own_flags(command) -> set[str]:
    declared: set[str] = set()
    for param in command.params:
        declared.update(o for o in getattr(param, "opts", []) if o.startswith("--"))
        declared.update(o for o in getattr(param, "secondary_opts", []) if o.startswith("--"))
    return declared


def _declared_flags(command, *, template: bool) -> set[str]:
    """The flags *command* accepts, widening through a template's unnamed subcommand.

    ``confiture migrate schema-to-schema [SUBCOMMAND] --source <db>`` is a real
    flag of a real subcommand the line declines to name. Accepting any flag a
    descendant declares keeps the template honest about fiction (`--wizard` is
    declared nowhere) without inventing a subcommand for it.
    """
    declared = _own_flags(command)
    children = getattr(command, "commands", None)
    if template and children:
        for child in children.values():
            declared |= _declared_flags(child, template=True)
    return declared


def findings(found: list[Invocation]) -> list[Finding]:
    """Every disagreement between the written command lines and the real CLI."""
    out: list[Finding] = []
    for path, line, words, tokens in found:
        resolved, command, leftover = resolve(words)
        if command is None:
            out.append(
                Finding(
                    path,
                    "command",
                    f"confiture {words[0]}",
                    f"`confiture {words[0]}` is not a command",
                )
            )
            continue

        # `words` is a prefix of `tokens` and `resolved` a prefix of `words`, so
        # the first token the command did not consume is where a placeholder
        # would stand — whether or not it was lower-case enough to be a word.
        rest = tokens[len(resolved) :]
        template = bool(rest) and bool(PLACEHOLDER.match(rest[0]))
        if leftover and not template:
            if getattr(command, "commands", None):
                what = f"confiture {' '.join([*resolved, leftover[0]])}"
                out.append(Finding(path, "command", what, f"`{what}` is not a subcommand"))
                continue
            if not _takes_positional(command):
                what = f"confiture {' '.join(resolved)}"
                out.append(
                    Finding(
                        path,
                        "positional",
                        f"{what} <{leftover[0]}>",
                        f"`{what}` takes no positional argument, but is shown with `{leftover[0]}`",
                    )
                )
                continue

        declared = _declared_flags(command, template=template)
        for flag in FLAG.findall(line):
            if flag in NOT_OURS or flag in declared:
                continue
            what = f"confiture {' '.join(resolved)} {flag}"
            out.append(
                Finding(path, "flag", what, f"`confiture {' '.join(resolved)}` has no `{flag}`")
            )
    return out
