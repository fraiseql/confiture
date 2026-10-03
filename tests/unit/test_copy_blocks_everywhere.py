"""Every reader of a schema answers the same with or without a ``COPY … FROM stdin`` block (#561).

A ``confiture build`` bundle holds seed files, and a seed is often ``COPY … FROM
stdin`` with rows that are not SQL. PostgreSQL's parser rejects those rows, so a
reader that hands the text to pglast without blanking them first refuses a
bundle confiture itself wrote (``drift --schema``: SCHEMA_202) — or, worse,
answers as if the schema were empty. Each reader below is asked the same
question twice, once with the block and once without, and must answer alike.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from confiture.core import function_signature_drift
from confiture.core.differ import SchemaDiffer
from confiture.core.drift import parse_expected_schema
from confiture.core.schema_read import read_text
from confiture.platform import parse_schema

SCHEMA = """\
CREATE TABLE app.tb_item (id bigint PRIMARY KEY, label text NOT NULL);
CREATE FUNCTION app.fn_label(p_id bigint) RETURNS text LANGUAGE sql
    AS $$ SELECT label FROM app.tb_item WHERE id = p_id $$;
"""

COPY_BLOCK = """\
COPY app.tb_item (id, label) FROM stdin;
1\tO'Brien; DROP TABLE x
2\t{"a": 1}\t$$
\\.
"""

AFTER = "CREATE VIEW app.v_item AS SELECT id, label FROM app.tb_item;\n"

WITH_COPY = SCHEMA + COPY_BLOCK + AFTER
WITHOUT_COPY = SCHEMA + AFTER


def _wire(model: Any) -> str:
    return model.to_json()


READERS: dict[str, Callable[[str], Any]] = {
    "platform.parse_schema": lambda sql: _wire(parse_schema(sql)),
    "SchemaDiffer.parse_schema": lambda sql: [
        t.name for t in SchemaDiffer().parse_schema(sql).tables
    ],
    "drift.parse_expected_schema": lambda sql: _wire(parse_expected_schema(sql).model),
    "schema_read.read_text": lambda sql: _wire(read_text(sql).model),
    "function_signature_drift.declared_routines": lambda sql: [
        function_signature_drift.printed_signature(r)
        for r in function_signature_drift.declared_routines(sql)
    ],
    "function_signature_drift.replacing_definitions": lambda sql: dict(
        function_signature_drift.replacing_definitions(sql)
    ),
}


@pytest.mark.parametrize("reader", sorted(READERS))
def test_a_copy_block_changes_no_reader_s_answer(reader: str) -> None:
    read = READERS[reader]
    assert read(WITH_COPY) == read(WITHOUT_COPY)
