"""``-- Strategy: <name>`` is read from a comment token, not from a line that starts with ``--``."""

from __future__ import annotations

from confiture.core.strategy import parse_migration_strategy


def test_header_in_the_first_lines() -> None:
    assert parse_migration_strategy("-- Strategy: Rebuild\nCREATE TABLE t (id int);\n") == "rebuild"


def test_header_inside_a_dollar_quoted_body_is_not_a_header() -> None:
    assert parse_migration_strategy("DO $$\n-- Strategy: rebuild\n$$;\n") is None


def test_header_past_the_tenth_line_is_not_read() -> None:
    sql = "\n" * 10 + "-- Strategy: rebuild\n"
    assert parse_migration_strategy(sql) is None


def test_no_header() -> None:
    assert parse_migration_strategy("SELECT 1;\n") is None
