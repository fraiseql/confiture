"""``server_constants``: the target server spells the tree's constants (#564).

What the oracle answers is measured by ``test_default_comparison_is_measured.py``;
this holds what it must not do — read a type through the session's ``search_path``,
fail a whole read over one refused value, or leave the caller's transaction broken.
"""

from collections.abc import Callable

import psycopg
import pytest

from confiture.core.ddl_walk import AS_WRITTEN
from confiture.core.drift import parse_expected_schema
from confiture.core.server_constants import server_constants


@pytest.fixture
def url(fresh_database_factory: Callable[[str], str]) -> str:
    return fresh_database_factory("confiture_constants")


def test_a_constant_is_spelled_in_the_sessions_time_zone(url: str) -> None:
    model = parse_expected_schema(
        "CREATE TABLE t (at timestamptz DEFAULT '2024-01-01 00:00');"
    ).model
    with psycopg.connect(url) as conn:
        conn.execute("SET TimeZone = 'Asia/Tokyo'")
        spelled = server_constants(conn, model)
    assert spelled.spell("2024-01-01 00:00", "timestamptz") == "2024-01-01 00:00:00+09"


def test_a_type_is_named_as_the_tree_places_it_not_by_search_path(url: str) -> None:
    ddl = "CREATE SCHEMA app; CREATE TYPE app.mood AS ENUM ('ok', 'sad');"
    model = parse_expected_schema(f"{ddl} CREATE TABLE t (m mood[] DEFAULT '{{ok, sad}}');").model
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(ddl)
        assert conn.execute("SELECT to_regtype('mood')").fetchone() == (None,)
        spelled = server_constants(conn, model)
    assert spelled.spell("{ok, sad}", "mood[]") == "{ok,sad}"


def test_a_type_the_server_lacks_is_left_as_written(url: str) -> None:
    model = parse_expected_schema("CREATE TABLE t (m mood DEFAULT 'ok');").model
    with psycopg.connect(url) as conn:
        assert server_constants(conn, model) == AS_WRITTEN


def test_a_refused_value_is_left_as_written_and_the_rest_spelled(url: str) -> None:
    """A label the live enum does not hold yet is its own difference, not the read's end."""
    model = parse_expected_schema(
        "CREATE TYPE mood AS ENUM ('ok', 'new');"
        " CREATE TABLE t (m mood DEFAULT 'new', d date DEFAULT '2024-1-1');"
    ).model
    with psycopg.connect(url) as conn:
        conn.execute("CREATE TYPE mood AS ENUM ('ok')")
        spelled = server_constants(conn, model)
        # The caller's transaction is still the caller's, and still usable.
        assert conn.execute("SELECT to_regtype('mood') IS NOT NULL").fetchone() == (True,)
    assert spelled.spell("new", "mood") == "new"
    assert spelled.spell("2024-1-1", "date") == "2024-01-01"


def test_a_tree_without_typed_constants_asks_nothing(url: str) -> None:
    model = parse_expected_schema(
        "CREATE TABLE t (n int DEFAULT 1 + 2, at timestamptz DEFAULT now());"
    ).model
    with psycopg.connect(url) as conn:
        assert server_constants(conn, model) == AS_WRITTEN
