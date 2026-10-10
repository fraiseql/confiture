"""The relations a migration says it creates: ``-- confiture:creates <relation>``.

The generator writes one such line above each ``CREATE TABLE`` and ``CREATE
MATERIALIZED VIEW`` it writes without ``IF NOT EXISTS`` — in a file that runs in
one transaction, where PostgreSQL itself proves the relation new and a failure
rolls the whole file back. ``migrate validate --idempotent`` reads the line as
intent and accepts that plain create; ``migrate fix --idempotent`` leaves it as
written.

A relation is matched **as written**: ``-- confiture:creates t`` declares ``t``
and not ``public.t``, and ``app.t`` declares ``app.t`` and not ``t``. Each part
is folded as PostgreSQL folds an identifier, so ``Users`` declares ``users`` and
``"Users"`` declares ``Users``. An argument that is not a name of one or two
parts — three parts, two words, a trailing ``;``, nothing — declares nothing: a
directive this module cannot read exempts nothing.

``migrate preflight`` never reads this directive. Its proof that a relation is
new is the plain ``CREATE`` statement, never what a comment claims.
"""

from confiture.core.schema_identity import identifier_identity
from confiture.core.sql_lexer import DIRECTIVE_PREFIX, directives, name_parts
from confiture.core.sql_utils import comment_text

CREATES_DIRECTIVE = "creates"

#: A declared relation: ``(schema, name)`` as PostgreSQL holds each written part,
#: the schema ``None`` when the directive wrote none.
Declared = tuple[str | None, str]


def creates_line(spelling: str) -> str:
    """The ``-- confiture:creates <spelling>`` line, one line whatever *spelling* holds."""
    return f"-- {DIRECTIVE_PREFIX}{CREATES_DIRECTIVE} {comment_text(spelling)}"


def relation_named(written: str | None) -> Declared | None:
    """The relation *written* names, folded, or ``None`` unless it is a name of one or two parts."""
    match name_parts(written) if written else None:
        case [name]:
            return None, identifier_identity(name)
        case [schema, name]:
            return identifier_identity(schema), identifier_identity(name)
        case _:
            return None


def declared(sql: str) -> frozenset[Declared]:
    """Every relation *sql*'s ``creates`` directives name, as written and folded."""
    found = (relation_named(d.argument) for d in directives(sql) if d.name == CREATES_DIRECTIVE)
    return frozenset(relation for relation in found if relation is not None)
