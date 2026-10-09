"""Session state a stored projection reads (#656): ``tview_003``–``005``, ``session_001``–``003``.

A TVIEW's rows are computed in the session that writes a base row, so whatever
its definition reads of the session — a setting, the role, the time — is the
writer's, stored for every reader.
"""

import pytest

from confiture.core.linting.inventory import build_inventory
from confiture.core.linting.session_reads import (
    SESSION_CODES,
    SessionFinding,
    session_read_findings,
)
from confiture.core.sql_lexer import parse_file

#: The TVIEW family; the all-views family is selected where a test says so.
TVIEW_CODES = frozenset({"tview_003", "tview_004", "tview_005"})

_BASE = "CREATE TABLE tb_product (pk_product bigint PRIMARY KEY, id uuid, label text, ends date);\n"


def _findings(*texts: str, codes: frozenset[str] = TVIEW_CODES) -> list[SessionFinding]:
    files = []
    base = 0
    for at, text in enumerate(texts):
        files.append(parse_file(text, f"{at:03}.sql", base))
        base += len(text) + 1
    return session_read_findings(files, build_inventory(files), codes)


def _codes(found: list[SessionFinding]) -> list[str]:
    return sorted(f.code for f in found)


def test_a_setting_read_through_a_view_is_an_error_where_it_is_read() -> None:
    (found,) = _findings(
        _BASE,
        "CREATE VIEW v_product AS\n"
        "SELECT p.pk_product, p.id, current_setting('app.locale', true) AS locale\n"
        "FROM tb_product p;\n",
        "CREATE TABLE tv_product AS SELECT pk_product, id FROM v_product;\n",
    )
    assert (found.code, found.file, found.line) == ("tview_003", "001.sql", 2)
    assert found.message == (
        "tv_product reads current_setting('app.locale') through v_product: "
        "the stored row takes the writer's value, not the reader's"
    )
    assert found.object_name == "v_product:current_setting(app.locale)"


def test_a_tview_written_as_a_call_is_read_at_the_line_inside_its_query() -> None:
    (found,) = _findings(
        _BASE,
        "SELECT tviews.pg_tviews_create_or_replace('tv_product', $$\n"
        "  SELECT pk_product, id,\n"
        "         (ends >= CURRENT_DATE) AS is_current\n"
        "  FROM tb_product $$);\n",
        codes=frozenset({"tview_005"}),
    )
    assert (found.code, found.file, found.line) == ("tview_005", "001.sql", 3)
    assert "tv_product reads CURRENT_DATE" in found.message


@pytest.mark.parametrize(
    "expression",
    [
        "now()",
        "pg_catalog.now()",
        "clock_timestamp()",
        "statement_timestamp()",
        "transaction_timestamp()",
        "CURRENT_TIMESTAMP",
        "LOCALTIMESTAMP(0)",
        "'today'::date",
        "age(ends::timestamp)",
    ],
)
def test_every_time_read_is_one(expression: str) -> None:
    found = _findings(
        _BASE,
        f"CREATE TABLE tv_product AS SELECT pk_product, id, {expression} AS t FROM tb_product;\n",
    )
    assert _codes(found) == ["tview_005"]


@pytest.mark.parametrize("expression", ["CURRENT_USER", "SESSION_USER", "current_schema"])
def test_the_session_s_identity_is_session_state(expression: str) -> None:
    found = _findings(
        _BASE,
        f"CREATE TABLE tv_product AS SELECT pk_product, id, {expression} AS who FROM tb_product;\n",
    )
    assert _codes(found) == ["tview_003"]


def test_age_of_two_arguments_reads_no_time() -> None:
    found = _findings(
        _BASE,
        "CREATE TABLE tv_product AS SELECT pk_product, id, "
        "age(ends::timestamp, ends::timestamp) AS a FROM tb_product;\n",
    )
    assert found == []


_HELPER = (
    "CREATE FUNCTION public.caller_locale() RETURNS text STABLE LANGUAGE plpgsql AS $$\n"
    "BEGIN\n"
    "  RETURN coalesce(current_setting('app.locale', true), 'en');\n"
    "END $$;\n"
)


def test_a_helper_is_reported_at_its_source_and_as_a_call() -> None:
    found = _findings(
        _BASE,
        _HELPER,
        "CREATE VIEW v_product AS SELECT pk_product, id, label || caller_locale() AS l "
        "FROM tb_product;\n",
        "CREATE TABLE tv_product AS SELECT pk_product, id FROM v_product;\n",
    )
    by_code = {f.code: f for f in found}
    assert sorted(by_code) == ["tview_003", "tview_004"]
    assert (by_code["tview_003"].file, by_code["tview_003"].line) == ("001.sql", 3)
    assert "through v_product → public.caller_locale()" in by_code["tview_003"].message
    assert (by_code["tview_004"].file, by_code["tview_004"].line) == ("002.sql", 1)
    assert "calls public.caller_locale() (STABLE)" in by_code["tview_004"].message


@pytest.mark.parametrize(
    "body",
    [
        "LANGUAGE sql AS $$ SELECT current_setting('app.locale') $$",
        "LANGUAGE sql BEGIN ATOMIC SELECT current_setting('app.locale'); END",
    ],
)
def test_sql_bodies_are_read_too(body: str) -> None:
    found = _findings(
        _BASE,
        f"CREATE FUNCTION locale() RETURNS text IMMUTABLE {body};\n",
        "CREATE TABLE tv_product AS SELECT pk_product, id, locale() AS l FROM tb_product;\n",
    )
    # IMMUTABLE as declared: no call finding, but the body is read all the same.
    assert _codes(found) == ["tview_003"]


def test_functions_calling_each_other_terminate() -> None:
    found = _findings(
        _BASE,
        "CREATE FUNCTION a(n int) RETURNS int VOLATILE LANGUAGE sql AS $$ SELECT b(n) $$;\n"
        "CREATE FUNCTION b(n int) RETURNS int VOLATILE LANGUAGE sql AS $$ SELECT a(n) $$;\n",
        "CREATE TABLE tv_product AS SELECT pk_product, id, a(1) AS x FROM tb_product;\n",
    )
    # One finding per call site: the TVIEW's a(), a's b(), b's a().
    assert sorted((f.object_name, f.line) for f in found) == [
        ("a():b()", 1),
        ("b():a()", 2),
        ("tv_product:a()", 1),
    ]


def test_builtins_and_pg_catalog_are_not_calls() -> None:
    found = _findings(
        _BASE,
        "CREATE TABLE tv_product AS SELECT pk_product, id, lower(label) AS l, "
        "pg_catalog.random() AS r FROM tb_product;\n",
    )
    assert found == []


def test_a_matview_or_another_tview_in_the_chain_is_not_walked() -> None:
    found = _findings(
        _BASE,
        "CREATE MATERIALIZED VIEW m_product AS SELECT pk_product, now() AS t FROM tb_product;\n"
        "CREATE TABLE tv_other AS SELECT pk_product, id FROM tb_product;\n",
        "CREATE TABLE tv_product AS SELECT m.pk_product, o.id FROM m_product m "
        "JOIN tv_other o USING (pk_product);\n",
    )
    assert found == []


def test_declared_options_silence_their_rule() -> None:
    call = (
        "SELECT tviews.pg_tviews_create_or_replace('tv_product', $$\n"
        "  SELECT pk_product, id, caller_locale() AS l, now() AS t FROM tb_product $$,\n"
        '  \'{{"time_refresh": "external", "function_reads": {reads}}}\');\n'
    )
    plain = _findings(_BASE, _HELPER, call.format(reads="{}"))
    assert _codes(plain) == ["tview_003", "tview_004"]
    declared = _findings(_BASE, _HELPER, call.format(reads='{"public.caller_locale()": []}'))
    assert _codes(declared) == ["tview_003"]


def test_a_warn_policy_is_not_refused_by_pg_tviews() -> None:
    found = _findings(
        _BASE,
        "SELECT tviews.pg_tviews_create_or_replace('tv_product', $$\n"
        "  SELECT pk_product, id, now() AS t FROM tb_product $$,\n"
        '  \'{"uncascaded_policy": "warn"}\');\n',
    )
    assert found == []


def test_a_waiver_with_a_reason_silences_the_read_it_names() -> None:
    found = _findings(
        _BASE,
        "-- confiture:projection-reads-session app.locale, now: the projection is per-locale\n"
        "CREATE TABLE tv_product AS SELECT pk_product, id, now() AS t,\n"
        "  current_setting('app.locale') AS l FROM tb_product;\n",
    )
    assert found == []


def test_a_waiver_above_a_view_in_the_chain_counts() -> None:
    found = _findings(
        _BASE,
        "-- confiture:projection-reads-session current_date: a daily snapshot\n"
        "CREATE VIEW v_product AS SELECT pk_product, id, CURRENT_DATE AS d FROM tb_product;\n",
        "CREATE TABLE tv_product AS SELECT pk_product, id, d FROM v_product;\n",
    )
    assert found == []


def test_a_waiver_without_a_reason_silences_nothing_and_says_so() -> None:
    (found,) = _findings(
        _BASE,
        "-- confiture:projection-reads-session app.locale\n"
        "CREATE TABLE tv_product AS SELECT pk_product, id, "
        "current_setting('app.locale') AS l FROM tb_product;\n",
    )
    assert found.code == "tview_003"
    assert "gives no reason" in found.message


def test_one_finding_per_read_names_every_tview_that_reaches_it() -> None:
    found = _findings(
        _BASE,
        "CREATE VIEW v_product AS SELECT pk_product, id, CURRENT_DATE AS d FROM tb_product;\n",
        "CREATE TABLE tv_a AS SELECT pk_product, id, d FROM v_product;\n"
        "CREATE TABLE tv_b AS SELECT pk_product, id, d FROM v_product;\n",
    )
    (finding,) = found
    assert finding.message.startswith("tv_a and tv_b read CURRENT_DATE through v_product")


def test_the_view_family_is_off_unless_selected() -> None:
    tree = (
        _BASE,
        "CREATE VIEW v_today AS SELECT pk_product, CURRENT_DATE AS d FROM tb_product;\n",
    )
    assert _findings(*tree, codes=frozenset({"tview_003", "tview_004", "tview_005"})) == []
    (found,) = _findings(*tree, codes=frozenset({"session_003"}))
    assert (found.code, found.object_name) == ("session_003", "v_today:CURRENT_DATE")


def test_the_two_families_report_independently() -> None:
    found = _findings(
        _BASE,
        "CREATE VIEW v_product AS SELECT pk_product, id, CURRENT_DATE AS d FROM tb_product;\n",
        "CREATE TABLE tv_product AS SELECT pk_product, id, d FROM v_product;\n",
        codes=SESSION_CODES,
    )
    assert _codes(found) == ["session_003", "tview_005"]


def test_the_codes_are_the_registry_s() -> None:
    assert TVIEW_CODES | {"session_001", "session_002", "session_003"} == SESSION_CODES


def test_a_query_that_does_not_parse_is_named_unread_not_passed_as_clean() -> None:
    from confiture.core.linting.session_reads import session_reads

    text = "SELECT tviews.pg_tviews_create_or_replace('tv_product', $$ SELEKT now() $$);\n"
    files = [parse_file(_BASE, "000.sql", 0), parse_file(text, "001.sql", len(_BASE) + 1)]
    read = session_reads(files, build_inventory(files), TVIEW_CODES)
    assert read.findings == []
    assert read.unread == ["tv_product (its query does not parse)"]


def test_select_session_reads_selects_the_view_family() -> None:
    from confiture.core.linting.rule_registry import resolve_selection

    assert resolve_selection(["session_reads"], ()) == frozenset(
        {"session_001", "session_002", "session_003"}
    )
    assert {"tview_003", "tview_004", "tview_005"} <= resolve_selection(None, ())
