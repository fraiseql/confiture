"""The TVIEW read graph: every view, matview and TVIEW the tree keeps, and its chain.

A TVIEW's chain is what pg_tviews follows from it: the plain views its query reads,
transitively, and — for the rules that read function bodies — the routines they
call. It stops at a materialized view and at another TVIEW, which store their rows.
"""

from confiture.core.linting.inventory import build_inventory
from confiture.core.linting.tview_reads import ReadGraph
from confiture.core.sql_lexer import parse_file

_TABLES = (
    "CREATE TABLE tb_category (pk_category bigint PRIMARY KEY, fk_parent bigint, path text);\n"
    "CREATE TABLE tb_item (pk_item bigint PRIMARY KEY, fk_category bigint);\n"
)
_VIEWS = (
    "CREATE VIEW v_category_path AS SELECT pk_category, path FROM tb_category;\n"
    "CREATE VIEW v_item_def AS\n"
    "SELECT i.pk_item, c.path FROM tb_item i JOIN v_category_path c\n"
    "  ON c.pk_category = i.fk_category;\n"
)


def _graph(*texts: str) -> ReadGraph:
    files = []
    base = 0
    for at, text in enumerate(texts):
        files.append(parse_file(text, f"{at:03}.sql", base))
        base += len(text) + 1
    return ReadGraph.read(files, build_inventory(files))


def _chains(graph: ReadGraph, *, routines: bool = False) -> dict[str, list[list[str]]]:
    return {
        target.obj.qualified: [
            [step.obj.qualified for step in path]
            for _holder, path in graph.chain(target, routines=routines)
        ]
        for target in graph.targets
        if target.family == "tview"
    }


def test_a_tview_s_chain_follows_plain_views_with_the_path_to_each() -> None:
    graph = _graph(
        _TABLES, _VIEWS, "CREATE TABLE tv_item AS SELECT pk_item, path FROM v_item_def;\n"
    )
    assert _chains(graph) == {"tv_item": [[], ["v_item_def"], ["v_item_def", "v_category_path"]]}


def test_a_tview_written_as_a_call_has_the_same_chain() -> None:
    graph = _graph(
        _TABLES,
        _VIEWS,
        "SELECT tviews.pg_tviews_create_or_replace('tv_item', $$\n"
        "  SELECT pk_item, path FROM v_item_def $$);\n",
    )
    (target,) = [t for t in graph.targets if t.family == "tview"]
    assert target.spelled_as_call
    assert _chains(graph) == {"tv_item": [[], ["v_item_def"], ["v_item_def", "v_category_path"]]}


def test_a_chain_stops_at_a_matview_and_at_another_tview() -> None:
    graph = _graph(
        _TABLES,
        _VIEWS,
        "CREATE MATERIALIZED VIEW mv_item AS SELECT pk_item, path FROM v_item_def;\n"
        "CREATE TABLE tv_inner AS SELECT pk_item, path FROM v_item_def;\n"
        "CREATE TABLE tv_outer AS SELECT m.pk_item, m.path FROM mv_item m\n"
        "  JOIN tv_inner t ON t.pk_item = m.pk_item;\n",
    )
    assert _chains(graph)["tv_outer"] == [[]]


def test_routine_edges_are_followed_only_when_asked() -> None:
    graph = _graph(
        _TABLES,
        "CREATE FUNCTION f_path(p bigint) RETURNS text LANGUAGE sql STABLE AS $$\n"
        "  SELECT path FROM v_category_path WHERE pk_category = p $$;\n",
        _VIEWS,
        "CREATE TABLE tv_item AS SELECT pk_item, f_path(pk_item) AS path FROM tb_item;\n",
    )
    assert _chains(graph) == {"tv_item": [[]]}
    assert _chains(graph, routines=True) == {
        "tv_item": [[], ["f_path"], ["f_path", "v_category_path"]]
    }


def test_each_holder_keeps_its_query_and_where_its_nodes_are() -> None:
    graph = _graph(
        _TABLES,
        _VIEWS,
        "SELECT tviews.pg_tviews_create_or_replace('tv_item', $$\n"
        "  SELECT pk_item,\n"
        "         path FROM v_item_def $$);\n",
    )
    (target,) = [t for t in graph.targets if t.family == "tview"]
    ((query,),) = [h.queries for h, _ in graph.chain(target) if h.obj.qualified == "tv_item"]
    from confiture.core.ddl_walk import walk_nodes

    (path_ref,) = [
        n
        for n in walk_nodes(query.root)
        if type(n).__name__ == "ColumnRef" and n.fields[-1].sval == "path"
    ]
    assert (query.file, query.line_at(path_ref.location)) == ("002.sql", 3)


def test_a_query_that_does_not_parse_is_an_unread_holder() -> None:
    graph = _graph(
        _TABLES, "SELECT tviews.pg_tviews_create_or_replace('tv_item', $$ SELEKT 1 $$);\n"
    )
    assert graph.unread(graph.targets) == {"tv_item (its query does not parse)"}
