"""What parses the SQL: pglast's version and the PostgreSQL grammar it embeds.

Every verdict confiture gives about DDL comes from pglast (D13).
``confiture --version`` names the parser on its second line and every JSON
envelope carries :func:`parser_stamp`, so which parser produced a verdict is
stated rather than inferred from confiture's own version (#210).
"""

from __future__ import annotations

import codecs
import re
from importlib import metadata
from typing import Any

from pglast import parser as _pglast_parser

_INDEX_RE = re.compile(r"at index (\d+)")

#: What a non-ASCII character becomes in :func:`ascii_shadow`. PostgreSQL's scanner
#: reads every byte over 0x7f as a letter, and so ``x`` stands for one exactly; it
#: also cannot spell ``COPY``, ``FROM`` or ``stdin``, the words the lexer looks for.
_SHADOW_CHAR = "x"
_SHADOW_ERRORS = "confiture.ascii_shadow"


def _shadow_run(error: UnicodeError) -> tuple[str, int]:
    """One ``x`` per character of the run ASCII cannot take, so the length holds."""
    if not isinstance(error, UnicodeEncodeError):
        raise error
    return _SHADOW_CHAR * (error.end - error.start), error.end


codecs.register_error(_SHADOW_ERRORS, _shadow_run)


def ascii_shadow(text: str) -> str:
    """*text* with every non-ASCII character replaced by one ``x``.

    Same length, same newlines, same token boundaries — an offset into the shadow
    is that offset in *text* — and pure ASCII, which is the point: pglast reports
    the offset of a syntax error in a unit that is neither characters nor bytes
    when a multibyte character precedes it (measured on 6.16 and 8.4, both
    ``scan`` and ``parse_sql``). Over ASCII the three agree, so an index taken
    from the shadow indexes *text*.

    The substitution is lexically invisible: PostgreSQL's scanner classes every
    byte over 0x7f as an identifier character, exactly as it classes ``x``, so a
    word, a quoted string, a comment and a dollar-quoted body keep their extents.
    The *text* of a token is always read from *text* itself, never from here.
    """
    return text.encode("ascii", errors=_SHADOW_ERRORS).decode("ascii")


def is_ascii(text: str) -> bool:
    """Whether *text* needs no shadow."""
    return text.isascii()


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
    """The 1-based line of a :class:`pglast.parser.ParseError` in ``sql``.

    An index reported for text carrying a multibyte character is short of the
    truth, so the offset is taken again from :func:`ascii_shadow` — the same text
    to the scanner, and ASCII, where pglast's index is the character's. The
    failing call is not known here, so both are tried and the first refusal
    answers; a shadow neither refuses leaves the reported index to stand.
    """
    index = parse_error_index(exc) or 0
    if not is_ascii(sql):
        index = _shadow_index(sql) or index
    return sql.count("\n", 0, min(index, len(sql))) + 1


def _shadow_index(sql: str) -> int | None:
    """The offset at which the shadow of *sql* is refused, by the parser or the scanner."""
    shadow = ascii_shadow(sql)
    for read in (_pglast_parser.parse_sql, lambda text: list(_pglast_parser.scan(text))):
        try:
            read(shadow)
        except _pglast_parser.ParseError as exc:
            return parse_error_index(exc)
    return None
