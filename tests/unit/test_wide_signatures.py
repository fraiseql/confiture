"""A routine's signature reads at any width (#433).

pglast's ``RawStream`` attaches an ``ancestors`` chain to every node it renders, so
once a statement has been rendered, a deep copy of one argument's ``TypeName``
follows that chain through the whole statement. The copy existed only to blank
the typmods; a routine with ~30 parameters exceeded the recursion limit.
"""

from __future__ import annotations

import pglast.parser

from confiture.core.linting.inventory import type_key, type_text
from confiture.platform import parse_schema


def _routine(width: int) -> str:
    params = ", ".join(f"p{i} uuid" for i in range(width))
    return f"CREATE FUNCTION app.f({params}) RETURNS int LANGUAGE sql AS 'select 1';"


def test_a_routine_with_a_hundred_parameters_reads() -> None:
    model = parse_schema(_routine(100))

    ((routine,),) = model.routines.values()
    assert len(routine.signature_key) == 100


def test_reading_a_type_leaves_the_parsed_tree_as_it_was() -> None:
    """The typmods are blanked on a copy: the argument still says ``varchar(10)``."""
    (raw,) = pglast.parser.parse_sql(
        "CREATE FUNCTION app.g(a varchar(10)) RETURNS int LANGUAGE sql AS 'select 1';"
    )
    type_name = raw.stmt.parameters[0].argType

    assert type_text(type_name) == "varchar"
    assert type_key(type_name) == (None, "varchar")
    assert type_name.typmods is not None
