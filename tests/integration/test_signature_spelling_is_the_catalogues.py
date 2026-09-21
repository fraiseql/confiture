"""A report prints a routine's argument types exactly as ``format_type`` does.

``--check-signatures`` prints ``stale_signature``, ``source_signatures`` and
``missing_from_db``, and ``fix-signatures`` executes ``DROP FUNCTION`` on the
first of them. Consumers key alert state on those strings, so the spelling a
report prints for a routine read live must be the spelling it printed before
the readers moved onto the model — ``format_type``'s, lower-cased — and it is
now printed from the routine's canonical key, through the one canonicaliser.

This walks every type in ``pg_catalog`` that a routine argument can name, and
its array, and asserts the round trip is exact: keyed by
``type_lattice.signature_from_type_names`` and printed by
``type_lattice.catalog_spelling``, each reads back as ``format_type`` wrote it.
"""

from __future__ import annotations

from collections.abc import Callable

import psycopg

from confiture.core.type_lattice import catalog_spelling, signature_from_type_names

_CATALOG_TYPES = """
SELECT format_type(t.oid, NULL) FROM pg_type t
WHERE t.typisdefined AND t.typrelid = 0 AND t.typtype <> 'p'
  AND t.typnamespace = 'pg_catalog'::regnamespace
UNION
SELECT format_type(t.typarray, NULL) FROM pg_type t
WHERE t.typarray <> 0 AND t.typrelid = 0 AND t.typtype <> 'p'
  AND t.typnamespace = 'pg_catalog'::regnamespace
"""


def _printed(spelled: str) -> str:
    ((schema, name),) = signature_from_type_names([spelled])
    return f"{schema}.{catalog_spelling(name)}" if schema else catalog_spelling(name)


def test_every_catalogue_type_prints_as_format_type_wrote_it(
    fresh_database_factory: Callable[[str], str],
) -> None:
    with psycopg.connect(fresh_database_factory("confiture_spelling")) as conn:
        spelled = [row[0] for row in conn.execute(_CATALOG_TYPES).fetchall()]
    assert len(spelled) > 200, "the catalogue query found almost nothing to check"
    mismatched = {s: _printed(s) for s in spelled if _printed(s) != s.lower()}
    assert mismatched == {}


def test_a_user_type_prints_with_the_schema_format_type_gave_it(
    fresh_database_factory: Callable[[str], str],
) -> None:
    with psycopg.connect(fresh_database_factory("confiture_spelling"), autocommit=True) as conn:
        conn.execute(
            "CREATE SCHEMA app; CREATE TYPE app.status AS ENUM ('a'); CREATE TYPE t AS (x int)"
        )
        spelled = [
            row[0]
            for row in conn.execute(
                "SELECT format_type(oid, NULL) FROM pg_type WHERE typname IN ('status', 't', '_status')"
                " ORDER BY typname"
            ).fetchall()
        ]
    assert spelled == ["app.status[]", "app.status", "t"]
    assert [_printed(s) for s in spelled] == spelled
