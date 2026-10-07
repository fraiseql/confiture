"""``softdel_003``: a view over a soft-deleting table tests its tombstone (#632).

A deleted row stays in its table, so a view that reads the table and never tests the
tombstone column lists it, embeds it or counts it. The test is per *relation read*:
a view that filters its driving table and embeds a joined one unfiltered still
leaks. A reference counts when a qualification — ``WHERE``, ``JOIN … ON``,
``HAVING``, a sub-select's own — names the column through that read.
"""

from pathlib import Path

import pytest
from tests.unit.linting.test_softdel_keys import _found, _lint

TABLES = """CREATE SCHEMA app;
CREATE TABLE app.tb_order (pk_order BIGINT PRIMARY KEY, id UUID, deleted_at TIMESTAMPTZ);
CREATE TABLE app.tb_order_line (pk BIGINT PRIMARY KEY, id UUID, fk_order BIGINT, qty INT,
    deleted_at TIMESTAMPTZ);
CREATE TABLE app.tb_country (pk BIGINT PRIMARY KEY, name TEXT);
"""

SELECT = "softdel_003"


def _reported(tmp_path: Path, view: str, project: str | None = None) -> list[str]:
    kwargs = {"check_softdel_views": True}
    report = (
        _lint(tmp_path, TABLES + view, **kwargs)
        if project is None
        else _lint(tmp_path, TABLES + view, project, **kwargs)
    )
    return sorted(v.object_name for v in _found(report, SELECT))


ISSUE = """CREATE VIEW app.v_order AS
SELECT o.id,
       jsonb_build_object(
           'id', o.id,
           'lines', (SELECT jsonb_agg(jsonb_build_object('id', l.id, 'qty', l.qty))
                     FROM app.tb_order_line l
                     WHERE l.fk_order = o.pk_order)
       ) AS data
FROM app.tb_order o
WHERE o.deleted_at IS NULL;
"""


def test_the_issue_s_embed_is_reported_and_its_driving_table_is_not(tmp_path: Path) -> None:
    report = _lint(tmp_path, TABLES + ISSUE, check_softdel_views=True)
    (finding,) = _found(report, SELECT)
    assert finding.object_name == "app.v_order"
    assert "app.tb_order_line" in finding.message
    assert "(l)" in finding.message
    assert "inside" in (finding.suggested_fix or "")
    assert finding.line_number == 11


@pytest.mark.parametrize(
    ("view", "reported"),
    [
        ("CREATE VIEW app.v AS SELECT id FROM app.tb_order;", ["app.v"]),
        ("CREATE VIEW app.v AS SELECT id FROM app.tb_order WHERE deleted_at IS NULL;", []),
        (
            "CREATE VIEW app.v AS SELECT id FROM app.tb_order WHERE tb_order.deleted_at IS NULL;",
            [],
        ),
        ("CREATE VIEW app.v AS SELECT id, deleted_at FROM app.tb_order;", ["app.v"]),
        (
            "CREATE VIEW app.v AS SELECT o.id FROM app.tb_order o "
            "JOIN app.tb_order_line l ON l.fk_order = o.pk_order "
            "WHERE o.deleted_at IS NULL;",
            ["app.v"],
        ),
        (
            "CREATE VIEW app.v AS SELECT o.id, l.qty FROM app.tb_order o "
            "LEFT JOIN app.tb_order_line l ON l.fk_order = o.pk_order AND l.deleted_at IS NULL "
            "WHERE o.deleted_at IS NULL;",
            [],
        ),
        (
            "CREATE VIEW app.v AS WITH live AS (SELECT * FROM app.tb_order "
            "WHERE deleted_at IS NULL) SELECT id FROM live;",
            [],
        ),
        (
            "CREATE VIEW app.v AS SELECT x.id FROM (SELECT * FROM app.tb_order) x "
            "WHERE x.deleted_at IS NULL;",
            [],
        ),
        (
            "CREATE VIEW app.v AS SELECT o.id FROM app.tb_order o, LATERAL "
            "(SELECT count(*) FROM app.tb_order_line l WHERE l.fk_order = o.pk_order) n "
            "WHERE o.deleted_at IS NULL;",
            ["app.v"],
        ),
        (
            "CREATE VIEW app.v AS SELECT id FROM app.tb_order WHERE deleted_at IS NULL "
            "UNION ALL SELECT id FROM app.tb_order_line;",
            ["app.v"],
        ),
        (
            "CREATE VIEW app.v AS SELECT o.id FROM app.tb_order o WHERE o.deleted_at IS NULL "
            "AND NOT EXISTS (SELECT 1 FROM app.tb_order_line l WHERE l.fk_order = o.pk_order "
            "AND l.deleted_at IS NULL);",
            [],
        ),
        (
            "CREATE MATERIALIZED VIEW app.mv AS SELECT count(*) FROM app.tb_order;",
            ["app.mv"],
        ),
        ("CREATE VIEW app.v AS SELECT pk, name FROM app.tb_country;", []),
    ],
    ids=[
        "unfiltered",
        "filtered",
        "qualified-by-name",
        "target-list-is-no-test",
        "joined-unfiltered",
        "left-join-on",
        "cte",
        "wrapper-subquery",
        "lateral-unfiltered",
        "union-branch",
        "not-exists",
        "matview",
        "no-tombstone-column",
    ],
)
def test_each_read_of_a_soft_deleting_table_tests_its_tombstone(
    tmp_path: Path, view: str, reported: list[str]
) -> None:
    assert _reported(tmp_path, view + "\n") == reported


def test_a_self_join_tests_each_read(tmp_path: Path) -> None:
    view = (
        "CREATE VIEW app.v AS SELECT a.id FROM app.tb_order a JOIN app.tb_order b "
        "ON b.id = a.id WHERE a.deleted_at IS NULL;\n"
    )
    report = _lint(tmp_path, TABLES + view, check_softdel_views=True)
    (finding,) = _found(report, SELECT)
    assert "(b)" in finding.message


def test_the_waiver_covers_the_tables_it_names(tmp_path: Path) -> None:
    waived = (
        "-- confiture:softdel-keeps-deleted tb_order_line: resolves ids of deleted lines too\n"
        "CREATE VIEW app.v AS SELECT l.id FROM app.tb_order_line l;\n"
    )
    other = (
        "-- confiture:softdel-keeps-deleted app.tb_order_line: an audit trail\n"
        "CREATE VIEW app.w AS SELECT l.id FROM app.tb_order_line l JOIN app.tb_order o "
        "ON o.pk_order = l.fk_order;\n"
    )
    report = _lint(tmp_path, TABLES + waived + other, check_softdel_views=True)
    assert [(v.object_name, "app.tb_order" in v.message) for v in _found(report, SELECT)] == [
        ("app.w", True)
    ]


def test_under_written_only_tombstoned_tables_are_judged(tmp_path: Path) -> None:
    project = "soft_delete:\n  column: deleted_at\n  tables: written\n"
    deletes = (
        "CREATE FUNCTION app.fn_delete(p bigint) RETURNS void LANGUAGE sql AS "
        "$$ UPDATE app.tb_order SET deleted_at = now() WHERE pk_order = p $$;\n"
    )
    view = (
        "CREATE VIEW app.v AS SELECT o.id FROM app.tb_order o JOIN app.tb_order_line l ON true;\n"
    )
    report = _lint(tmp_path, TABLES + deletes + view, project, check_softdel_views=True)
    (finding,) = _found(report, SELECT)
    assert "app.tb_order " in finding.message + " "
    assert "tb_order_line" not in finding.message


def test_a_view_replaced_later_is_judged_as_it_ends(tmp_path: Path) -> None:
    views = (
        "CREATE VIEW app.v AS SELECT id FROM app.tb_order;\n"
        "CREATE OR REPLACE VIEW app.v AS SELECT id FROM app.tb_order WHERE deleted_at IS NULL;\n"
    )
    assert _reported(tmp_path, views) == []


# A key equality carries a test across reads of one table (#650), measured on
# PostgreSQL 18.4: a row joined on its primary key to a live row of the same table is
# that live row; a LEFT JOIN's ON restricts only its nullable side.
LIVE = "(SELECT pk_order FROM app.tb_order WHERE deleted_at IS NULL)"


@pytest.mark.parametrize(
    ("view", "reported"),
    [
        (
            f"CREATE VIEW app.v AS SELECT o.id FROM {LIVE} live "
            "JOIN app.tb_order o ON o.pk_order = live.pk_order;",
            [],
        ),
        (
            "CREATE VIEW app.v AS WITH RECURSIVE tree AS ("
            "SELECT pk_order FROM app.tb_order WHERE deleted_at IS NULL "
            "UNION ALL SELECT c.pk_order FROM app.tb_order c JOIN tree t "
            "ON c.pk_order = t.pk_order + 1 WHERE c.deleted_at IS NULL) "
            "SELECT o.id FROM tree JOIN app.tb_order o ON tree.pk_order = o.pk_order;",
            [],
        ),
        (
            "CREATE VIEW app.v AS WITH agg AS (SELECT o.pk_order AS fk_order, count(*) AS n "
            "FROM app.tb_order o GROUP BY o.pk_order) "
            "SELECT o.id, agg.n FROM app.tb_order o LEFT JOIN agg ON o.pk_order = agg.fk_order "
            "WHERE o.deleted_at IS NULL;",
            [],
        ),
        (
            f"CREATE VIEW app.v AS SELECT o.id FROM app.tb_order o, {LIVE} live "
            "WHERE live.pk_order = o.pk_order;",
            [],
        ),
        (
            "CREATE VIEW app.v AS SELECT o.id FROM app.tb_order o WHERE o.deleted_at IS NULL "
            "AND EXISTS (SELECT 1 FROM app.tb_order o2 WHERE o2.pk_order = o.pk_order);",
            [],
        ),
        (
            f"CREATE VIEW app.v AS SELECT o.id FROM app.tb_order o "
            f"LEFT JOIN {LIVE} live ON live.pk_order = o.pk_order;",
            ["app.v"],
        ),
        (
            f"CREATE VIEW app.v AS SELECT o.id FROM {LIVE} live "
            "JOIN app.tb_order o ON o.id = live.pk_order::text::uuid;",
            ["app.v"],
        ),
        (
            "CREATE VIEW app.v AS SELECT o.id FROM (SELECT id FROM app.tb_order "
            "WHERE deleted_at IS NULL) live JOIN app.tb_order o ON o.id = live.id;",
            ["app.v"],
        ),
        (
            f"CREATE VIEW app.v AS SELECT o.id FROM {LIVE} live "
            "JOIN app.tb_order o ON o.pk_order = live.pk_order OR o.id IS NULL;",
            ["app.v"],
        ),
        (
            "CREATE VIEW app.v AS SELECT o.id FROM app.tb_order live "
            "JOIN app.tb_order o ON o.pk_order = live.pk_order;",
            ["app.v", "app.v"],
        ),
        (
            "CREATE VIEW app.v AS SELECT l.id FROM app.tb_order_line l "
            "JOIN app.tb_order_line live ON live.fk_order = l.fk_order "
            "WHERE live.deleted_at IS NULL;",
            ["app.v"],
        ),
        (
            "CREATE VIEW app.v AS WITH agg AS (SELECT l.fk_order, count(*) AS n "
            "FROM app.tb_order o LEFT JOIN app.tb_order_line l "
            "ON o.pk_order = l.fk_order AND l.deleted_at IS NULL GROUP BY l.fk_order) "
            "SELECT o.id, agg.n FROM app.tb_order o LEFT JOIN agg ON o.pk_order = agg.fk_order "
            "WHERE o.deleted_at IS NULL;",
            [],
        ),
        (
            "CREATE VIEW app.v AS WITH agg AS (SELECT l.fk_order, count(*) AS n "
            "FROM app.tb_order o LEFT JOIN app.tb_order_line l "
            "ON o.pk_order = l.qty AND l.deleted_at IS NULL GROUP BY l.fk_order) "
            "SELECT o.id, agg.n FROM app.tb_order o LEFT JOIN agg ON o.pk_order = agg.fk_order "
            "WHERE o.deleted_at IS NULL;",
            ["app.v"],
        ),
    ],
    ids=[
        "key-join-to-live-subquery",
        "key-join-to-recursive-cte",
        "aggregate-cte-grouped-by-key",
        "key-equality-in-where",
        "correlated-exists-on-key",
        "left-join-preserved-side",
        "not-a-plain-column",
        "not-a-key",
        "under-or",
        "neither-tested",
        "equal-but-not-unique",
        "aggregate-cte-grouped-by-the-joined-key",
        "aggregate-cte-grouped-by-an-unjoined-column",
    ],
)
def test_a_key_equality_with_a_live_read_of_the_table_carries_its_test(
    tmp_path: Path, view: str, reported: list[str]
) -> None:
    assert _reported(tmp_path, view + "\n") == reported


def test_an_anti_join_hides_live_rows_and_says_so(tmp_path: Path) -> None:
    view = (
        "CREATE VIEW app.v AS SELECT c.pk FROM app.tb_country c "
        "LEFT JOIN app.tb_order o ON o.pk_order = c.pk WHERE o.pk_order IS NULL;\n"
    )
    report = _lint(tmp_path, TABLES + view, check_softdel_views=True)
    (finding,) = _found(report, SELECT)
    assert "hides" in finding.message
    assert "shows the rows deleted" not in finding.message
    assert "ON clause" in (finding.suggested_fix or "")
