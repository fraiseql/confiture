"""The seed reader names every table a statement writes, whether or not it reads the rows (#743).

A table a seed file populates is in ``seed drift``'s scope however the file writes
it. A statement whose rows the reader cannot see (``INSERT … SELECT``, a
data-modifying CTE, ``UPDATE``, ``MERGE``) still says which table it writes, so the
scope never shrinks in silence.
"""

from confiture.core.schema_model import RelationName
from confiture.core.seed.validation.prep_seed.seed_rows import read_seed_statements


def _unread_targets(sql: str) -> list[RelationName | None]:
    return [u.relation for u in read_seed_statements(sql).unread]


def test_insert_select_names_its_target() -> None:
    sql = "INSERT INTO catalog.tb_unit (id) SELECT gen_random_uuid();\n"

    assert _unread_targets(sql) == [RelationName("catalog", "tb_unit")]


def test_an_unqualified_insert_select_target() -> None:
    assert _unread_targets("INSERT INTO tb_unit SELECT 1;\n") == [RelationName(None, "tb_unit")]


def test_insert_default_values_names_its_target() -> None:
    assert _unread_targets("INSERT INTO app.tb_x DEFAULT VALUES;\n") == [
        RelationName("app", "tb_x")
    ]


def test_a_writable_cte_is_no_longer_a_silent_select() -> None:
    sql = (
        "WITH a AS (INSERT INTO app.tb_a VALUES (1) RETURNING 1),\n"
        "     b AS (INSERT INTO app.tb_b VALUES (2) RETURNING 1)\n"
        "SELECT * FROM a, b;\n"
    )

    assert _unread_targets(sql) == [RelationName("app", "tb_a"), RelationName("app", "tb_b")]


def test_a_cte_insert_beside_a_read_insert() -> None:
    sql = "WITH a AS (INSERT INTO app.tb_a VALUES (1) RETURNING 1)\nINSERT INTO app.tb_b VALUES (2);\n"
    read = read_seed_statements(sql)

    assert [w.relation for w in read.writes] == [RelationName("app", "tb_b")]
    assert [u.relation for u in read.unread] == [RelationName("app", "tb_a")]


def test_update_and_merge_name_their_targets() -> None:
    sql = (
        "UPDATE app.tb_a SET x = 1;\n"
        "MERGE INTO app.tb_b t USING (VALUES (1)) s (id) ON t.id = s.id\n"
        "WHEN NOT MATCHED THEN INSERT (id) VALUES (s.id);\n"
    )

    assert _unread_targets(sql) == [RelationName("app", "tb_a"), RelationName("app", "tb_b")]


def test_a_delete_populates_nothing_and_stays_unreported() -> None:
    """DELETE writes no row: no value to check, and no table it fills."""
    read = read_seed_statements("DELETE FROM app.tb_a;\n")

    assert (read.unread, read.targets()) == ((), ())


def test_targets_lists_every_written_table_once_in_order() -> None:
    sql = (
        "INSERT INTO app.tb_b VALUES (1);\n"
        "INSERT INTO app.tb_a SELECT 1;\n"
        "INSERT INTO app.tb_b VALUES (2);\n"
        "COPY app.tb_c (id) FROM stdin;\n1\n\\.\n"
    )

    assert read_seed_statements(sql).targets() == (
        RelationName("app", "tb_b"),
        RelationName("app", "tb_a"),
        RelationName("app", "tb_c"),
    )


def test_a_select_calling_a_loader_is_a_named_limit() -> None:
    """A function that writes tables is invisible to a static reader; it is not in scope."""
    assert read_seed_statements("SELECT app.fn_load_units();\n").targets() == ()


def test_a_copy_from_a_file_names_its_table() -> None:
    read = read_seed_statements("COPY app.tb_a (k) FROM '/data/a.csv' WITH (FORMAT csv);\n")

    [unread] = read.unread
    assert (unread.relation, unread.inserts, unread.columns) == (
        RelationName("app", "tb_a"),
        True,
        ("k",),
    )
