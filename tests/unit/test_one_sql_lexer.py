"""One SQL lexer: ``core/sql_lexer.py`` is the only module that tokenises SQL.

Deciding where a comment ends, what a string literal or a dollar-quoted body
covers, or where ``COPY … FROM stdin`` data stops is libpg_query's scanner's
job, reached through ``sql_lexer``. A regex that carries one of those lexical
markers is a second lexer, and every second lexer confiture ever had disagreed
with the first on some input (``'a--b'``, ``$body$ … $$ … $body$``, a quote in a
COPY row). This test fails on a new one.

Regexes that match the *shape* of a statement (``^CREATE\\s+TABLE``) are a
different residue — shape matching pglast should do — and are counted by the
shrink-only ``sql_keyword_regex`` budget in ``tests/budgets.json``.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
# The source tree, not the imported package: the Publish workflow runs this suite
# against the built wheel, where ``confiture.__file__`` lives in the virtualenv.
PACKAGE = REPO / "python" / "confiture"
LEXER = PACKAGE / "core" / "sql_lexer.py"

# Substrings of a regex pattern's text that mean it lexes SQL: a line or block
# comment opener, a dollar quote, a single-quoted literal, COPY's ``stdin`` and
# its ``\.`` terminator.
LEXICAL_MARKERS = ("--", "/\\*", "\\$", "'[^']", "stdin", "\\\\\\.")

# Files whose marker-carrying pattern does not read SQL, with the reason. An
# entry whose file no longer carries such a pattern is stale and fails.
ALLOWED: dict[str, str] = {
    "python/confiture/config/_env_vars.py": (
        "`${VAR}` expansion in YAML configuration values; the text is not SQL"
    ),
    "python/confiture/core/temp_database.py": (
        "drops pg_dump's own header lines (`-- Dumped from …`, `SET …`) from a dump's noise; "
        "it recognises fixed lines pg_dump writes, it never decides where a comment ends"
    ),
    "python/confiture/testing/frameworks/mutation.py": (
        "a mutation operator that rewrites the DEFAULT clause of the framework's own SQL sample"
    ),
}


@pytest.fixture(scope="module")
def budgets_module():
    spec = importlib.util.spec_from_file_location("budgets", REPO / "scripts" / "budgets.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _lexical_regexes(budgets_module) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        if path == LEXER:
            continue
        for line, pattern in budgets_module.regex_patterns(path):
            if any(marker in pattern for marker in LEXICAL_MARKERS):
                rel = path.relative_to(REPO).as_posix()
                found.setdefault(rel, []).append(f"{rel}:{line}: {pattern[:70]!r}")
    return found


def test_no_regex_lexes_sql_outside_the_lexer(budgets_module) -> None:
    offenders = [
        line
        for rel, lines in _lexical_regexes(budgets_module).items()
        if rel not in ALLOWED
        for line in lines
    ]
    assert offenders == [], "second lexers:\n  " + "\n  ".join(offenders)


def test_allow_list_is_current(budgets_module) -> None:
    present = set(_lexical_regexes(budgets_module))
    stale = sorted(rel for rel in ALLOWED if rel not in present)
    assert stale == [], f"allow-list entries with nothing left to allow: {stale}"


def test_only_the_lexer_calls_the_scanner() -> None:
    """``pglast.parser.scan`` / ``pglast.split`` are reached through ``sql_lexer`` only."""
    callers: list[str] = []
    for path in sorted(PACKAGE.rglob("*.py")):
        if path == LEXER:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Attribute) and node.attr in ("scan", "split"):
                root = node.value
                while isinstance(root, ast.Attribute):
                    root = root.value
                if isinstance(root, ast.Name) and root.id == "pglast":
                    callers.append(f"{path.relative_to(REPO).as_posix()}:{node.lineno}")
    assert callers == [], callers
