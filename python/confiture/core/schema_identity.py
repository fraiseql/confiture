"""Where an unqualified schema object lands: the one default schema.

``CREATE TABLE t`` and ``CREATE TABLE public.t`` are the same table, so a reader
deciding whether two statements are about one object folds a missing qualifier
to this. Every such reader folds it to the *same* thing, which is why the
constant has one home and the literal ``"public"`` appears beside a schema
variable nowhere else — ``tests/unit/test_one_object_identity.py`` fails on a
second spelling of it (#313).

A role, a schema or any other identifier written in SQL has the same split: what
PostgreSQL holds (:func:`identifier_identity`) and how SQL writes it. Compare the
first; write the second.

Import-safe on purpose. ``core/linting/inventory`` decides object identity but
imports pglast, and a module that only needs to resolve a bare relation name for
a catalogue query — a batched backfill, an idempotency suggestion — should not
pay for a parser to learn one word: made to, it is tempted to write the word
instead. The identity is the fold; the *spelling* an object prints is
:func:`~confiture.core.schema_model.qualified_name`, which never invents a
qualifier the author did not write.
"""

from __future__ import annotations

import re
from functools import cache

#: Where an unqualified ``CREATE`` lands, for the purpose of deciding whether
#: two statements define the same object: ``f()`` and ``public.f()`` are one.
DEFAULT_SCHEMA = "public"


def identifier_identity(written: str) -> str:
    """The identifier PostgreSQL holds for one written in SQL.

    A quoted one is itself, its quotes removed and ``""`` undoubled (``"AppOwner"``
    is ``AppOwner``); a bare one is folded to lower case (``AppOwner`` is
    ``appowner``). Compare identities; write the spelling.
    """
    if len(written) > 1 and written.startswith('"') and written.endswith('"'):
        return written[1:-1].replace('""', '"')
    return written.lower()


#: A name SQL may write bare: lower case, and not starting with a digit.
_BARE = re.compile(r"[a-z_][a-z0-9_$]*")


@cache
def _needs_quotes() -> frozenset[str]:
    """The keywords that cannot be a bare identifier: reserved and type-or-function names.

    From pglast's copy of PostgreSQL's grammar (every supported major has it),
    imported on first use so that importing this module stays free of the parser.
    """
    # Reason: import-safety — pglast is a dependency, but this module is imported by code that parses nothing
    from pglast import keywords

    return frozenset(keywords.RESERVED_KEYWORDS | keywords.TYPE_FUNC_NAME_KEYWORDS)


def quote_identifier(name: str) -> str:
    """*name* as SQL writes it: bare where PostgreSQL reads it back as itself, quoted otherwise.

    The one quoter of an identifier written into text — a suggestion, a generated
    file, a statement a parser reads back. SQL confiture *executes* composes
    identifiers with ``psycopg.sql.Identifier`` instead.
    """
    if _BARE.fullmatch(name) and name not in _needs_quotes():
        return name
    return '"' + name.replace('"', '""') + '"'
