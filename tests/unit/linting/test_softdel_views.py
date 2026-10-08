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


# A key equality to a *view* that filters the table carries the test too (#662),
# measured on PostgreSQL 18.4: tombstoning rows of tb_item gives the same output as
# deleting them.
ITEMS = """CREATE TABLE app.tb_item (pk_item BIGINT PRIMARY KEY, id UUID UNIQUE, data JSONB,
    fk_order BIGINT, deleted_at TIMESTAMPTZ);
CREATE VIEW app.v_item AS
  SELECT i.id, i.data FROM app.tb_item i WHERE i.deleted_at IS NULL;
"""


@pytest.mark.parametrize(
    ("view", "reported"),
    [
        (
            "CREATE VIEW app.v_items_by_order AS SELECT o.pk_order, jsonb_agg(vi.data) AS items "
            "FROM app.v_item vi JOIN app.tb_item i ON vi.id = i.id "
            "JOIN app.tb_order o ON i.fk_order = o.pk_order AND o.deleted_at IS NULL "
            "GROUP BY o.pk_order;",
            [],
        ),
        (
            "CREATE VIEW app.v_two AS SELECT vi.id FROM app.v_item vi;\n"
            "CREATE VIEW app.v AS SELECT i.data FROM app.v_two w "
            "JOIN app.tb_item i ON i.id = w.id;",
            [],
        ),
        (
            "CREATE VIEW app.v_all AS SELECT i.id FROM app.tb_item i;\n"
            "CREATE VIEW app.v AS SELECT i.data FROM app.v_all a JOIN app.tb_item i ON i.id = a.id;",
            ["app.v", "app.v_all"],
        ),
        (
            "CREATE VIEW app.v_data AS SELECT i.data AS id FROM app.tb_item i "
            "WHERE i.deleted_at IS NULL;\n"
            "CREATE VIEW app.v AS SELECT i.data FROM app.v_data d JOIN app.tb_item i ON i.id = d.id;",
            ["app.v"],
        ),
        (
            "CREATE VIEW app.v AS SELECT i.data FROM app.tb_item i "
            "LEFT JOIN app.v_item vi ON vi.id = i.id;",
            ["app.v"],
        ),
    ],
    ids=["issue", "view-over-view", "view-not-filtered", "not-the-key", "left-join-preserved-side"],
)
def test_a_key_equality_with_a_filtering_view_carries_its_test(
    tmp_path: Path, view: str, reported: list[str]
) -> None:
    assert _reported(tmp_path, ITEMS + view + "\n") == reported


# A joined relation whose rows reach nothing is read without effect (#662), measured on
# PostgreSQL 18.4: with GROUP BY or DISTINCT collapsing the rows it multiplies, and no
# column of it selected, aggregated or tested, tombstoning its rows changes nothing.
CATALOG = """CREATE AGGREGATE app.my_count (uuid) (SFUNC = int8inc_any, STYPE = int8);
CREATE TABLE app.tb_vendor (pk_vendor BIGINT PRIMARY KEY, id UUID, name TEXT,
    deleted_at TIMESTAMPTZ);
CREATE TABLE app.tb_product (pk_product BIGINT PRIMARY KEY, fk_vendor BIGINT, deleted_at TIMESTAMPTZ);
"""
VENDOR_JOINS = (
    "FROM app.tb_vendor v "
    "LEFT JOIN app.tb_product p ON p.fk_vendor = v.pk_vendor "
    "LEFT JOIN app.tb_order_line l ON l.fk_order = p.pk_product "
)


@pytest.mark.parametrize(
    ("view", "reported"),
    [
        (
            f"SELECT v.pk_vendor, v.id, v.name {VENDOR_JOINS}"
            "WHERE v.deleted_at IS NULL GROUP BY v.pk_vendor, v.id, v.name",
            [],
        ),
        (f"SELECT DISTINCT v.pk_vendor {VENDOR_JOINS}WHERE v.deleted_at IS NULL", []),
        (
            f"SELECT v.pk_vendor, max(v.name), count(DISTINCT v.id) {VENDOR_JOINS}"
            "WHERE v.deleted_at IS NULL GROUP BY v.pk_vendor",
            [],
        ),
        (
            f"SELECT v.pk_vendor, count(*) {VENDOR_JOINS}"
            "WHERE v.deleted_at IS NULL GROUP BY v.pk_vendor",
            ["(l)", "(p)"],
        ),
        (
            f"SELECT v.pk_vendor, jsonb_build_object('name', lower(v.name)) {VENDOR_JOINS}"
            "WHERE v.deleted_at IS NULL GROUP BY v.pk_vendor, v.name",
            [],
        ),
        (
            "SELECT v.pk_vendor, jsonb_build_object('n', jsonb_agg(v.name)) "
            f"{VENDOR_JOINS}WHERE v.deleted_at IS NULL GROUP BY v.pk_vendor",
            ["(l)", "(p)"],
        ),
        (
            f"SELECT v.pk_vendor, app.my_count(v.id) {VENDOR_JOINS}"
            "WHERE v.deleted_at IS NULL GROUP BY v.pk_vendor",
            ["(l)", "(p)"],
        ),
        (
            f"SELECT v.pk_vendor, row_number() OVER () {VENDOR_JOINS}"
            "WHERE v.deleted_at IS NULL GROUP BY v.pk_vendor",
            ["(l)", "(p)"],
        ),
        (f"SELECT v.pk_vendor {VENDOR_JOINS}WHERE v.deleted_at IS NULL", ["(l)", "(p)"]),
        (
            "SELECT p.pk_product FROM app.tb_product p "
            "LEFT JOIN app.tb_vendor v ON v.pk_vendor = p.fk_vendor "
            "LEFT JOIN app.tb_order o ON o.pk_order = v.pk_vendor "
            "WHERE p.deleted_at IS NULL",
            [],
        ),
        (
            "SELECT p.pk_product FROM app.tb_product p "
            "LEFT JOIN app.tb_vendor v ON v.pk_vendor = p.fk_vendor "
            "LEFT JOIN app.tb_order_line l ON l.fk_order = v.pk_vendor "
            "WHERE p.deleted_at IS NULL",
            ["(l)", "(v)"],
        ),
        (
            f"SELECT v.pk_vendor, max(p.pk_product) {VENDOR_JOINS}"
            "WHERE v.deleted_at IS NULL GROUP BY v.pk_vendor",
            ["(p)"],
        ),
        (
            f"SELECT v.pk_vendor {VENDOR_JOINS}"
            "WHERE v.deleted_at IS NULL AND l.qty > 0 GROUP BY v.pk_vendor",
            ["(l)", "(p)"],
        ),
        (
            "SELECT v.pk_vendor FROM app.tb_vendor v "
            "JOIN app.tb_product p ON p.fk_vendor = v.pk_vendor "
            "WHERE v.deleted_at IS NULL GROUP BY v.pk_vendor",
            ["(p)"],
        ),
        (
            f"SELECT v.pk_vendor {VENDOR_JOINS}"
            "WHERE v.deleted_at IS NULL GROUP BY v.pk_vendor HAVING count(l.pk) > 0",
            ["(l)", "(p)"],
        ),
        (
            f"SELECT v.pk_vendor, p {VENDOR_JOINS}"
            "WHERE v.deleted_at IS NULL GROUP BY v.pk_vendor, p",
            ["(p)"],
        ),
    ],
    ids=[
        "issue",
        "distinct",
        "duplicate-insensitive-aggregates",
        "count-star",
        "scalar-calls",
        "aggregate-inside-a-call",
        "the-tree-s-own-aggregate",
        "window-function",
        "no-grouping",
        "joined-on-its-key",
        "a-key-join-read-by-one-that-multiplies",
        "aggregates-its-column",
        "tested-in-where",
        "inner-join",
        "having",
        "whole-row",
    ],
)
def test_a_join_whose_rows_reach_nothing_is_read_without_effect(
    tmp_path: Path, view: str, reported: list[str]
) -> None:
    report = _lint(
        tmp_path, TABLES + CATALOG + f"CREATE VIEW app.v AS {view};\n", check_softdel_views=True
    )
    found = sorted(
        "(" + v.message.split(") and never")[0].rsplit("(", 1)[1] + ")"
        for v in _found(report, SELECT)
    )
    assert found == reported
