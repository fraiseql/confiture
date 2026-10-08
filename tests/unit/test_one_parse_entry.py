"""One way into the parser: ``sql_lexer.parse_file`` is how SQL a file holds gets parsed.

A file of DDL, a migration, a seed or a build bundle can carry a ``COPY … FROM
stdin`` block, whose rows are psql client protocol: PostgreSQL's parser rejects
them, and every module that handed such text to ``pglast.parse_sql`` itself either
refused a file confiture wrote (#561) or answered as if the file held nothing.
``parse_file`` blanks the block first, keeping every offset and line.

This test fails on a call of pglast's parser outside ``core/sql_lexer.py``.
Each module allowed one parses something that can never hold a ``COPY`` block —
one expression, one generated statement, one PL/pgSQL fragment — and says
which. An entry whose module no longer calls the parser fails too.
"""

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
# The source tree, not the imported package: the Publish workflow runs this suite
# against the built wheel, where ``confiture.__file__`` lives in the virtualenv.
PACKAGE = REPO / "python" / "confiture"
ENTRY = PACKAGE / "core" / "sql_lexer.py"

#: The parser's entry points, however they are reached.
PARSERS = frozenset({"parse_sql", "parse_sql_json", "parse_sql_protobuf"})

#: Module → why what it parses can never hold a ``COPY … FROM stdin`` block.
ALLOWED: dict[str, str] = {
    "python/confiture/core/ddl_objects.py": (
        "re-parses one statement it rendered itself (an object's `create_sql`, a generated `DROP`)"
    ),
    "python/confiture/core/ddl_walk.py": (
        "one expression (`SELECT <default>`) or one TVIEW query, never a file"
    ),
    "python/confiture/core/fk_extractor.py": (
        "one statement span cut from text `build.two_pass` has already blanked"
    ),
    "python/confiture/core/linting/references.py": (
        "the body of a `LANGUAGE sql` routine: statements inside a dollar quote, never psql data"
    ),
    "python/confiture/core/linting/tview_rules.py": "one index key expression (`SELECT <key>`)",
    "python/confiture/core/live_catalog.py": (
        "definitions PostgreSQL's catalog returns (`pg_get_expr`, `pg_get_indexdef`, …), one each"
    ),
    "python/confiture/core/plpgsql_fragments.py": "one SQL fragment of a compiled PL/pgSQL body",
    "python/confiture/core/seed/validation/prep_seed/seed_rows.py": (
        "a `COPY` block's own statement line — the block's rows are read as data, never parsed"
    ),
    "python/confiture/core/stub_generator.py": (
        "a routine's body as the catalog returns it (`pg_get_functiondef`)"
    ),
}


def _calls(path: Path) -> list[int]:
    """The line of every call of a pglast parser in *path*, by attribute or imported name."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported = {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("pglast")
        for alias in node.names
        if alias.name in PARSERS
    }
    lines = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (isinstance(func, ast.Attribute) and func.attr in PARSERS) or (
            isinstance(func, ast.Name) and func.id in imported
        ):
            lines.append(node.lineno)
    return lines


def _callers() -> dict[str, list[int]]:
    found = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        if path == ENTRY:
            continue
        lines = _calls(path)
        if lines:
            found[path.relative_to(REPO).as_posix()] = lines
    return found


def test_only_the_lexer_calls_the_parser() -> None:
    unexpected = {module: lines for module, lines in _callers().items() if module not in ALLOWED}
    assert unexpected == {}, (
        "parse a file through sql_lexer.parse_file, which blanks COPY data first; "
        "a module whose text can never hold COPY data goes in ALLOWED with the reason:\n"
        + "\n".join(f"  {module}: lines {lines}" for module, lines in unexpected.items())
    )


def test_every_allowance_is_still_needed() -> None:
    stale = sorted(set(ALLOWED) - set(_callers()))
    assert stale == [], f"no longer calls the parser — drop from ALLOWED: {stale}"


def test_a_call_by_imported_name_is_seen(tmp_path: Path) -> None:
    planted = tmp_path / "planted.py"
    planted.write_text("from pglast.parser import parse_sql as p\n\np('SELECT 1')\n")
    assert _calls(planted) == [3]
