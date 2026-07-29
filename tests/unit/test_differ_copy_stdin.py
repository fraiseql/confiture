"""#194: ``SchemaDiffer.parse_schema`` must survive ``COPY … FROM stdin`` blocks.

``COPY table FROM stdin;`` followed by inline tab-separated rows and a ``\\.``
terminator is psql client protocol, not parseable SQL — pglast (PostgreSQL's
own grammar) rejects the data lines. Before this fix, one seed file using
inline COPY anywhere in a concatenated schema killed the entire pglast pass;
the sqlparse fallback then silently missed DDL (token limits), so
``migrate validate --require-migration`` reported "No DDL changes detected"
while blind. Observed in the wild: printoptim_backend's ``local`` env build
(18 MB, one ``COPY prep_seed.tb_generic_item FROM stdin`` block) made the
ship gate a permanent no-op.

The data lines are free-form text: they can contain semicolons, quotes, and
SQL-looking fragments, so they must be stripped as a block (COPY statement
through the ``\\.`` terminator), not statement-split.
"""

from __future__ import annotations

import logging

from confiture.core.differ import SchemaDiffer

COPY_BLOCK = """\
COPY prep_seed.tb_generic_item (id, identifier, fk_product_id) FROM stdin;
bd1ac132-8309-4f9b-961e-bd0be0de9e2d\t<generic|1b.cabinet><leasing|1-month>\t2a7ee336
deadbeef-0000-4f9b-961e-bd0be0de9e2e\tsemicolons; 'quotes' and CREATE TABLE noise\t2a7ee337
\\.
"""


def test_parse_schema_survives_copy_stdin_block() -> None:
    sql = (
        "CREATE TABLE before_copy (id INT PRIMARY KEY);\n"
        + COPY_BLOCK
        + "CREATE TABLE after_copy (id INT PRIMARY KEY, name TEXT);\n"
    )
    parsed = SchemaDiffer().parse_schema(sql)
    names = {t.name for t in parsed.tables}
    assert names == {"before_copy", "after_copy"}


def test_diff_detects_add_table_after_copy_stdin_block() -> None:
    base = "CREATE TABLE before_copy (id INT PRIMARY KEY);\n" + COPY_BLOCK
    target = base + "CREATE TABLE added_later (id INT PRIMARY KEY);\n"
    differ = SchemaDiffer()
    diff = differ.compare(base, target)
    assert any(c.type == "ADD_TABLE" and c.table == "added_later" for c in diff.changes)


def test_copy_without_inline_data_is_untouched() -> None:
    # COPY ... FROM '/path/file' is a normal statement pglast accepts; only
    # FROM stdin blocks carry inline data that needs stripping.
    sql = (
        "CREATE TABLE t1 (id INT);\n"
        "COPY t1 FROM '/tmp/data.csv' WITH (FORMAT csv);\n"
        "CREATE TABLE t2 (id INT);\n"
    )
    parsed = SchemaDiffer().parse_schema(sql)
    assert {t.name for t in parsed.tables} == {"t1", "t2"}


def test_pglast_fallback_warns_instead_of_degrading_silently(
    caplog,
) -> None:
    # Genuinely unparseable SQL still falls back to sqlparse, but must say so:
    # the silent fallback is what turned a blocking gate into a no-op.
    sql = "CREATE TABLE ok (id INT);\nTHIS IS NOT SQL AT ALL;\n"
    with caplog.at_level(logging.WARNING, logger="confiture.core.differ"):
        SchemaDiffer().parse_schema(sql)
    assert any("pglast" in rec.message and "sqlparse" in rec.message for rec in caplog.records)
