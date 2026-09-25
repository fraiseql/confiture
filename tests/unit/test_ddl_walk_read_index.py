"""``read_index`` keeps what each key's element says after the key (#335).

An operator class, a collation and an ordering are part of the index an author
declared: ``USING gin (username gin_trgm_ops)`` without its operator class is a
statement PostgreSQL refuses, since ``text`` has no default ``gin`` class. Both
sides read an index through this one function — a tree's ``CREATE INDEX`` and
the catalogue's ``pg_get_indexdef`` — so what it keeps, both keep.
"""

from __future__ import annotations

import pglast
import pytest

from confiture.core.ddl_walk import read_index


def _read(sql: str):
    return read_index(pglast.parse_sql(sql)[0].stmt, table="t")


@pytest.mark.parametrize(
    ("sql", "columns", "options"),
    [
        ("CREATE INDEX i ON t (a)", ("a",), ()),
        ("CREATE INDEX i ON t (a DESC NULLS LAST, b)", ("a", "b"), ("DESC NULLS LAST", "")),
        (
            "CREATE INDEX i ON t USING gin (username gin_trgm_ops)",
            ("username",),
            ("gin_trgm_ops",),
        ),
        (
            'CREATE INDEX i ON t (b COLLATE "C" text_pattern_ops)',
            ("b",),
            ('COLLATE "C" text_pattern_ops',),
        ),
        (
            "CREATE INDEX i ON t USING gin ((data ->> 'title') gin_trgm_ops)",
            ("data ->> 'title'",),
            ("gin_trgm_ops",),
        ),
        ('CREATE INDEX i ON t ("Mixed" DESC)', ("Mixed",), ("DESC",)),
    ],
)
def test_each_key_keeps_what_follows_it(sql: str, columns: tuple, options: tuple) -> None:
    index = _read(sql)
    assert (index.columns, index.key_options) == (columns, options)
