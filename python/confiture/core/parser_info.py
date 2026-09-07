"""What parses the SQL: pglast's version and the PostgreSQL grammar it embeds.

Every verdict confiture gives about DDL comes from pglast (D13). A standard
install once classified with a regex backend while reporting a version that
looked exactly like an AST-capable one (#210); now ``confiture --version``
names the parser on its second line and every JSON envelope carries
:func:`parser_stamp`.
"""

from __future__ import annotations

import re
from importlib import metadata
from typing import Any

from pglast import parser as _pglast_parser

_INDEX_RE = re.compile(r"at index (\d+)")


def pglast_version() -> str:
    """The installed pglast release, e.g. ``"8.4"``."""
    return metadata.version("pglast")


def pg_grammar_major() -> int:
    """The PostgreSQL major whose grammar this pglast embeds, e.g. ``18``."""
    return int(_pglast_parser.get_postgresql_version()[0])


def parser_stamp() -> dict[str, Any]:
    """The ``parser`` object every JSON envelope carries."""
    return {"pglast": pglast_version(), "pg_major": pg_grammar_major()}


def parser_line() -> str:
    """The second line of ``confiture --version``."""
    return f"parser: pglast {pglast_version()} (PostgreSQL {pg_grammar_major()} grammar)"


def parse_error_index(exc: BaseException) -> int | None:
    """The character offset a :class:`pglast.parser.ParseError` points at, if it says.

    pglast reports it in the message (``… at index 7``); the ``location``
    attribute is not populated by every build.
    """
    index = getattr(exc, "location", None)
    if isinstance(index, int) and index >= 0:
        return index
    m = _INDEX_RE.search(str(exc))
    return int(m.group(1)) if m else None


def parse_error_line(sql: str, exc: BaseException) -> int:
    """The 1-based line of a :class:`pglast.parser.ParseError` in ``sql``."""
    index = parse_error_index(exc) or 0
    return sql.count("\n", 0, min(index, len(sql))) + 1
