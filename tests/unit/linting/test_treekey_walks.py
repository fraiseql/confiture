"""How a view walks a pg_treekey tree (#676): ``treekey_001`` and ``treekey_002``.

pg_tviews follows a view's dependencies to decide which TVIEW rows a write
refreshes, and a ``WITH RECURSIVE`` over the parent key or an ``unnest`` of the
path is a spelling it cannot always follow. The fixtures are pg_treekey's own,
from ``src/lint.rs`` and ``tests/pg_regress/sql/60_lint_views.sql``, so the rule
and ``treekey.lint_views()`` agree.
"""

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


def test_a_recursive_cte_over_the_parent_fk_is_treekey_001() -> None:
    assert _found(
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
    ) == ["treekey_001"]


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


def test_an_unnest_of_the_path_in_a_cte_is_treekey_002() -> None:
    assert _found(
        "CREATE VIEW v_industry AS WITH p AS (\n"
        "  SELECT i.pk_industry, unnest(string_to_array(i.path::text, '.'::text))::bigint AS anc\n"
        "    FROM catalog.tb_industry i\n"
        ")\n"
        "SELECT p.pk_industry, array_agg(p.anc) AS ancestors FROM p GROUP BY p.pk_industry;\n"
    ) == ["treekey_002"]


def test_an_unnest_of_the_path_in_a_scalar_subquery_is_treekey_002() -> None:
    assert _found(
        "CREATE VIEW v_location AS SELECT l.pk_location,\n"
        "  (SELECT array_agg(a.name) FROM tenant.tb_location a\n"
        "    WHERE (a.pk_location::text) IN (\n"
        "      SELECT unnest(string_to_array(l.path::text, '.'::text)) AS unnest)) AS names\n"
        "  FROM tenant.tb_location l;\n"
    ) == ["treekey_002"]


def test_an_unnest_of_the_path_in_lateral_is_treekey_002() -> None:
    assert _found(
        "CREATE VIEW v_location AS SELECT l.pk_location, x.label\n"
        "  FROM tenant.tb_location l,\n"
        "  LATERAL unnest(string_to_array(l.path::text, '.'::text)) x(label);\n"
    ) == ["treekey_002"]


def test_any_of_string_to_array_of_the_path_is_treekey_002() -> None:
    assert _found(
        "CREATE VIEW v_units AS SELECT o.pk_organizational_unit,\n"
        "  (SELECT array_agg(a.name) FROM tenant.tb_organizational_unit a\n"
        "    WHERE a.pk_organizational_unit::text = ANY (string_to_array(o.path::text, '.'::text)))\n"
        "    AS names\n"
        "  FROM tenant.tb_organizational_unit o;\n"
    ) == ["treekey_002"]


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
    assert [f.code for f in found] == ["treekey_001", "treekey_002"]


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
    assert sorted((f.object_name, f.code) for f in found) == [
        ("lv.mv_industry:lv.tb_industry", "treekey_002"),
        ("lv.v_category_names:lv.tb_item_category", "treekey_001"),
        ("lv.v_location:lv.tb_location", "treekey_002"),
        ("lv_other.v_location_names:lv.tb_location", "treekey_002"),
    ]


# -- what the static rule adds -------------------------------------------------


def test_no_manage_path_call_means_no_tree_and_no_finding() -> None:
    tables = _REGRESS_TREES.split("SELECT treekey", maxsplit=1)[0]
    assert _findings(tables, _REGRESS_VIEWS) == []


def test_a_finding_is_placed_where_the_walk_is_written_and_says_what_to_do() -> None:
    (found,) = _findings(
        _REGRESS_TREES,
        "CREATE VIEW lv.v_location AS\n"
        "SELECT l.pk_location, x.label\n"
        "FROM lv.tb_location l, LATERAL unnest(string_to_array(l.path::text, '.')) AS x (label);\n",
    )
    assert (found.code, found.file, found.line, found.object_type) == (
        "treekey_002",
        "001.sql",
        3,
        "view",
    )
    assert "lv.v_location" in found.message
    assert "lv.tb_location.path" in found.message
    assert "treekey.register_ancestry" in found.fix
    assert "@>" in found.fix


def test_named_arguments_and_an_unqualified_call_declare_a_tree() -> None:
    found = _findings(
        "CREATE TABLE tb_node (pk_node bigint PRIMARY KEY, fk_up bigint, lineage ltree);\n"
        "SELECT manage_path(table_ref => 'tb_node', pk_col => 'pk_node',\n"
        "    parent_fk_col => 'fk_up', path_col => 'lineage');\n",
        "CREATE VIEW v_node AS SELECT n.pk_node, unnest(string_to_array(n.lineage::text, '.'))\n"
        "  FROM public.tb_node n;\n",
    )
    assert [(f.code, f.object_name) for f in found] == [("treekey_002", "v_node:tb_node")]


def test_a_tview_reading_the_tree_is_judged_too() -> None:
    found = _findings(
        _REGRESS_TREES,
        "SELECT tviews.pg_tviews_create_or_replace('tv_location', $$\n"
        "  SELECT l.pk_location, x.label\n"
        "  FROM lv.tb_location l, LATERAL unnest(string_to_array(l.path::text, '.')) AS x (label)\n"
        "$$);\n",
    )
    assert [(f.code, f.object_type, f.line) for f in found] == [("treekey_002", "tview", 3)]
