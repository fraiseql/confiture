"""How a view walks a pg_treekey tree (#676): ``treekey_001`` and ``treekey_002``.

pg_tviews follows a view's dependencies to decide which TVIEW rows a write
refreshes, and a ``WITH RECURSIVE`` over the parent key or an ``unnest`` of the
path is a spelling it cannot always follow. The fixtures are pg_treekey's own,
from ``src/lint.rs`` and ``tests/pg_regress/sql/60_lint_views.sql``, so the rule
and ``treekey.lint_views()`` agree.
"""

import pytest

from confiture.core.linting.inventory import build_inventory
from confiture.core.linting.tree_walks import TreeWalkFinding, tree_walk_findings
from confiture.core.sql_lexer import parse_file

_TREES = """CREATE TABLE catalog.tb_item_category (pk_item_category bigint PRIMARY KEY,
    fk_parent_item_category bigint, name text, path ltree, tags text[], path_of_names text);
CREATE TABLE catalog.tb_industry (pk_industry bigint PRIMARY KEY,
    fk_parent_industry bigint, name text, path ltree);
CREATE TABLE tenant.tb_location (pk_location bigint PRIMARY KEY,
    fk_parent_location bigint, name text, path ltree);
CREATE TABLE tenant.tb_organizational_unit (pk_organizational_unit bigint PRIMARY KEY,
    fk_parent_organizational_unit bigint, name text, path ltree);
SELECT treekey.manage_path('catalog.tb_item_category', 'pk_item_category',
    'fk_parent_item_category');
SELECT treekey.manage_path('catalog.tb_industry', 'pk_industry', 'fk_parent_industry');
SELECT treekey.manage_path('tenant.tb_location', 'pk_location', 'fk_parent_location');
SELECT treekey.manage_path('tenant.tb_organizational_unit', 'pk_organizational_unit',
    'fk_parent_organizational_unit');
"""


def _findings(*texts: str) -> list[TreeWalkFinding]:
    files = []
    base = 0
    for at, text in enumerate(texts):
        files.append(parse_file(text, f"{at:03}.sql", base))
        base += len(text) + 1
    return tree_walk_findings(files, build_inventory(files))


def _found(view: str) -> list[str]:
    return [f.code for f in _findings(_TREES, view)]


# -- src/lint.rs ---------------------------------------------------------------


def test_a_recursive_cte_over_the_parent_fk_on_a_plain_view_is_not_treekey_001() -> None:
    """No TVIEW reads it, so pg_tviews never sees it."""
    assert (
        _found(
            "CREATE VIEW v_category_names AS WITH RECURSIVE names(pk_item_category, name) AS (\n"
            "  SELECT c.pk_item_category, c.name::text AS name\n"
            "    FROM catalog.tb_item_category c\n"
            "   WHERE c.fk_parent_item_category IS NULL\n"
            "  UNION ALL\n"
            "  SELECT c.pk_item_category, (n.name || ' > '::text) || c.name::text\n"
            "    FROM catalog.tb_item_category c\n"
            "      JOIN names n ON c.fk_parent_item_category = n.pk_item_category\n"
            ")\n"
            "SELECT pk_item_category, name FROM names;\n"
        )
        == []
    )


def test_a_recursive_cte_over_something_else_is_fine() -> None:
    assert (
        _found(
            "CREATE VIEW v_series AS WITH RECURSIVE n(i) AS (\n"
            "  SELECT 1\n"
            "  UNION ALL\n"
            "  SELECT n_1.i + 1 FROM n n_1 WHERE n_1.i < 3\n"
            ")\n"
            "SELECT c.pk_item_category, c.fk_parent_item_category, n.i\n"
            "  FROM catalog.tb_item_category c CROSS JOIN n;\n"
        )
        == []
    )


def test_an_unnest_of_the_path_in_a_cte_on_a_plain_view_is_not_treekey_002() -> None:
    assert (
        _found(
            "CREATE VIEW v_industry AS WITH p AS (\n"
            "  SELECT i.pk_industry, unnest(string_to_array(i.path::text, '.'::text))::bigint AS anc\n"
            "    FROM catalog.tb_industry i\n"
            ")\n"
            "SELECT p.pk_industry, array_agg(p.anc) AS ancestors FROM p GROUP BY p.pk_industry;\n"
        )
        == []
    )


def test_an_unnest_of_the_path_in_a_scalar_subquery_on_a_plain_view_is_not_treekey_002() -> None:
    assert (
        _found(
            "CREATE VIEW v_location AS SELECT l.pk_location,\n"
            "  (SELECT array_agg(a.name) FROM tenant.tb_location a\n"
            "    WHERE (a.pk_location::text) IN (\n"
            "      SELECT unnest(string_to_array(l.path::text, '.'::text)) AS unnest)) AS names\n"
            "  FROM tenant.tb_location l;\n"
        )
        == []
    )


def test_an_unnest_of_the_path_in_lateral_on_a_plain_view_is_not_treekey_002() -> None:
    assert (
        _found(
            "CREATE VIEW v_location AS SELECT l.pk_location, x.label\n"
            "  FROM tenant.tb_location l,\n"
            "  LATERAL unnest(string_to_array(l.path::text, '.'::text)) x(label);\n"
        )
        == []
    )


def test_any_of_string_to_array_of_the_path_on_a_plain_view_is_not_treekey_002() -> None:
    assert (
        _found(
            "CREATE VIEW v_units AS SELECT o.pk_organizational_unit,\n"
            "  (SELECT array_agg(a.name) FROM tenant.tb_organizational_unit a\n"
            "    WHERE a.pk_organizational_unit::text = ANY (string_to_array(o.path::text, '.'::text)))\n"
            "    AS names\n"
            "  FROM tenant.tb_organizational_unit o;\n"
        )
        == []
    )


def test_an_unnest_of_another_column_is_fine() -> None:
    assert (
        _found(
            "CREATE VIEW v_tags AS SELECT c.pk_item_category, unnest(c.tags) AS tag,\n"
            "  c.path_of_names FROM catalog.tb_item_category c;\n"
        )
        == []
    )


def test_containment_is_fine() -> None:
    assert (
        _found(
            "CREATE VIEW v_names AS SELECT n.pk_item_category,\n"
            "  (SELECT array_agg(a.name ORDER BY (nlevel(a.path)))\n"
            "     FROM catalog.tb_item_category a\n"
            "    WHERE a.path @> n.path) AS path_of_names\n"
            "  FROM catalog.tb_item_category n;\n"
        )
        == []
    )


def test_a_register_ancestry_view_is_fine() -> None:
    assert (
        _found(
            "CREATE VIEW v_item_category_ancestry AS SELECT node.pk_item_category,\n"
            "  nlevel(node.path) AS depth,\n"
            "  (SELECT array_agg(anc.pk_item_category ORDER BY (nlevel(anc.path))) AS array_agg\n"
            "     FROM catalog.tb_item_category anc\n"
            "    WHERE anc.path OPERATOR(public.@>) node.path AND nlevel(anc.path) >= 1)\n"
            "    AS path_of_ids\n"
            "  FROM catalog.tb_item_category node;\n"
        )
        == []
    )


def test_quoted_names_are_matched_quoted_and_both_findings_reported() -> None:
    found = _findings(
        'CREATE TABLE s.t ("Pk" bigint PRIMARY KEY, "Fk_Up" bigint, "Tree Path" ltree);\n'
        "SELECT treekey.manage_path('s.t', 'Pk', 'Fk_Up', 'Tree Path');\n",
        'CREATE VIEW s.v AS WITH RECURSIVE w AS (SELECT t."Fk_Up" FROM s.t t)\n'
        "SELECT unnest(string_to_array(t.\"Tree Path\"::text, '.'::text)) FROM s.t t;\n",
    )
    assert [f.code for f in found] == []


def test_a_bare_name_does_not_match_a_quoted_column() -> None:
    found = _findings(
        'CREATE TABLE s.t ("Pk" bigint PRIMARY KEY, "Fk_Up" bigint, "Tree Path" ltree);\n'
        "SELECT treekey.manage_path('s.t', 'Pk', 'Fk_Up', 'Tree Path');\n",
        "CREATE VIEW s.v AS WITH RECURSIVE w AS (SELECT t.Fk_Up FROM s.t t) SELECT 1 FROM w;\n",
    )
    assert found == []


# -- tests/pg_regress/sql/60_lint_views.sql ---------------------------------------

_REGRESS_TREES = """CREATE TABLE lv.tb_item_category (pk_item_category bigint PRIMARY KEY,
    fk_parent_item_category bigint, name text, path ltree, tags text[]);
CREATE TABLE lv.tb_industry (pk_industry bigint PRIMARY KEY,
    fk_parent_industry bigint, name text, path ltree);
CREATE TABLE lv.tb_location (pk_location bigint PRIMARY KEY,
    fk_parent_location bigint, name text, path ltree);
CREATE TABLE lv.tb_unmanaged (pk_unmanaged bigint PRIMARY KEY,
    fk_parent_unmanaged bigint, path ltree);
SELECT treekey.manage_path('lv.tb_item_category', 'pk_item_category', 'fk_parent_item_category');
SELECT treekey.manage_path('lv.tb_industry', 'pk_industry', 'fk_parent_industry');
SELECT treekey.manage_path('lv.tb_location', 'pk_location', 'fk_parent_location');
"""

_REGRESS_VIEWS = """CREATE VIEW lv.v_category_names AS
WITH RECURSIVE names AS (
    SELECT c.pk_item_category, c.name FROM lv.tb_item_category c
    WHERE c.fk_parent_item_category IS NULL
    UNION ALL
    SELECT c.pk_item_category, n.name || ' > ' || c.name
    FROM lv.tb_item_category c JOIN names n ON c.fk_parent_item_category = n.pk_item_category)
SELECT * FROM names;
CREATE MATERIALIZED VIEW lv.mv_industry AS
WITH p AS (SELECT i.pk_industry, unnest(string_to_array(i.path::text, '.'))::bigint AS anc
           FROM lv.tb_industry i)
SELECT p.pk_industry, array_agg(p.anc) AS ancestors FROM p GROUP BY p.pk_industry;
CREATE VIEW lv.v_location AS
SELECT l.pk_location, x.label
FROM lv.tb_location l, LATERAL unnest(string_to_array(l.path::text, '.')) AS x (label);
CREATE VIEW lv_other.v_location_names AS
SELECT o.pk_location,
       (SELECT array_agg(a.name) FROM lv.tb_location a
        WHERE a.pk_location::text = ANY (string_to_array(o.path::text, '.'))) AS names
FROM lv.tb_location o;
CREATE VIEW lv.v_category_ok AS
SELECT n.pk_item_category,
       (SELECT array_agg(a.name ORDER BY nlevel(a.path)) FROM lv.tb_item_category a
        WHERE a.path @> n.path) AS names
FROM lv.tb_item_category n;
CREATE VIEW lv.v_category_tags AS
SELECT c.pk_item_category, unnest(c.tags) AS tag FROM lv.tb_item_category c;
CREATE VIEW lv.v_category_series AS
WITH RECURSIVE n (i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n WHERE i < 3)
SELECT c.pk_item_category, c.fk_parent_item_category, n.i
FROM lv.tb_item_category c CROSS JOIN n;
CREATE VIEW lv.v_unmanaged AS
SELECT u.pk_unmanaged, unnest(string_to_array(u.path::text, '.')) AS label FROM lv.tb_unmanaged u;
CREATE VIEW lv.v_on_top AS SELECT * FROM lv.v_location;
"""


def test_the_regression_suite_reports_what_lint_views_reports() -> None:
    found = _findings(_REGRESS_TREES, _REGRESS_VIEWS)
    assert found == []


# -- what the static rule adds -------------------------------------------------


def test_no_manage_path_call_means_no_tree_and_no_finding() -> None:
    tables = _REGRESS_TREES.split("SELECT treekey", maxsplit=1)[0]
    assert _findings(tables, _REGRESS_VIEWS) == []


def test_a_finding_is_placed_where_the_walk_is_written_and_says_what_to_do() -> None:
    (found,) = _findings(
        _REGRESS_TREES,
        "SELECT tviews.pg_tviews_create_or_replace('lv.tv_location', $$\n"
        "SELECT l.pk_location, x.label\n"
        "FROM lv.tb_location l, LATERAL unnest(string_to_array(l.path::text, '.'))\n"
        "  WITH ORDINALITY AS x (label, ord) $$);\n",
    )
    assert (found.code, found.file, found.line, found.object_type) == (
        "treekey_002",
        "001.sql",
        3,
        "tview",
    )
    assert "lv.tv_location" in found.message
    assert "lv.tb_location.path" in found.message
    assert "@>" in found.fix


def test_named_arguments_and_an_unqualified_call_declare_a_tree() -> None:
    found = _findings(
        "CREATE TABLE tb_node (pk_node bigint PRIMARY KEY, fk_up bigint, lineage ltree);\n"
        "SELECT manage_path(table_ref => 'tb_node', pk_col => 'pk_node',\n"
        "    parent_fk_col => 'fk_up', path_col => 'lineage');\n",
        "CREATE VIEW v_node AS SELECT n.pk_node, unnest(string_to_array(n.lineage::text, '.'))\n"
        "  FROM public.tb_node n;\n",
    )
    assert found == []


def test_a_tview_reading_the_tree_is_judged_too() -> None:
    found = _findings(
        _REGRESS_TREES,
        "SELECT tviews.pg_tviews_create_or_replace('tv_location', $$\n"
        "  SELECT l.pk_location, x.label\n"
        "  FROM lv.tb_location l, LATERAL unnest(string_to_array(l.path::text, '.')) AS x (label)\n"
        "$$);\n",
    )
    assert found == []


# -- treekey_001: a recursive walk on a TVIEW's chain (pg_tviews 0.1.0-beta.26) ------

_CATEGORY = """CREATE TABLE tb_category (pk_category bigint PRIMARY KEY, id uuid,
    fk_parent bigint, name text, path ltree);
CREATE TABLE tb_item (pk_item bigint PRIMARY KEY, id uuid, fk_category bigint);
SELECT treekey.manage_path('tb_category', 'pk_category', 'fk_parent');
"""

#: pg_tviews#183's shape: the TVIEW reads a view that reads a view that walks the tree.
_PATH_VIEWS = """CREATE VIEW v_category_path AS
WITH RECURSIVE up AS (
  SELECT c.pk_category AS node, c.pk_category AS anc, c.fk_parent, 0 AS depth
    FROM tb_category c
  UNION ALL
  SELECT up.node, p.pk_category, p.fk_parent, up.depth + 1
    FROM up JOIN tb_category p ON p.pk_category = up.fk_parent)
SELECT n.pk_category, (SELECT array_agg(a.name ORDER BY up.depth DESC) FROM up
    JOIN tb_category a ON a.pk_category = up.anc WHERE up.node = n.pk_category) AS names
FROM tb_category n;
CREATE VIEW v_item_def AS
SELECT i.pk_item, i.id, c.names FROM tb_item i JOIN v_category_path c
  ON c.pk_category = i.fk_category;
"""


def _tview(name: str = "tv_item", options: str | None = None) -> str:
    passed = f", options => '{options}'" if options else ""
    return (
        f"SELECT tviews.pg_tviews_create_or_replace('{name}', $$\n"
        f"  SELECT pk_item, id, jsonb_build_object('names', names) AS data FROM v_item_def\n"
        f"$${passed});\n"
    )


def _walks(*texts: str) -> list[TreeWalkFinding]:
    return [f for f in _findings(*texts) if f.code == "treekey_001"]


def test_a_recursive_walk_a_tview_reaches_through_views_is_one_finding_at_the_cte() -> None:
    (found,) = _walks(_CATEGORY, _PATH_VIEWS, _tview())
    assert (found.file, found.line, found.object_type, found.object_name) == (
        "001.sql",
        2,
        "view",
        "v_category_path:tb_category",
    )
    assert found.message.startswith(
        "tv_item reads tb_category in a WITH RECURSIVE through v_item_def → v_category_path: "
    )
    assert "pg_tviews refuses" in found.message
    assert "@>" in found.fix
    assert '"uncascaded_tables": {"tb_category": "full_refresh"}' in found.fix
    assert '"uncascaded_policy": "full_refresh"' in found.fix


@pytest.mark.parametrize(
    "options",
    [
        '{"uncascaded_policy": "full_refresh"}',
        '{"uncascaded_tables": {"public.tb_category": "full_refresh"}}',
        '{"uncascaded_policy": "warn", "uncascaded_tables": {"tb_category": "full_refresh"}}',
    ],
)
def test_a_full_refresh_policy_for_the_tree_is_quiet(options: str) -> None:
    assert _walks(_CATEGORY, _PATH_VIEWS, _tview(options=options)) == []


def test_a_warn_policy_says_the_rows_go_stale() -> None:
    (found,) = _walks(_CATEGORY, _PATH_VIEWS, _tview(options='{"uncascaded_policy": "warn"}'))
    assert "stale" in found.message
    assert "refuses" not in found.message


def test_a_per_table_policy_for_another_table_leaves_the_tree_s() -> None:
    options = '{"uncascaded_tables": {"tb_item": "full_refresh"}}'
    assert len(_walks(_CATEGORY, _PATH_VIEWS, _tview(options=options))) == 1


def test_a_recursive_view_no_tview_reads_is_not_treekey_001() -> None:
    assert _walks(_CATEGORY, _PATH_VIEWS) == []


def test_two_tviews_reaching_one_walk_are_one_finding_naming_both() -> None:
    (found,) = _walks(_CATEGORY, _PATH_VIEWS, _tview("tv_item"), _tview("tv_item_copy"))
    assert found.message.startswith("tv_item and tv_item_copy read tb_category")


def test_a_recursive_cte_naming_the_parent_column_without_reading_the_tree_is_fine() -> None:
    view = (
        "CREATE VIEW v_item_def AS\n"
        "WITH RECURSIVE s(i, fk_parent) AS (SELECT 1, 0::bigint UNION ALL\n"
        "  SELECT i + 1, fk_parent FROM s WHERE i < 3)\n"
        "SELECT i.pk_item, i.id, (SELECT max(s.i) FROM s) AS names FROM tb_item i;\n"
    )
    assert _walks(_CATEGORY, view, _tview()) == []


def test_the_tree_read_in_a_cte_the_recursive_one_reads_counts() -> None:
    """Measured: pg_tviews reads the tree as walked when the recursive CTE reads a sibling."""
    view = (
        "CREATE VIEW v_item_def AS\n"
        "WITH RECURSIVE base AS (SELECT c.pk_category, c.fk_parent FROM tb_category c),\n"
        "up AS (SELECT b.pk_category AS node, b.fk_parent FROM base b UNION ALL\n"
        "  SELECT up.node, p.fk_parent FROM up JOIN base p ON p.pk_category = up.fk_parent)\n"
        "SELECT i.pk_item, i.id, (SELECT count(*) FROM up) AS names FROM tb_item i;\n"
    )
    (found,) = _walks(_CATEGORY, view, _tview())
    assert found.line == 3


def test_a_sibling_cte_the_recursive_one_does_not_read_is_fine() -> None:
    """Measured: a WITH RECURSIVE clause's other CTEs are read as any CTE is."""
    view = (
        "CREATE VIEW v_item_def AS\n"
        "WITH RECURSIVE base AS (SELECT c.pk_category, c.name FROM tb_category c),\n"
        "s(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM s WHERE i < 3)\n"
        "SELECT i.pk_item, i.id, (SELECT max(s.i) FROM s) AS names FROM tb_item i\n"
        "  JOIN base b ON b.pk_category = i.fk_category;\n"
    )
    assert _walks(_CATEGORY, view, _tview()) == []


def test_a_walk_inside_a_called_function_is_not_treekey_001() -> None:
    """Measured: pg_tviews sees a function's tables through function_reads (tview_004)."""
    function = (
        "CREATE FUNCTION f_names(p bigint) RETURNS text[] LANGUAGE sql STABLE AS $f$\n"
        "WITH RECURSIVE up AS (SELECT c.pk_category, c.fk_parent FROM tb_category c\n"
        "  WHERE c.pk_category = p UNION ALL SELECT x.pk_category, x.fk_parent FROM up\n"
        "  JOIN tb_category x ON x.pk_category = up.fk_parent)\n"
        "SELECT array_agg(pk_category::text) FROM up $f$;\n"
        "CREATE VIEW v_item_def AS SELECT i.pk_item, i.id, f_names(i.fk_category) AS names\n"
        "  FROM tb_item i;\n"
    )
    assert _walks(_CATEGORY, function, _tview()) == []


def test_a_tview_written_as_a_table_meets_the_default_policy() -> None:
    (found,) = _walks(
        _CATEGORY,
        _PATH_VIEWS,
        "CREATE TABLE tv_item AS SELECT pk_item, id, names FROM v_item_def;\n",
    )
    assert "pg_tviews refuses" in found.message


def test_the_walk_in_the_tview_s_own_query_is_placed_in_it() -> None:
    (found,) = _walks(
        _CATEGORY,
        "SELECT tviews.pg_tviews_create_or_replace('tv_category', $$\n"
        "WITH RECURSIVE up AS (SELECT c.pk_category, c.fk_parent FROM tb_category c\n"
        "  UNION ALL SELECT p.pk_category, p.fk_parent FROM up\n"
        "  JOIN tb_category p ON p.pk_category = up.fk_parent)\n"
        "SELECT n.pk_category, n.id FROM tb_category n $$);\n",
    )
    assert (found.object_type, found.line) == ("tview", 2)
    assert found.message.startswith("tv_category reads tb_category in a WITH RECURSIVE: ")


# -- treekey_002: the path unnested WITH ORDINALITY on a TVIEW's chain ----------------

#: The spellings measured on pg_tviews 0.1.0-beta.26 (``tviews-probe/defs``), each a
#: TVIEW's whole query over ``tb_category``.
_SPELLINGS = {
    "b": (
        "SELECT n.pk_category, n.id, jsonb_build_object('names',\n"
        "  (SELECT array_agg(a.name ORDER BY nlevel(a.path)) FROM tb_category a\n"
        "    WHERE a.pk_category::text IN (SELECT unnest(string_to_array(n.path::text, '.'))))) AS data\n"
        "FROM tb_category n\n"
    ),
    "b2": (
        "SELECT n.pk_category, n.id, jsonb_build_object('names',\n"
        "  (SELECT array_agg(a.name ORDER BY nlevel(a.path)) FROM tb_category a\n"
        "    WHERE a.pk_category IN (SELECT unnest(string_to_array(n.path::text, '.'))::bigint))) AS data\n"
        "FROM tb_category n\n"
    ),
    "b3": (
        "SELECT n.pk_category, n.id, jsonb_build_object('names',\n"
        "  (SELECT array_agg(a.name ORDER BY nlevel(a.path))\n"
        "     FROM unnest(string_to_array(n.path::text, '.')) AS u(lbl) JOIN tb_category a ON a.pk_category = u.lbl::bigint)) AS data\n"
        "FROM tb_category n\n"
    ),
    "b4": (
        "SELECT n.pk_category, n.id, jsonb_build_object('names',\n"
        "  (SELECT array_agg(a.name ORDER BY u.ord)\n"
        "     FROM unnest(string_to_array(n.path::text, '.')) WITH ORDINALITY AS u(lbl, ord) JOIN tb_category a ON a.pk_category = u.lbl::bigint)) AS data\n"
        "FROM tb_category n\n"
    ),
    "c": (
        "SELECT n.pk_category, n.id, jsonb_build_object('names', x.names) AS data\n"
        "FROM tb_category n\n"
        "CROSS JOIN LATERAL (SELECT array_agg(a.name ORDER BY u.ord) AS names\n"
        "   FROM unnest(string_to_array(n.path::text, '.')) WITH ORDINALITY AS u(lbl, ord)\n"
        "   JOIN tb_category a ON a.pk_category = u.lbl::bigint) x\n"
    ),
    "c2": (
        "SELECT n.pk_category, n.id, jsonb_build_object('names', array_agg(a.name ORDER BY u.ord)) AS data\n"
        "FROM tb_category n\n"
        "CROSS JOIN LATERAL unnest(string_to_array(n.path::text, '.')) WITH ORDINALITY AS u(lbl, ord)\n"
        "JOIN tb_category a ON a.pk_category = u.lbl::bigint\n"
        "GROUP BY n.pk_category, n.id\n"
    ),
    "c3": (
        "SELECT n.pk_category, n.id, jsonb_build_object('names', array_agg(a.name ORDER BY nlevel(a.path))) AS data\n"
        "FROM tb_category n\n"
        "CROSS JOIN LATERAL unnest(string_to_array(n.path::text, '.')) AS u(lbl)\n"
        "JOIN tb_category a ON a.pk_category = u.lbl::bigint\n"
        "GROUP BY n.pk_category, n.id\n"
    ),
    "c4": (
        "SELECT n.pk_category, n.id, jsonb_build_object('names', x.names) AS data\n"
        "FROM tb_category n\n"
        "CROSS JOIN LATERAL (SELECT array_agg(a.name ORDER BY nlevel(a.path)) AS names\n"
        "   FROM tb_category a WHERE a.pk_category IN (SELECT unnest(string_to_array(n.path::text, '.'))::bigint)) x\n"
    ),
    "d": (
        "SELECT n.pk_category, n.id, jsonb_build_object('names',\n"
        "  (SELECT array_agg(a.name ORDER BY nlevel(a.path)) FROM tb_category a\n"
        "    WHERE a.pk_category::text = ANY (string_to_array(n.path::text, '.')))) AS data\n"
        "FROM tb_category n\n"
    ),
    "e": (
        "WITH anc AS (SELECT c.pk_category, unnest(string_to_array(c.path::text, '.'))::bigint AS anc FROM tb_category c)\n"
        "SELECT n.pk_category, n.id, jsonb_build_object('names', array_agg(a.name ORDER BY nlevel(a.path))) AS data\n"
        "FROM tb_category n JOIN anc ON anc.pk_category = n.pk_category JOIN tb_category a ON a.pk_category = anc.anc\n"
        "GROUP BY n.pk_category, n.id\n"
    ),
}


def _spelled(name: str, options: str | None = None) -> str:
    passed = f", options => '{options}'" if options else ""
    return (
        "SELECT tviews.pg_tviews_create_or_replace('tv_category', $$\n"
        + _SPELLINGS[name]
        + f"$${passed});\n"
    )


def _ordinal(*texts: str) -> list[TreeWalkFinding]:
    return [f for f in _findings(*texts) if f.code == "treekey_002"]


@pytest.mark.parametrize("name", ["b4", "c", "c2"])
def test_the_path_unnested_with_ordinality_is_treekey_002(name: str) -> None:
    (found,) = _ordinal(_CATEGORY, _spelled(name))
    assert (found.object_type, found.object_name) == ("tview", "tv_category:tb_category")
    assert found.message.startswith(
        "tv_category unnests tb_category.path WITH ORDINALITY: pg_tviews refuses"
    )
    assert "nlevel" in found.fix


@pytest.mark.parametrize("name", ["b", "b2", "b3", "c3", "c4", "d", "e"])
def test_every_other_unnest_of_the_path_is_traced(name: str) -> None:
    assert _findings(_CATEGORY, _spelled(name)) == []


def test_the_ordinality_is_placed_where_it_is_written() -> None:
    (found,) = _ordinal(_CATEGORY, _spelled("c2"))
    assert (found.file, found.line) == ("001.sql", 4)


def test_an_ordinality_a_tview_reaches_through_a_view_is_reported_in_the_view() -> None:
    (found,) = _ordinal(
        _CATEGORY,
        "CREATE VIEW v_category_names AS\n" + _SPELLINGS["c2"] + ";\n",
        "CREATE TABLE tv_category AS SELECT * FROM v_category_names;\n",
    )
    assert (found.object_name, found.line) == ("v_category_names:tb_category", 4)
    assert found.message.startswith("tv_category unnests tb_category.path WITH ORDINALITY through")


def test_an_ordinality_no_tview_reads_is_not_treekey_002() -> None:
    assert _ordinal(_CATEGORY, "CREATE VIEW v_category_names AS\n" + _SPELLINGS["c2"] + ";\n") == []


def test_a_full_refresh_policy_for_the_tree_quiets_treekey_002() -> None:
    """Measured: the ordinality is an uncascaded read, so full_refresh creates the TVIEW."""
    options = '{"uncascaded_tables": {"tb_category": "full_refresh"}}'
    assert _ordinal(_CATEGORY, _spelled("c2", options)) == []


def test_a_warn_policy_says_the_ordinality_leaves_rows_stale() -> None:
    (found,) = _ordinal(_CATEGORY, _spelled("b4", '{"uncascaded_policy": "warn"}'))
    assert "stale" in found.message


def test_a_tree_registered_with_another_path_column_is_read() -> None:
    tree = (
        "CREATE TABLE tb_node (pk_node bigint PRIMARY KEY, id uuid, fk_up bigint, name text,\n"
        "    lineage ltree);\n"
        "SELECT treekey.manage_path('tb_node', 'pk_node', 'fk_up', path_col => 'lineage');\n"
    )
    query = (
        "SELECT tviews.pg_tviews_create_or_replace('tv_node', $$\n"
        "SELECT n.pk_node, n.id, x.label FROM tb_node n\n"
        "CROSS JOIN LATERAL unnest(string_to_array(n.lineage::text, '.')) WITH ORDINALITY\n"
        "  AS x(label, ord) $$);\n"
    )
    assert [f.object_name for f in _ordinal(tree, query)] == ["tv_node:tb_node"]
    assert _ordinal(tree, query.replace("n.lineage", "n.name")) == []
