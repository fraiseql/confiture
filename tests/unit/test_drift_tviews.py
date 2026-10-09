"""A pg_tviews TVIEW is compared as one object: missing is critical, extra is info (#504).

Until #504 the DDL side dropped ``CREATE TABLE tv_post AS SELECT …`` and the live
side read ``tv_post`` as a table, so every TVIEW project reported
``extra_table warning public.tv_post`` (measured on 1.26.0) — failing
``--fail-on-warning`` on a database built from its own DDL.
"""

from unittest.mock import MagicMock

from confiture.core.drift import DriftType, SchemaDriftDetector, parse_expected_schema
from confiture.core.schema_model import (
    Coverage,
    FunctionRead,
    SchemaModel,
    Table,
    TView,
    ref_for,
    tview_ref,
)

DECLARED = """
CREATE TABLE tb_post (pk_post bigint PRIMARY KEY);
CREATE TABLE tv_post AS SELECT pk_post FROM tb_post;
"""

POST = Table(name="tb_post", schema="public")


def live(*tviews: TView) -> SchemaModel:
    expected_table = parse_expected_schema(DECLARED).model.tables
    return SchemaModel(
        tables=expected_table, tviews={tview_ref(t): t for t in tviews}, coverage=Coverage.every()
    )


def compare(live_model: SchemaModel):
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value.fetchone.return_value = ("db",)
    expected = parse_expected_schema(DECLARED).model
    return SchemaDriftDetector(conn).compare_schemas(expected, live_model).drift_items


def keys(items) -> list[tuple[str, str, str]]:
    return sorted((i.drift_type.value, i.severity.value, i.object_name) for i in items)


def test_the_expected_side_holds_the_tview_and_no_table_for_it() -> None:
    model = parse_expected_schema(DECLARED).model
    assert list(model.tviews) == [ref_for("tview", "public", "tv_post")]
    assert ref_for("table", "public", "tv_post") not in model.tables


def test_a_database_holding_the_tview_reports_nothing() -> None:
    assert compare(live(TView(name="tv_post", schema="public"))) == []


def test_a_missing_tview_is_critical() -> None:
    assert keys(compare(live())) == [("missing_tview", "critical", "tv_post")]


def test_an_extra_tview_is_info() -> None:
    found = compare(
        live(TView(name="tv_post", schema="public"), TView(name="tv_user", schema="public"))
    )
    assert keys(found) == [("extra_tview", "info", "public.tv_user")]


def test_the_kinds_are_published() -> None:
    assert (DriftType.MISSING_TVIEW.value, DriftType.EXTRA_TVIEW.value) == (
        "missing_tview",
        "extra_tview",
    )


PINNED = """
CREATE TABLE tb_post (pk_post bigint PRIMARY KEY);
CREATE TABLE tv_post WITH (fillfactor = 70) AS SELECT pk_post FROM tb_post;
"""


def compare_pinned(ddl: str, live_model: SchemaModel):
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value.fetchone.return_value = ("db",)
    expected = parse_expected_schema(ddl).model
    return SchemaDriftDetector(conn).compare_schemas(expected, live_model).drift_items


def test_a_pinned_option_the_database_does_not_hold_is_a_warning() -> None:
    found = compare_pinned(
        PINNED, live(TView(name="tv_post", schema="public", logged=False, fillfactor=85))
    )

    assert [
        (i.drift_type.value, i.severity.value, i.object_name, i.expected, i.actual) for i in found
    ] == [("tview_option_mismatch", "warning", "tv_post", "fillfactor = 70", "fillfactor = 85")]
    assert found[0].subject is not None
    assert (found[0].subject.schema, found[0].subject.relation, found[0].subject.name) == (
        "public",
        "tv_post",
        "fillfactor",
    )


def test_a_key_the_tree_does_not_pin_is_never_drift() -> None:
    """``logged`` is pg_tviews' default or a hand's choice: the tree said nothing."""
    found = compare_pinned(
        PINNED, live(TView(name="tv_post", schema="public", logged=True, fillfactor=70))
    )

    assert found == []


def test_a_pinned_persistence_is_compared() -> None:
    ddl = PINNED.replace(
        "CREATE TABLE tv_post WITH (fillfactor = 70)", "CREATE UNLOGGED TABLE tv_post"
    )
    found = compare_pinned(
        ddl, live(TView(name="tv_post", schema="public", logged=True, fillfactor=85))
    )

    assert keys(found) == [("tview_option_mismatch", "warning", "tv_post")]
    assert (found[0].expected, found[0].actual) == ("logged = false", "logged = true")


def test_the_option_kind_is_published() -> None:
    assert DriftType.TVIEW_OPTION_MISMATCH.value == "tview_option_mismatch"


def test_set_logged_in_the_tree_is_a_pin_drift_compares() -> None:
    """The tree ``tview_002`` asks for: a TVIEW left unlogged on the database is drift."""
    ddl = f"{DECLARED}ALTER TABLE tv_post SET LOGGED;\n"
    found = compare_pinned(
        ddl, live(TView(name="tv_post", schema="public", logged=False, fillfactor=85))
    )

    assert [(i.drift_type.value, i.expected, i.actual) for i in found] == [
        ("tview_option_mismatch", "logged = true", "logged = false")
    ]


def test_set_fillfactor_in_the_tree_is_a_pin_drift_compares() -> None:
    """A TVIEW whose fillfactor the tree set by ``ALTER`` drifts when the database holds another."""
    ddl = f"{DECLARED}ALTER TABLE tv_post SET (fillfactor = 70);\n"
    found = compare_pinned(
        ddl, live(TView(name="tv_post", schema="public", logged=False, fillfactor=85))
    )

    assert [(i.drift_type.value, i.expected, i.actual) for i in found] == [
        ("tview_option_mismatch", "fillfactor = 70", "fillfactor = 85")
    ]


POLICY = """
CREATE TABLE tb_post (pk_post bigint PRIMARY KEY);
SELECT tviews.pg_tviews_create_or_replace('tv_post', 'SELECT pk_post FROM tb_post',
    options => '{"uncascaded_policy": "full_refresh"}');
"""


def test_a_pinned_uncascaded_policy_is_compared_with_the_registrys() -> None:
    """``tviews.registry.uncascaded_policy``, which pg_tviews keeps out of ``options``."""
    found = compare_pinned(
        POLICY,
        live(
            TView(
                name="tv_post",
                schema="public",
                logged=False,
                fillfactor=85,
                uncascaded_policy="warn",
            )
        ),
    )

    assert [(i.drift_type.value, i.expected, i.actual) for i in found] == [
        (
            "tview_option_mismatch",
            'uncascaded_policy = "full_refresh"',
            'uncascaded_policy = "warn"',
        )
    ]


def test_a_policy_the_tree_does_not_pin_is_never_drift() -> None:
    """A ``CREATE TABLE … AS`` takes the session's ``pg_tviews.uncascaded_policy``."""
    found = compare_pinned(
        DECLARED,
        live(TView(name="tv_post", schema="public", uncascaded_policy="warn")),
    )

    assert found == []


READS = """
CREATE TABLE tb_post (pk_post bigint PRIMARY KEY);
SELECT tviews.pg_tviews_create_or_replace('tv_post', 'SELECT pk_post FROM tb_post',
    options => '{"time_refresh": "external",
                 "function_reads": {"label_suffix()": ["tb_setting"],
                                    "app.price(int8, date)": ["app.tb_price"]}}');
"""


def _registry(**declared: object) -> SchemaModel:
    """The TVIEW as ``tviews.registry`` spells it under confiture's read path (``public``)."""
    return live(TView(name="tv_post", schema="public", logged=False, fillfactor=85, **declared))


def test_declared_reads_the_registry_holds_are_no_drift() -> None:
    """The registry qualifies a function and formats its types; a table on the path is bare."""
    found = compare_pinned(
        READS,
        _registry(
            time_refresh="external",
            function_reads=(
                FunctionRead("app.price(bigint, date)", ("app.tb_price",)),
                FunctionRead("public.label_suffix()", ("tb_setting",)),
            ),
        ),
    )

    assert found == []


def test_a_declared_read_the_registry_does_not_hold_is_a_warning() -> None:
    found = compare_pinned(
        READS,
        _registry(
            function_reads=(FunctionRead("public.label_suffix()", ("tb_setting",)),),
        ),
    )

    assert sorted((i.drift_type.value, i.severity.value, i.subject.name) for i in found) == [
        ("tview_option_mismatch", "warning", "function_reads"),
        ("tview_option_mismatch", "warning", "time_refresh"),
    ]
    by_key = {i.subject.name: i for i in found}
    assert by_key["time_refresh"].actual == "time_refresh = null"
    assert by_key["function_reads"].actual == (
        'function_reads = {"public.label_suffix()": ["tb_setting"]}'
    )


def test_reads_the_tree_does_not_declare_are_never_drift() -> None:
    """An absent key leaves the registry's value as it is, as a replace keeps it."""
    found = compare_pinned(
        DECLARED,
        _registry(
            time_refresh="external",
            function_reads=(FunctionRead("public.label_suffix()", ("tb_setting",)),),
        ),
    )

    assert found == []
