"""A parse failure is a finding, never an empty answer — unless someone else reports it.

A reader that catches ``pglast.parser.ParseError`` and returns ``[]`` (or
``None``, ``False``, ``{}``, or carries on) has answered "nothing here" about a
text it never read. Every such answer confiture gave was a bug: the lint rules
that re-parsed a file and found nothing in it, ``temp_relations`` reading an
unblanked build, ``build --fail-on-duplicates`` reading a seed file as
unparseable. This test fails on a new one.

Each function allowed one says **who reports the failure instead**, or why the
empty answer *is* the answer (an oracle asked "does this compile?"). An entry
whose function no longer has such a handler fails too.
"""

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PACKAGE = REPO / "python" / "confiture"

#: What an empty answer looks like.
EMPTY = frozenset({"[]", "{}", "()", "set()", "frozenset()", "None", "False", "''"})

#: ``module:function`` → who reports the failure, or why empty is the answer.
ALLOWED: dict[str, str] = {
    "python/confiture/core/cor_extractor.py:find_cor_targets": (
        "a pending migration the parser rejects is preflight's PFLIGHT_UNPARSEABLE"
    ),
    "python/confiture/core/data_assertions.py:_elog_level_of": (
        "a probe of PostgreSQL's own compiler: a probe that will not compile disables the "
        "check, never crashes it"
    ),
    "python/confiture/core/data_assertions.py:_derivations": (
        "a migration the parser rejects is preflight's PFLIGHT_UNPARSEABLE; each statement "
        "still scans for assertions"
    ),
    "python/confiture/core/ddl_walk.py:typed_constants": (
        "a default is text the parser already read inside its statement, or pg_get_expr's; "
        "one it cannot read again has no constant to spell, and same_value compares it as "
        "written"
    ),
    "python/confiture/core/fk_extractor.py:_parse": (
        "a span that is not one statement keeps its key where it is written: the answer"
    ),
    "python/confiture/core/function_signature_checker.py:_drops": (
        "a migration the parser rejects is reported by the migration's own checks"
    ),
    "python/confiture/core/linting/references.py:temp_relations": (
        "a body the compiler will not return is named unread by read_references (build_003)"
    ),
    "python/confiture/core/linting/seed_secrets.py:_statement_findings": (
        "a seed file the parser rejects is the lint's UNPARSEABLE notice for that file"
    ),
    "python/confiture/core/linting/seed_secrets.py:findings_in": (
        "a seed file the parser rejects is the lint's UNPARSEABLE notice for that file"
    ),
    "python/confiture/core/plpgsql_parse.py:_compiles": (
        "the oracle's question is whether a body compiles; False is the answer"
    ),
    "python/confiture/core/schema_analyzer.py:_foreign_keys": (
        "dry-run: a statement PostgreSQL rejects fails the dry run's own execution"
    ),
    "python/confiture/core/sql_lexer.py:_scan_recovering": (
        "the scanner's recovery: the tokens before an error, and none past it, is the answer"
    ),
    "python/confiture/core/preflight.py:invalid_index_issues": (
        "a pending migration the parser rejects is preflight's PFLIGHT_UNPARSEABLE"
    ),
    "python/confiture/core/stub_generator.py:jsonb_keys": (
        "a stub whose keys cannot be read is typed as a plain dict, which it says"
    ),
    "python/confiture/core/tview_preflight.py:touches_tview": (
        "the gate asks only whether a TVIEW is touched; applying the migration reports it"
    ),
    "python/confiture/core/tview_preflight.py:live_issues": (
        "a pending migration the parser rejects is preflight's PFLIGHT_UNPARSEABLE"
    ),
}


def _silent(handler: ast.ExceptHandler) -> bool:
    if handler.type is None or "ParseError" not in ast.unparse(handler.type):
        return False
    return all(
        isinstance(statement, (ast.Pass, ast.Continue))
        or (
            isinstance(statement, ast.Return)
            and (statement.value is None or ast.unparse(statement.value) in EMPTY)
        )
        for statement in handler.body
    )


def _silent_handlers(path: Path, root: Path = REPO) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    functions = [
        n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and _silent(node):
            owner = min(
                (f for f in functions if f.lineno <= node.lineno <= (f.end_lineno or f.lineno)),
                key=lambda f: (f.end_lineno or f.lineno) - f.lineno,
            )
            found.add(f"{path.relative_to(root).as_posix()}:{owner.name}")
    return found


def _all() -> set[str]:
    return {key for path in sorted(PACKAGE.rglob("*.py")) for key in _silent_handlers(path)}


def test_no_parse_failure_is_answered_with_nothing() -> None:
    unexpected = sorted(_all() - set(ALLOWED))
    assert unexpected == [], (
        "report the failure (UNPARSEABLE, a degraded rule, an unread body), or say in "
        f"ALLOWED who reports it instead: {unexpected}"
    )


def test_every_allowance_is_still_needed() -> None:
    stale = sorted(set(ALLOWED) - _all())
    assert stale == [], f"no longer answers a parse failure with nothing — drop: {stale}"


def test_a_planted_silent_handler_is_seen(tmp_path: Path) -> None:
    planted = tmp_path / "planted.py"
    planted.write_text(
        "import pglast\n\n"
        "def reader(sql):\n"
        "    try:\n"
        "        return pglast.parse_sql(sql)\n"
        "    except pglast.parser.ParseError:\n"
        "        return []\n"
    )
    assert _silent_handlers(planted, root=tmp_path) == {"planted.py:reader"}
