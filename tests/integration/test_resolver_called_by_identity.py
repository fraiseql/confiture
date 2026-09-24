"""Level 4 runs a resolver PostgreSQL knows by a quoted, mixed-case name (#375).

``SELECT Fn_resolve_Widget()`` folds to ``fn_resolve_widget``, which does not
exist; only the quoted identity calls the routine the DDL created. Level 4
calls it inside a savepoint, so the row it writes is gone afterwards.
"""

from __future__ import annotations

from pathlib import Path

import psycopg

from confiture.core.schema_sources import read_schema
from confiture.core.seed.validation.prep_seed.level_4_runtime import Level4RuntimeValidator
from confiture.core.seed.validation.prep_seed.resolvers import find_resolvers

DDL = """\
CREATE TABLE tb_widget (id INT);
CREATE FUNCTION "Fn_resolve_Widget"() RETURNS void LANGUAGE sql AS $$
    INSERT INTO tb_widget VALUES (1);
$$;
"""


def test_a_quoted_mixed_case_resolver_runs(
    clean_test_db: psycopg.Connection, tmp_path: Path
) -> None:
    clean_test_db.execute(DDL)
    (tmp_path / "widget.sql").write_text(DDL)
    (resolver,) = find_resolvers(read_schema(tmp_path), catalog_schema="catalog")

    assert Level4RuntimeValidator().dry_run_resolution(resolver, clean_test_db) == []
    assert clean_test_db.execute("SELECT count(*) FROM tb_widget").fetchone() == (0,)
