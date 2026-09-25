"""One identifier quoter: an identifier written into text is quoted by one function (#375).

Four modules quoted identifiers, each its own way. ``idempotency/_naming`` asked
Python's ``keyword.iskeyword`` whether a name needed quotes, so a suggested guard
for a table named ``user`` or ``order`` wrote it bare — ``user`` is reserved in
PostgreSQL and a keyword in no Python. :func:`confiture.core.schema_identity.quote_identifier`
answers with PostgreSQL's own keyword lists, from the parser confiture already
depends on; :func:`~confiture.core.schema_identity.identifier_identity` is the
one reading back. SQL that is *executed* keeps ``psycopg.sql.Identifier``.

The guard fails on a module outside ``schema_identity`` that doubles a double
quote into an identifier, or undoubles one out of it. The allow-list is empty.
"""

from __future__ import annotations

import re
from pathlib import Path

import pglast
import pytest

import confiture
from confiture.core.idempotency._captures import Captures
from confiture.core.idempotency.models import IdempotencyPattern
from confiture.core.idempotency.suggestion_templates import suggestion_for
from confiture.core.schema_identity import identifier_identity, quote_identifier

PACKAGE = Path(confiture.__file__).resolve().parent
HOME = PACKAGE / "core" / "schema_identity.py"

#: ``.replace('"', '""')`` and ``.replace('""', '"')``, in either quote style.
_QUOTE_DOUBLING = re.compile(
    r"""\.replace\(\s*(?:'"'\s*,\s*'""'|'""'\s*,\s*'"'|"\\""\s*,\s*"\\"\\""|"\\"\\""\s*,\s*"\\"")\s*\)"""
)

ALLOWED: dict[str, str] = {}


@pytest.mark.parametrize(
    ("name", "written"),
    [
        ("users", "users"),
        ("tb_order_line", "tb_order_line"),
        ("user", '"user"'),
        ("order", '"order"'),
        ("select", '"select"'),
        ("authorization", '"authorization"'),
        ("AppOwner", '"AppOwner"'),
        ('a"b', '"a""b"'),
        ("1abc", '"1abc"'),
        ("with space", '"with space"'),
        ("", '""'),
    ],
)
def test_an_identifier_is_quoted_only_where_postgresql_needs_it(name: str, written: str) -> None:
    assert quote_identifier(name) == written


@pytest.mark.parametrize("name", ["users", "user", "order", "AppOwner", 'a"b', "select"])
def test_quoting_round_trips_through_the_identity(name: str) -> None:
    assert identifier_identity(quote_identifier(name)) == name


@pytest.mark.parametrize("schema", [None, "public"])
@pytest.mark.parametrize("table", ["user", "order", "select", "users"])
def test_a_suggested_guard_for_a_reserved_table_name_parses(schema: str | None, table: str) -> None:
    """Qualified, any keyword parses after the dot; bare, ``user`` must be quoted."""
    suggestion = suggestion_for(
        IdempotencyPattern.CREATE_TABLE, Captures(schema=schema, table=table)
    )
    (statement,) = pglast.parse_sql(suggestion.replace("( ... )", "(id int)"))
    assert statement.stmt.relation.relname == table


def test_no_module_but_schema_identity_quotes_an_identifier_by_hand() -> None:
    offenders = sorted(
        str(path.relative_to(PACKAGE))
        for path in PACKAGE.rglob("*.py")
        if path != HOME and _QUOTE_DOUBLING.search(path.read_text(encoding="utf-8"))
    )
    assert [o for o in offenders if o not in ALLOWED] == []
    assert all(reason.strip() for reason in ALLOWED.values())
