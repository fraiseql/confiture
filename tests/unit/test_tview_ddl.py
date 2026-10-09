"""The DDL side reads a TVIEW: ``CREATE TABLE tv_<entity> AS SELECT`` (#504).

pg_tviews intercepts a ``CREATE TABLE … AS`` whose target is named ``tv_*``,
and only that one, so the reader applies the same rule. Until #504 the
statement was invisible: neither a table nor a view.
"""

import pglast
import pytest
from pglast.stream import RawStream

from confiture.core.schema_model import TView, ref_for
from confiture.core.schema_read import read_text
from confiture.core.sql_lexer import parse_file

SELECT = "SELECT p.pk_post, p.id FROM tb_post p"
TABLES = "CREATE TABLE tb_post (pk_post bigint PRIMARY KEY, id uuid);\n"


def _rendered(select: str) -> str:
    return RawStream()(pglast.parse_sql(select)[0].stmt)


@pytest.mark.parametrize(
    ("target", "schema"), [("tv_post", None), ("app.tv_post", "app")], ids=["bare", "qualified"]
)
def test_a_create_table_as_into_tv_is_a_tview(target: str, schema: str | None) -> None:
    model = read_text(f"{TABLES}CREATE TABLE {target} AS {SELECT};\n").model

    assert model.tviews == {
        ref_for("tview", schema, "tv_post"): TView(
            name="tv_post", schema=schema, definition=_rendered(SELECT)
        )
    }
    assert ref_for("table", schema, "tv_post") not in model.tables


def test_a_create_table_as_into_another_name_is_no_tview() -> None:
    model = read_text(f"{TABLES}CREATE TABLE post_copy AS {SELECT};\n").model

    assert model.tviews == {}


def test_a_materialized_view_is_still_a_view() -> None:
    model = read_text(f"{TABLES}CREATE MATERIALIZED VIEW tv_post AS {SELECT};\n").model

    assert model.tviews == {}
    assert ref_for("matview", None, "tv_post") in model.views


def test_drop_table_drops_the_tview() -> None:
    model = read_text(f"{TABLES}CREATE TABLE tv_post AS {SELECT};\nDROP TABLE tv_post;\n").model

    assert model.tviews == {}


def test_a_changed_tview_is_an_object_that_changed() -> None:
    """``migrate validate --require-migration`` compares tracked objects by definition."""
    from confiture.core.ddl_objects import objects_in

    def tracked(select: str) -> dict:
        sql = f"{TABLES}CREATE TABLE tv_post AS {select};\n"
        return objects_in([parse_file(sql)])

    before, after = tracked(SELECT), tracked("SELECT p.pk_post FROM tb_post p")
    ref = ref_for("tview", None, "tv_post")
    assert before.keys() == after.keys() == {ref}
    assert before[ref][0].definition != after[ref][0].definition


def test_a_table_named_tv_with_columns_is_a_table() -> None:
    """``tv_`` is a common naming convention with no pg_tviews anywhere: the shape decides.

    A production project fraisier deploys holds ten ``CREATE TABLE public.tv_x (…)``
    and no pg_tviews. Read by the prefix, each would be a TVIEW the database lacks —
    ten critical ``missing_tview`` on a clean deploy.
    """
    model = read_text("CREATE TABLE public.tv_order (id bigint PRIMARY KEY, data jsonb);\n").model

    assert model.tviews == {}
    assert ref_for("table", "public", "tv_order") in model.tables


def test_a_tview_carries_the_storage_its_statement_pins() -> None:
    """``UNLOGGED`` and ``WITH (fillfactor = n)`` are pg_tviews' ``logged`` and ``fillfactor``."""
    model = read_text(
        f"{TABLES}CREATE UNLOGGED TABLE tv_post WITH (fillfactor = 70) AS {SELECT};\n"
    ).model

    (tview,) = model.tviews.values()
    assert (tview.logged, tview.fillfactor) == (False, 70)


def test_a_tview_that_pins_nothing_carries_no_storage() -> None:
    """An unpinned key is pg_tviews' to choose, and the tree's to leave alone."""
    (tview,) = read_text(f"{TABLES}CREATE TABLE tv_post AS {SELECT};\n").model.tviews.values()

    assert (tview.logged, tview.fillfactor) == (None, None)


CTAS = f"{TABLES}CREATE TABLE tv_post AS {SELECT};\n"
CALL = f"{TABLES}SELECT tviews.pg_tviews_create_or_replace('tv_post', $q${SELECT}$q$);\n"


@pytest.mark.parametrize(
    "call",
    [
        f"SELECT tviews.pg_tviews_create_or_replace('tv_post', $q${SELECT}$q$)",
        f"SELECT pg_tviews_create_or_replace('post', '{SELECT}')",
        f"SELECT tviews.pg_tviews_create_or_replace(tview_name => 'tv_post', query => $q${SELECT}$q$)",
        f"SELECT tviews.pg_tviews_create('tv_post', $q${SELECT}$q$)",
    ],
    ids=["create_or_replace", "entity-unqualified", "named", "create"],
)
def test_a_pg_tviews_call_declares_the_tview_its_ctas_would(call: str) -> None:
    """``pg_tviews_create_or_replace()`` is how a generated migration writes a TVIEW (#504)."""
    assert read_text(f"{TABLES}{call};\n").model.tviews == read_text(CTAS).model.tviews


@pytest.mark.parametrize(
    "options",
    [
        """options => '{"logged": false, "fillfactor": 70}'""",
        """'{"fillfactor": 70, "logged": false}'::jsonb""",
    ],
    ids=["named", "positional-cast"],
)
def test_a_call_pins_the_options_it_passes(options: str) -> None:
    call = f"SELECT tviews.pg_tviews_create_or_replace('tv_post', $q${SELECT}$q$, {options});\n"
    pinned = f"{TABLES}CREATE UNLOGGED TABLE tv_post WITH (fillfactor = 70) AS {SELECT};\n"

    assert read_text(f"{TABLES}{call}").model.tviews == read_text(pinned).model.tviews


def test_a_call_names_its_schema() -> None:
    call = f"SELECT tviews.pg_tviews_create_or_replace('app.tv_post', $q${SELECT}$q$);\n"

    assert list(read_text(f"{TABLES}{call}").model.tviews) == [ref_for("tview", "app", "tv_post")]


@pytest.mark.parametrize("created", [CTAS, CALL], ids=["ctas", "call"])
def test_pg_tviews_drop_in_the_tree_drops_the_tview(created: str) -> None:
    assert (
        read_text(
            f"{created}SELECT tviews.pg_tviews_drop('tv_post', if_exists => true);\n"
        ).model.tviews
        == {}
    )


def test_a_drop_before_the_create_keeps_the_tview() -> None:
    """``drop; create`` is the everyday idiom, and the fold is order-aware."""
    tree = f"{TABLES}SELECT tviews.pg_tviews_drop('tv_post', true);\n{CALL.removeprefix(TABLES)}"

    assert list(read_text(tree).model.tviews) == [ref_for("tview", None, "tv_post")]


def test_a_call_naming_no_constant_declares_nothing() -> None:
    """A name this reader cannot read is no TVIEW it can name."""
    tree = f"{TABLES}SELECT tviews.pg_tviews_create_or_replace(d.name, d.query) FROM defs d;\n"

    assert read_text(tree).model.tviews == {}


def _tracked(sql: str) -> dict:
    from confiture.core.ddl_objects import objects_in

    return objects_in([parse_file(sql)])


def test_a_tview_written_as_a_call_is_the_object_its_ctas_is() -> None:
    """``migrate validate --require-migration`` and the diff see one TVIEW, however it is written."""
    ctas, call = _tracked(CTAS), _tracked(CALL)

    assert ctas.keys() == call.keys() == {ref_for("tview", None, "tv_post")}
    ((written,),) = ctas.values()
    ((called,),) = call.values()
    assert (written.definition, written.create_sql) == (called.definition, called.create_sql)


@pytest.mark.parametrize("created", [CTAS, CALL], ids=["ctas", "call"])
def test_a_tview_dropped_by_a_call_is_no_tracked_object(created: str) -> None:
    assert _tracked(f"{created}SELECT tviews.pg_tviews_drop('tv_post');\n") == {}


def test_moving_a_tview_from_ctas_to_a_call_changes_nothing() -> None:
    from confiture import platform

    assert platform.diff(CTAS, CALL).changes == []


@pytest.mark.parametrize(
    ("tree", "logged"),
    [
        (f"{CTAS}ALTER TABLE tv_post SET LOGGED;\n", True),
        (f"{CTAS}ALTER TABLE public.tv_post SET LOGGED;\n", True),
        (f"{CALL}ALTER TABLE tv_post SET LOGGED;\n", True),
        (f"{CTAS}ALTER TABLE tv_post SET LOGGED;\nALTER TABLE tv_post SET UNLOGGED;\n", False),
        (CTAS.replace("CREATE TABLE", "CREATE UNLOGGED TABLE"), False),
        (CTAS, None),
    ],
    ids=["set-logged", "qualified", "call", "set-unlogged-after", "unlogged-ctas", "nothing"],
)
def test_set_logged_pins_the_tview_logged(tree: str, logged: bool | None) -> None:
    """``ALTER TABLE … SET LOGGED`` is how pg_tviews' docs say to keep a TVIEW on a standby."""
    (tview,) = read_text(tree).model.tviews.values()

    assert tview.logged is logged


@pytest.mark.parametrize(
    "tree",
    [
        CTAS,
        f"{CTAS}ALTER TABLE tv_post SET LOGGED;\n",
        f"{CTAS}ALTER TABLE tv_post SET LOGGED;\nALTER TABLE tv_post SET UNLOGGED;\n",
        CALL.replace("$q$);", """$q$, options => '{"logged": true}');"""),
        CALL.replace("$q$);", """$q$, options => '{"logged": false}');"""),
    ],
    ids=["ctas", "set-logged", "set-unlogged-after", "call-logged", "call-unlogged"],
)
def test_the_lint_and_the_model_agree_on_whether_a_tview_is_logged(tree: str) -> None:
    """``tview_002`` fires exactly when the model does not pin the TVIEW logged."""
    from confiture.core.linting.tview_rules import tview_findings

    flagged = any(
        f[0] == "tview_002" for f in tview_findings(read_text(tree).inventory, has_replicas=True)
    )
    (tview,) = read_text(tree).model.tviews.values()

    assert flagged is (tview.logged is not True)


def test_a_generated_tview_passes_the_logged_its_tree_set() -> None:
    """``migrate diff --generate`` writes the TVIEW the tree ends with, ``SET LOGGED`` included."""
    from confiture.core.ddl_walk import tview_calls

    tracked = _tracked(f"{CTAS}ALTER TABLE tv_post SET LOGGED;\n")
    ((obj,),) = tracked.values()
    (call,) = tview_calls(pglast.parse_sql(obj.create_sql)[0].stmt)
    assert call.options == {"logged": True}
    called = _tracked(CALL.replace("$q$);", """$q$, options => '{"logged": true}');"""))
    ((same,),) = called.values()
    assert obj.definition == same.definition


def test_set_logged_reaches_a_tview_the_tree_defines_twice() -> None:
    """Two definitions are one object (``duplicates.wins``); the fold keeps what decides it."""
    tree = f"{CTAS}{CALL.removeprefix(TABLES)}ALTER TABLE tv_post SET LOGGED;\n"

    from confiture.core.ddl_walk import tview_calls

    ((obj,),) = _tracked(tree).values()
    (call,) = tview_calls(pglast.parse_sql(obj.create_sql)[0].stmt)
    assert call.options == {"logged": True}


@pytest.mark.parametrize(
    ("tree", "fillfactor"),
    [
        (f"{CTAS}ALTER TABLE tv_post SET (fillfactor = 70);\n", 70),
        (f"{CTAS}ALTER TABLE public.tv_post SET (fillfactor = '70');\n", 70),
        (f"{CALL}ALTER TABLE tv_post SET (fillfactor = 70, autovacuum_enabled = false);\n", 70),
        (
            f"{CTAS}ALTER TABLE tv_post SET (fillfactor = 70);\nALTER TABLE tv_post RESET (fillfactor);\n",
            100,
        ),
        (f"{CTAS}ALTER TABLE tv_post SET (autovacuum_enabled = false);\n", None),
        (f"{CTAS}ALTER TABLE tv_post SET LOGGED, SET (fillfactor = 70);\n", 70),
        (CTAS, None),
    ],
    ids=["set", "quoted-value", "call", "reset-after", "other-option", "with-logged", "nothing"],
)
def test_set_fillfactor_pins_the_tview_fillfactor(tree: str, fillfactor: int | None) -> None:
    """``SET (fillfactor = n)`` pins n; ``RESET`` pins PostgreSQL's 100, as the registry reads it."""
    (tview,) = read_text(tree).model.tviews.values()

    assert tview.fillfactor == fillfactor


def test_set_logged_and_fillfactor_in_one_alter_pin_both() -> None:
    (tview,) = read_text(
        f"{CTAS}ALTER TABLE tv_post SET LOGGED, SET (fillfactor = 70);\n"
    ).model.tviews.values()

    assert (tview.logged, tview.fillfactor) == (True, 70)


def test_a_generated_tview_passes_the_fillfactor_its_tree_set() -> None:
    """``migrate diff --generate`` writes the TVIEW the tree ends with, ``SET (fillfactor)`` included."""
    from confiture.core.ddl_walk import tview_calls

    tree = f"{CTAS}ALTER TABLE tv_post SET LOGGED;\nALTER TABLE tv_post SET (fillfactor = 70);\n"
    ((obj,),) = _tracked(tree).values()
    (call,) = tview_calls(pglast.parse_sql(obj.create_sql)[0].stmt)
    assert call.options == {"fillfactor": 70, "logged": True}
    called = _tracked(
        CALL.replace("$q$);", """$q$, options => '{"logged": true, "fillfactor": 70}');""")
    )
    ((same,),) = called.values()
    assert obj.definition == same.definition


POLICY = CALL.replace("$q$);", """$q$, options => '{"uncascaded_policy": "full_refresh"}');""")


def test_a_call_pins_the_uncascaded_policy_it_passes() -> None:
    """pg_tviews 0.1.0-beta.25 takes the key in ``options`` and stores it beside them."""
    (tview,) = read_text(POLICY).model.tviews.values()

    assert (tview.uncascaded_policy, tview.logged, tview.fillfactor) == ("full_refresh", None, None)


@pytest.mark.parametrize("tree", [CTAS, CALL], ids=["ctas", "call"])
def test_a_tview_that_names_no_policy_pins_none(tree: str) -> None:
    """``CREATE TABLE … AS`` reads ``pg_tviews.uncascaded_policy``, a session setting: no pin."""
    (tview,) = read_text(tree).model.tviews.values()

    assert tview.uncascaded_policy is None


def test_a_generated_tview_passes_the_uncascaded_policy_its_tree_declares() -> None:
    """``migrate diff --generate`` writes the call with the policy, beside the storage pins."""
    from confiture.core.ddl_walk import tview_calls

    tree = POLICY + "ALTER TABLE tv_post SET LOGGED;\n"
    ((obj,),) = _tracked(tree).values()
    (call,) = tview_calls(pglast.parse_sql(obj.create_sql)[0].stmt)
    assert call.options == {"logged": True, "uncascaded_policy": "full_refresh"}
    assert obj.create_sql.endswith(
        """options => '{"logged": true, "uncascaded_policy": "full_refresh"}')"""
    )


def test_a_changed_uncascaded_policy_is_a_change() -> None:
    from confiture import platform

    warned = POLICY.replace("full_refresh", "warn")
    assert platform.diff(POLICY, warned).changes != []
    assert platform.diff(CALL, POLICY).changes != []


READS = CALL.replace(
    "$q$);",
    """$q$, options => '{"time_refresh": "external",
        "function_reads": {"public.label_suffix()": ["tb_setting", "app.tb_locale"],
                           "now_utc()": []}}');""",
)


def test_a_call_pins_the_reads_it_declares() -> None:
    """``time_refresh`` and ``function_reads`` as written, functions and tables sorted."""
    from confiture.core.schema_model import FunctionRead

    (tview,) = read_text(READS).model.tviews.values()

    assert tview.time_refresh == "external"
    assert tview.function_reads == (
        FunctionRead("now_utc()", ()),
        FunctionRead("public.label_suffix()", ("app.tb_locale", "tb_setting")),
    )


@pytest.mark.parametrize("tree", [CTAS, CALL], ids=["ctas", "call"])
def test_a_tview_that_declares_no_reads_pins_none(tree: str) -> None:
    (tview,) = read_text(tree).model.tviews.values()

    assert (tview.time_refresh, tview.function_reads) == (None, None)


def test_an_empty_function_reads_is_a_pin() -> None:
    """``{}`` replaces what the registry holds; an absent key keeps it."""
    tree = CALL.replace("$q$);", """$q$, options => '{"function_reads": {}}');""")
    (tview,) = read_text(tree).model.tviews.values()

    assert tview.function_reads == ()


def test_a_generated_tview_passes_the_reads_its_tree_declares() -> None:
    from confiture.core.ddl_walk import tview_calls

    ((obj,),) = _tracked(READS).values()
    (call,) = tview_calls(pglast.parse_sql(obj.create_sql)[0].stmt)
    assert call.options["time_refresh"] == "external"
    assert obj.create_sql.endswith(
        """options => '{"function_reads": {"now_utc()": [], """
        """"public.label_suffix()": ["app.tb_locale", "tb_setting"]}, """
        """"time_refresh": "external"}')"""
    )


def test_a_changed_declared_read_is_a_change() -> None:
    from confiture import platform

    assert platform.diff(CALL, READS).changes != []
    assert platform.diff(READS, READS.replace("now_utc()", "now_local()")).changes != []
