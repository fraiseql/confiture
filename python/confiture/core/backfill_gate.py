"""The backfill gate: a generated step the author completes before ``migrate up`` applies it.

Some changes can be refused by the rows a table already holds: a ``NOT NULL``
column nothing fills, ``SET NOT NULL``, an added UNIQUE, primary key or CHECK, a
type the values may not fit. ``migrate diff --generate`` cannot know those rows, so
it writes the change around a placeholder (:mod:`confiture.core.differ_sql`)::

    -- confiture:backfill tb_user.email
    -- Replace this block with the statements that fix …

``backfill`` is the stage expand/contract names for this step
(:data:`confiture.core.expand_contract.StageName`). The author replaces the
placeholder with the statements that fix the rows, or writes
``-- confiture:backfill none`` when no row needs fixing. Until then:

* ``migrate up`` refuses the file (``VALID_010``, exit 5). No flag overrides
  this, because the file is unfinished.
* ``migrate preflight`` reports it (``PFLIGHT_BACKFILL_PENDING``, an error).

A Python migration carries the same placeholders in its ``backfill_pending``
attribute, which the generator writes and the author removes.
"""

from confiture.core.sql_lexer import DIRECTIVE_PREFIX, directives
from confiture.core.sql_utils import comment_text

BACKFILL_DIRECTIVE = "backfill"
#: The argument that says the author checked and no row needs fixing.
NOTHING_TO_FIX = "none"


def placeholder(target: str, rows: str) -> str:
    """The placeholder block for ``target``: what must be fixed, and how to finish it.

    ``rows`` says which rows the change can be refused by, in words an author acts on.
    """
    done = f"-- {DIRECTIVE_PREFIX}{BACKFILL_DIRECTIVE} {NOTHING_TO_FIX}"
    return (
        f"-- {DIRECTIVE_PREFIX}{BACKFILL_DIRECTIVE} {comment_text(target)}\n"
        f"-- Replace this block with the statements that fix {comment_text(rows)},\n"
        f"-- or with `{done}` when no row needs it: migrate up refuses this file until then.\n"
    )


def pending(sql: str) -> list[str]:
    """The targets of the placeholders ``sql`` still carries, in file order."""
    return [
        directive.argument or ""
        for directive in directives(sql)
        if directive.name == BACKFILL_DIRECTIVE and directive.argument != NOTHING_TO_FIX
    ]
