"""`missing_from_db` lists the functions the database has not got, and no others.

Measured on a **pristine** database built from the live-drift corpus, whose three
routines all exist:

```
default flags:    missing_from_db = ["core.fn_touch()",
                                     "core.fn_seen(timestamp with time zone)",
                                     "core.fn_gone(bigint)"]
--schemas core:   missing_from_db = ["core.fn_touch()"]
```

Two independent causes, both structural:

* **scope** — `--check-signatures` defaulted to `--schemas public` while
  `--check-live-drift` reads the schemas out of the DDL, so every routine outside
  `public` was reported missing, always;
* **trigger functions** — `FunctionIntrospector` filters
  `pg_get_function_result(p.oid) IS DISTINCT FROM 'trigger'` unless asked
  otherwise, and `LiveFunctionCatalog` never asked. The *source* parser has no
  such filter, so a `RETURNS TRIGGER` function was permanently missing from a
  database that has it.

A flag that fails a deploy on `missing_from_db` is unshippable on top of that.
The de-noising is the work; the flag is the last commit.
"""

from __future__ import annotations

from pathlib import Path

import psycopg
import pytest

from confiture.core.function_signature_drift import FunctionSignatureDriftDetector
from confiture.core.function_signature_parser import FunctionSignatureParser
from confiture.core.live_function_catalog import LiveFunctionCatalog
from confiture.core.psql_applier import apply_sql_via_psql

CORPUS = Path(__file__).resolve().parents[1] / "fixtures" / "live_drift_corpus"

#: The corpus files that make a schema with routines in it.
FILES = ("010_schema.sql", "020_tables.sql", "030_types.sql", "050_objects.sql")


def corpus_sql() -> str:
    return "\n".join((CORPUS / name).read_text(encoding="utf-8") for name in FILES)


@pytest.fixture
def routines_database(fresh_database: str) -> str:
    apply_sql_via_psql(fresh_database, sql=corpus_sql())
    return fresh_database


def report(url: str, schemas: list[str]):
    source = FunctionSignatureParser().parse(corpus_sql())
    with psycopg.connect(url) as conn:
        live = LiveFunctionCatalog(conn).get_signatures(schemas)
    return FunctionSignatureDriftDetector().compare(source, live)


def test_a_pristine_database_is_missing_nothing(routines_database: str) -> None:
    """Every routine the corpus declares exists, so nothing is undeployed."""
    assert report(routines_database, ["core"]).missing_from_db == []


def test_a_trigger_function_is_on_both_sides(routines_database: str) -> None:
    """`core.fn_touch()` returns trigger, and the live side used to filter it out."""
    with psycopg.connect(routines_database) as conn:
        live = LiveFunctionCatalog(conn).get_signatures(["core"])
    assert "fn_touch" in {signature.name for signature in live}


def test_a_procedure_is_on_both_sides(routines_database: str) -> None:
    """`prokind IN ('f','p')` — a procedure is a routine the source declares too."""
    with psycopg.connect(routines_database) as conn:
        live = LiveFunctionCatalog(conn).get_signatures(["core"])
    assert "pr_noop" in {signature.name for signature in live}


def test_a_genuinely_undeployed_function_is_reported(routines_database: str) -> None:
    """The point of the channel: a routine the source declares and the database lacks."""
    with psycopg.connect(routines_database) as conn:
        conn.execute("DROP FUNCTION core.fn_gone(bigint)")
        conn.commit()
    assert report(routines_database, ["core"]).missing_from_db == ["core.fn_gone(bigint)"]


def test_no_stale_overload_is_invented(routines_database: str) -> None:
    """Widening the live side must not suggest a single new `DROP FUNCTION`.

    `stale_overloads` drives `remediation_sql`, which is **destructive**:
    "suppressing a genuine overload is non-destructive, whereas dropping a live
    function is catastrophic."
    """
    assert report(routines_database, ["core"]).stale_overloads == []
