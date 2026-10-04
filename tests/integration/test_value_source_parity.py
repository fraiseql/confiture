"""The tree and the database it builds agree on where each column's value comes from.

A ``serial`` is ``integer`` with a ``nextval`` default in the catalog; a
``gen_random_uuid()`` default comes back as ``gen_random_uuid()``. Each reader
classifies the default from the parse tree it holds, so both sides answer
``Column.value_source`` the same way.

Requires a running PostgreSQL server accessible via CONFITURE_TEST_DB_URL.
"""

import psycopg

from confiture.core import live_catalog
from confiture.core.schema_read import read_text

TREE = """\
CREATE SEQUENCE app.s;
CREATE TABLE app.t (
    a bigint GENERATED ALWAYS AS IDENTITY,
    b numeric GENERATED ALWAYS AS (1 + 2) STORED,
    c serial,
    d bigint DEFAULT nextval('app.s'),
    e uuid DEFAULT gen_random_uuid(),
    f timestamptz DEFAULT now(),
    g text DEFAULT 'x',
    h jsonb DEFAULT '{}'::jsonb,
    i text
);
"""


def test_both_sides_say_where_each_value_comes_from(clean_test_db: psycopg.Connection) -> None:
    with clean_test_db.cursor() as cur:
        cur.execute("CREATE SCHEMA app;")
        cur.execute(TREE)
    clean_test_db.commit()

    (parsed,) = read_text(TREE).model.tables.values()
    (live,) = live_catalog.read(clean_test_db, schemas=["app"]).tables.values()

    assert {c.name: c.value_source for c in live.columns} == {
        c.name: c.value_source for c in parsed.columns
    }
