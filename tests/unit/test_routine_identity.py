"""One signature identity: a routine read from DDL and one read from a catalogue.

A routine is the same routine when its name and its input argument types are the
same, and "the same type" is ``type_lattice``'s answer — never a spelling. There
were two canonicalisers of an argument type, and the cases they split on are the
ones pinned here, each written the way a DDL file writes it on one side and the
way ``format_type`` writes it on the other:

* ``int8`` and ``bigint`` are one type; ``int[]`` and ``int`` are two;
* ``app.t`` and a bare ``t`` are one type when ``search_path`` makes them one —
  a schema written on one side and left off the other matches (#302);
* ``char(2)`` is ``character``; ``timestamp`` is ``timestamp without time zone``;
* an array is one array however many ``[]`` the DDL wrote: PostgreSQL ignores the
  dimension count in a type;
* a type ``format_type`` quotes is the type the DDL named without quotes.
"""

from __future__ import annotations

import pytest

from confiture.core.linting.inventory import (
    build_model,
    signature_from_type_names,
    signatures_match,
)
from confiture.core.schema_model import Routine, View


def _routine(sql: str) -> Routine:
    (routines,) = build_model(sql).routines.values()
    (routine,) = routines
    return routine


def _key(arguments: str) -> tuple:
    return _routine(
        f"CREATE FUNCTION app.f({arguments}) RETURNS int LANGUAGE sql AS $$ SELECT 1 $$;"
    ).signature_key


def test_int8_and_bigint_are_one_signature() -> None:
    assert _key("a int8") == _key("a bigint")


def test_an_array_and_its_element_are_two_signatures() -> None:
    assert not signatures_match(_key("a int[]"), _key("a int"))


def test_a_type_schema_written_on_one_side_only_still_matches() -> None:
    assert signatures_match(_key("a app.t"), _key("a t"))


def test_two_different_type_schemas_never_match() -> None:
    assert not signatures_match(_key("a app.t"), _key("a other.t"))


@pytest.mark.parametrize(
    ("written", "catalogued"),
    [
        ("a int", "integer"),
        ("a int8", "bigint"),
        ("a varchar(20)", "character varying"),
        ("a timestamptz", "timestamp with time zone"),
        ("a timestamp", "timestamp without time zone"),
        ("a time", "time without time zone"),
        ("a char(2)", "character"),
        ("a float", "double precision"),
        ("a numeric(10, 2)", "numeric"),
        ("a int[]", "integer[]"),
        ("a text[][]", "text[]"),
        ("a app.status", "app.status"),
        ('a "MyType"', '"MyType"'),
        ("VARIADIC a text[]", "text[]"),
    ],
)
def test_the_ddl_and_the_catalogue_spell_one_signature(written: str, catalogued: str) -> None:
    assert signatures_match(_key(written), signature_from_type_names([catalogued]))


def test_out_parameters_are_not_part_of_the_signature() -> None:
    assert _key("a int, OUT b text") == _key("a int")


class TestTheModelHoldsRoutines:
    SQL = """
        CREATE FUNCTION app.f(a int8, b text) RETURNS bigint
        LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = app
        AS $$ BEGIN RETURN a; END $$;
        CREATE PROCEDURE p() LANGUAGE sql AS $$ SELECT 1 $$;
    """

    def test_a_function_is_read_whole(self) -> None:
        model = build_model(self.SQL)
        f = next(r for rs in model.routines.values() for r in rs if r.name == "f")
        assert (f.schema, f.kind, f.language, f.volatility) == (
            "app",
            "function",
            "plpgsql",
            "stable",
        )
        assert (f.security_definer, f.search_path_pinned) == (True, True)
        assert f.body == " BEGIN RETURN a; END "
        assert f.returns == "bigint"
        assert f.signature_key == ((None, "bigint"), (None, "text"))

    def test_a_procedure_defaults_to_volatile_and_invoker(self) -> None:
        model = build_model(self.SQL)
        p = next(r for rs in model.routines.values() for r in rs if r.name == "p")
        assert (p.kind, p.volatility, p.security_definer, p.returns) == (
            "procedure",
            "volatile",
            False,
            None,
        )

    def test_create_or_replace_keeps_the_last_definition(self) -> None:
        sql = (
            "CREATE FUNCTION f() RETURNS int LANGUAGE sql AS $$ SELECT 1 $$;"
            "CREATE OR REPLACE FUNCTION f() RETURNS int LANGUAGE sql AS $$ SELECT 2 $$;"
        )
        assert _routine(sql).body == " SELECT 2 "

    def test_a_dropped_routine_is_not_declared(self) -> None:
        sql = (
            "CREATE FUNCTION f(a int8) RETURNS int LANGUAGE sql AS $$ SELECT 1 $$;"
            "DROP FUNCTION f(bigint);"
        )
        assert build_model(sql).routines == {}


class TestTheModelHoldsViews:
    SQL = """
        CREATE TABLE t (id int);
        CREATE VIEW app.v AS SELECT id FROM t;
        CREATE MATERIALIZED VIEW mv AS SELECT id FROM t;
        CREATE UNIQUE INDEX mv_id ON mv (id);
    """

    def _views(self) -> dict[str, View]:
        return {v.name: v for v in build_model(self.SQL).views.values()}

    def test_a_view_and_a_matview(self) -> None:
        views = self._views()
        assert (views["v"].schema, views["v"].materialized) == ("app", False)
        assert (views["mv"].schema, views["mv"].materialized) == (None, True)
        assert views["v"].definition == "SELECT id FROM t"

    def test_an_index_on_a_matview_is_the_matviews(self) -> None:
        (index,) = self._views()["mv"].indexes
        assert (index.name, index.columns, index.unique) == ("mv_id", ("id",), True)
