"""Tripwire: no SQL identifier is hand-quoted into a query string (SEC-01).

``f'SELECT … FROM "{schema}"."{table}"'`` looks safe — the quotes are there —
and is not: a value carrying ``"`` or ``;`` closes the quote and the rest of it
is SQL.  The one correct spelling is ``psycopg.sql.Identifier`` (or
``core.ledger.table_identifier`` for the tracking table), which quotes and
escapes on the way to the server.

This test walks every module under ``python/confiture`` and fails on any
f-string, ``%``-format, ``str.format`` or string concatenation whose text places
an interpolation directly inside the quotes after ``FROM``, ``TABLE``, ``INTO``,
``JOIN`` or ``UPDATE``.  The allowlist is empty and must stay empty: a new
exception is a new injection site, not a false positive.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

_CONFITURE_SRC = Path(__file__).resolve().parents[2] / "python" / "confiture"

# A keyword that introduces a relation name, then an opening double quote, then
# an interpolation marker: `{` for f-strings and str.format, `%` for %-format.
_HAND_QUOTED = re.compile(r'\b(?:FROM|TABLE|INTO|JOIN|UPDATE)\s+"\s*[{%]', re.IGNORECASE)

# A literal that *ends* in the opening quote, so the next operand of a `+` is
# the identifier: `'SELECT 1 FROM "' + name + '"'`.
_OPEN_QUOTE_TAIL = re.compile(r'\b(?:FROM|TABLE|INTO|JOIN|UPDATE)\s+"\s*$', re.IGNORECASE)

# Deliberately empty.  Fix the site instead of listing it here.
ALLOWLIST: frozenset[str] = frozenset()


def _offending_text(node: ast.AST) -> str | None:
    """Return the offending source text if *node* hand-quotes an identifier."""
    if isinstance(node, ast.JoinedStr):
        text = ast.unparse(node)
        return text if _HAND_QUOTED.search(text) else None

    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
        left = node.left
        if isinstance(left, ast.Constant) and isinstance(left.value, str):
            return left.value if _HAND_QUOTED.search(left.value) else None
        return None

    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "format"
        and isinstance(node.func.value, ast.Constant)
        and isinstance(node.func.value.value, str)
    ):
        text = node.func.value.value
        return text if _HAND_QUOTED.search(text) else None

    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = node.left
        while isinstance(left, ast.BinOp) and isinstance(left.op, ast.Add):
            left = left.right
        if isinstance(left, ast.Constant) and isinstance(left.value, str):
            return left.value if _OPEN_QUOTE_TAIL.search(left.value) else None
        return None

    return None


def find_hand_quoted_identifiers(root: Path) -> list[str]:
    """Every ``path:line: text`` under *root* that hand-quotes an identifier."""
    findings: list[str] = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            text = _offending_text(node)
            if text is None:
                continue
            rel = path.relative_to(root.parent.parent).as_posix()
            if rel in ALLOWLIST:
                continue
            findings.append(f"{rel}:{node.lineno}: {text.strip()}")
    return findings


def test_allowlist_is_empty() -> None:
    assert frozenset() == ALLOWLIST, "the allowlist exists to be empty — fix the site"


def test_no_module_hand_quotes_an_identifier() -> None:
    findings = find_hand_quoted_identifiers(_CONFITURE_SRC)
    assert findings == [], (
        "SQL identifiers spliced into a query string by hand:\n  "
        + "\n  ".join(findings)
        + "\nUse psycopg.sql.SQL(...).format(psycopg.sql.Identifier(...)) — or "
        "confiture.core.ledger.table_identifier for the tracking table."
    )


# ---------------------------------------------------------------------------
# The detector itself — each shape it must catch, and the shape it must allow.
# ---------------------------------------------------------------------------


def _scan(source: str) -> list[str]:
    tree = ast.parse(source)
    return [t for t in (_offending_text(n) for n in ast.walk(tree)) if t is not None]


def test_detector_catches_fstring() -> None:
    assert _scan("""q = f'SELECT 1 FROM "{schema}"."{table}"' """)


def test_detector_catches_percent_format() -> None:
    assert _scan("""q = 'DROP TABLE "%s"' % name""")


def test_detector_catches_str_format() -> None:
    assert _scan("""q = 'INSERT INTO "{}" VALUES (1)'.format(name)""")


def test_detector_catches_concatenation() -> None:
    assert _scan("""q = 'SELECT 1 FROM "' + name + '"' """)


def test_detector_allows_identifier_composition() -> None:
    assert not _scan("""q = sql.SQL("SELECT 1 FROM {}").format(sql.Identifier(schema, table))""")


def test_detector_allows_parameter_placeholders() -> None:
    assert not _scan("""q = "SELECT 1 FROM t WHERE name = %s" % (name,)""")
