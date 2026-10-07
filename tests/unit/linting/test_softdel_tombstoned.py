"""``soft_delete: {tables: written}``: a table soft-deletes when the tree tombstones it (#640).

A tree where every table carries the audit columns has ``deleted_at`` on reference
tables nothing ever deletes; judging every table that *has* the column buried the
real findings under 112 on one tree. ``written`` judges a table only when some
statement writes a value other than ``NULL`` to its tombstone column — a routine
body, a ``LANGUAGE sql`` body or a statement of the tree, in every form PostgreSQL
updates a row with. What cannot be read is named in the rule's ``degraded`` status,
never taken as "does not write".
"""

from pathlib import Path

import pytest
from tests.unit.linting.test_softdel_keys import _found, _lint

from confiture.core.linting.inventory import build_inventory
from confiture.core.linting.tombstones import tombstoned
from confiture.core.sql_lexer import parse_file

TABLES = """CREATE SCHEMA app;
CREATE TABLE app.tb_order (pk BIGINT PRIMARY KEY, code TEXT UNIQUE, deleted_at TIMESTAMPTZ);
CREATE TABLE app.tb_language (pk BIGINT PRIMARY KEY, code TEXT UNIQUE, deleted_at TIMESTAMPTZ);
"""


def _written(sql: str) -> set[str]:
    parsed = parse_file(TABLES + sql, "schema.sql")
    found = tombstoned(build_inventory([parsed]), [parsed], "deleted_at")
    return {name for _schema, name in found.tables}


def _function(body: str, language: str = "plpgsql") -> str:
    if language == "sql":
        return f"CREATE FUNCTION app.fn_x(p bigint) RETURNS void LANGUAGE sql AS $$ {body} $$;\n"
    return (
        "CREATE FUNCTION app.fn_x(p bigint) RETURNS void LANGUAGE plpgsql AS $$\n"
        f"DECLARE v_now timestamptz := now();\nBEGIN\n  {body}\nEND;\n$$;\n"
    )


@pytest.mark.parametrize(
    "sql",
    [
        _function("UPDATE app.tb_order SET deleted_at = now() WHERE pk = p;"),
        _function("UPDATE app.tb_order SET deleted_at = v_now WHERE pk = p;"),
        _function("UPDATE app.tb_order o SET deleted_at = CURRENT_TIMESTAMP WHERE o.pk = p;"),
        _function("UPDATE app.tb_order SET deleted_at = now() WHERE pk = p", language="sql"),
        _function("UPDATE tb_order SET deleted_at = now() WHERE pk = p;"),
        _function(
            "WITH gone AS (UPDATE app.tb_order SET deleted_at = now() WHERE pk = p RETURNING pk) "
            "SELECT count(*) INTO p FROM gone;"
        ),
        _function("UPDATE app.tb_order SET (deleted_at, code) = (now(), NULL) WHERE pk = p;"),
        _function(
            "UPDATE app.tb_order o SET deleted_at = now() FROM app.tb_language l WHERE l.pk = o.pk;"
        ),
        _function(
            "INSERT INTO app.tb_order (pk) VALUES (p) "
            "ON CONFLICT (pk) DO UPDATE SET deleted_at = now();"
        ),
        _function(
            "MERGE INTO app.tb_order o USING app.tb_language l ON l.pk = o.pk "
            "WHEN MATCHED THEN UPDATE SET deleted_at = now();"
        ),
        "UPDATE app.tb_order SET deleted_at = now() WHERE code = 'x';\n",
        "CREATE RULE r_delete AS ON DELETE TO app.tb_order DO INSTEAD "
        "UPDATE app.tb_order SET deleted_at = now() WHERE pk = OLD.pk;\n",
    ],
)
def test_a_write_of_a_value_tombstones_the_table(sql: str) -> None:
    assert _written(sql) == {"tb_order"}


@pytest.mark.parametrize(
    "sql",
    [
        "",
        _function("UPDATE app.tb_order SET deleted_at = NULL WHERE pk = p;"),
        _function("UPDATE app.tb_order SET deleted_at = NULL::timestamptz WHERE pk = p;"),
        _function("UPDATE app.tb_order SET deleted_at = DEFAULT WHERE pk = p;"),
        _function("UPDATE app.tb_order SET code = 'x' WHERE deleted_at IS NULL;"),
    ],
)
def test_an_undelete_or_a_read_tombstones_nothing(sql: str) -> None:
    assert _written(sql) == set()


def test_an_update_without_only_writes_the_partitions() -> None:
    sql = (
        "CREATE TABLE app.tb_event (pk BIGINT, deleted_at TIMESTAMPTZ) PARTITION BY RANGE (pk);\n"
        "CREATE TABLE app.tb_event_1 PARTITION OF app.tb_event FOR VALUES FROM (0) TO (10);\n"
        + _function("UPDATE app.tb_event SET deleted_at = now() WHERE pk = p;")
    )
    assert _written(sql) == {"tb_event", "tb_event_1"}


def test_what_cannot_be_read_is_undecided() -> None:
    parsed = parse_file(
        TABLES + _function("EXECUTE format('UPDATE %I SET deleted_at = now()', 'tb_order');"),
        "schema.sql",
    )
    found = tombstoned(build_inventory([parsed]), [parsed], "deleted_at")
    assert found.tables == frozenset()
    (undecided,) = found.undecided
    assert "app.fn_x(bigint)" in undecided
    assert "EXECUTE" in undecided


WRITTEN = "soft_delete:\n  column: deleted_at\n  tables: written\n"
DELETES_ORDERS = _function("UPDATE app.tb_order SET deleted_at = now() WHERE pk = p;")


def test_written_judges_only_the_tables_the_tree_tombstones(tmp_path: Path) -> None:
    report = _lint(tmp_path, TABLES + DELETES_ORDERS, WRITTEN)
    assert [v.object_name for v in _found(report, "softdel_001")] == ["app.tb_order"]


def test_present_still_judges_every_table_with_the_column(tmp_path: Path) -> None:
    report = _lint(tmp_path, TABLES + DELETES_ORDERS)
    assert sorted(v.object_name for v in _found(report, "softdel_001")) == [
        "app.tb_language",
        "app.tb_order",
    ]


def test_exclude_drops_a_table_and_an_unmatched_entry_is_said(tmp_path: Path) -> None:
    yaml = "soft_delete:\n  column: deleted_at\n  exclude: [app.tb_language, app.tb_nothing]\n"
    report = _lint(tmp_path, TABLES, yaml)
    assert [v.object_name for v in _found(report, "softdel_001")] == ["app.tb_order"]
    assert any("app.tb_nothing" in (s.reason or "") for s in report.degraded)


def test_written_names_the_bodies_it_could_not_read(tmp_path: Path) -> None:
    sql = TABLES + _function("EXECUTE 'UPDATE app.tb_order SET deleted_at = now()';")
    report = _lint(tmp_path, sql, WRITTEN)
    assert _found(report, "softdel_001") == []
    reasons = [s.reason or "" for s in report.degraded if s.code == "softdel_001"]
    assert any("app.fn_x(bigint)" in r for r in reasons)
