"""``confiture seed generate`` and ``seed convert``, run by their command line.

``seed generate`` reads a live table and writes a commented-out INSERT template
with one ``<type_n>`` placeholder per value. The tests fill it in the way its
HINT line asks: uncomment it, put a value where each placeholder is. Then they
run it against the table it was generated from. A template that names the
wrong columns, or a column that takes no value, fails there.

``seed convert`` rewrites an INSERT seed file as ``COPY … FROM stdin``, and a
COPY block is data for ``psql``, not for a driver. So the output is loaded with
``psql`` into a fresh database, the INSERT file into a second one, and the rows
must be the same. The values are chosen to be hard for COPY's text format: an
empty string beside a NULL, a tab, a newline, a backslash, the text ``\\N``,
and a non-ASCII character.

The ``xfail`` test records a defect found while writing this file.

Every test runs in databases of its own.
"""

from __future__ import annotations

import json
import re
import shutil
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.psql_applier import apply_sql_via_psql
from confiture.error_codes import FAILURE, FINDINGS

pytestmark = pytest.mark.integration

runner = CliRunner()

_PLACEHOLDER = re.compile(r"<[^<>]+_(\d+)>")


def _database(make: Callable[[str], str], *ddl: str) -> str:
    url = make("confiture_t")
    with psycopg.connect(url, autocommit=True) as conn:
        for statement in ddl:
            conn.execute(statement)
    return url


def _filled(stub: str) -> str:
    """The template's INSERT, uncommented, each ``<type_n>`` replaced by the literal ``'n'``."""
    lines = stub.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("-- INSERT INTO"))
    end = next(i for i in range(start, len(lines)) if lines[i].endswith(";"))
    insert = "\n".join(line.removeprefix("-- ") for line in lines[start : end + 1])
    return _PLACEHOLDER.sub(r"'\1'", insert)


# ── seed generate ──────────────────────────────────────────────────────────────

_WIDGETS = (
    "CREATE TABLE widgets ("
    " id BIGSERIAL PRIMARY KEY,"
    " label TEXT NOT NULL,"
    " weight INTEGER NOT NULL,"
    " created_at TIMESTAMPTZ NOT NULL DEFAULT now())"
)


def test_generate_writes_a_template_that_inserts_into_the_table(
    fresh_database_factory: Callable[[str], str], tmp_path: Path
) -> None:
    url = _database(fresh_database_factory, _WIDGETS)
    seeds = tmp_path / "db" / "seeds"

    result = runner.invoke(
        app,
        [
            "seed",
            "generate",
            "widgets",
            "--database-url",
            url,
            "--output-dir",
            str(seeds),
            "--rows",
            "3",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    stub_path = seeds / "development" / "widgets.sql"
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert payload["output_path"] == str(stub_path)
    assert (payload["row_count"], payload["column_count"]) == (3, 4)
    stub = stub_path.read_text()
    assert "-- INSERT INTO public.widgets (label, weight)" in stub.splitlines()
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(_filled(stub))
        rows = conn.execute("SELECT label, weight FROM widgets ORDER BY id").fetchall()
    assert rows == [("1", 1), ("2", 2), ("3", 3)]


def test_generate_keeps_an_existing_seed_file_unless_told_to_overwrite(
    fresh_database_factory: Callable[[str], str], tmp_path: Path
) -> None:
    url = _database(fresh_database_factory, _WIDGETS)
    seeds = tmp_path / "seeds"
    argv = ["seed", "generate", "widgets", "-d", url, "-o", str(seeds), "--seed-env", "test"]
    first = runner.invoke(app, [*argv, "-n", "2"])
    assert first.exit_code == 0, first.output
    stub_path = seeds / "test" / "widgets.sql"
    original = stub_path.read_text()

    refused = runner.invoke(app, [*argv, "-n", "5", "--format", "json"])

    assert refused.exit_code == FAILURE, refused.output
    payload = json.loads(refused.stdout)
    assert payload["success"] is False
    assert "--overwrite" in payload["error"]
    assert stub_path.read_text() == original

    replaced = runner.invoke(
        app,
        [
            "seed",
            "generate",
            "widgets",
            "-d",
            url,
            "-o",
            str(seeds),
            "--seed-env",
            "test",
            "-n",
            "5",
            "--overwrite",
        ],
    )

    assert replaced.exit_code == 0, replaced.output
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(_filled(stub_path.read_text()))
        assert conn.execute("SELECT count(*) FROM widgets").fetchone() == (5,)


def test_generate_for_a_table_that_does_not_exist_fails_and_writes_nothing(
    fresh_database: str, tmp_path: Path
) -> None:
    seeds = tmp_path / "seeds"

    result = runner.invoke(
        app,
        ["seed", "generate", "no_such_table", "-d", fresh_database, "-o", str(seeds), "-f", "json"],
    )

    assert result.exit_code == FAILURE, result.output
    payload = json.loads(result.stdout)
    assert payload["success"] is False
    assert "public.no_such_table not found" in payload["error"]
    assert not seeds.exists()


@pytest.mark.xfail(
    strict=True,
    raises=psycopg.errors.GeneratedAlways,
    reason="#360: the template lists identity (GENERATED ALWAYS) and generated columns, "
    "which accept no value",
)
def test_generate_leaves_out_columns_postgresql_computes(
    fresh_database_factory: Callable[[str], str], tmp_path: Path
) -> None:
    url = _database(
        fresh_database_factory,
        "CREATE TABLE gadgets ("
        " id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,"
        " label TEXT NOT NULL,"
        " label_length INTEGER GENERATED ALWAYS AS (length(label)) STORED)",
    )

    result = runner.invoke(
        app, ["seed", "generate", "gadgets", "-d", url, "-o", str(tmp_path), "-n", "2"]
    )

    assert result.exit_code == 0, result.output
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(_filled((tmp_path / "development" / "gadgets.sql").read_text()))
        assert conn.execute("SELECT label, label_length FROM gadgets ORDER BY id").fetchall() == [
            ("1", 1),
            ("2", 1),
        ]


# ── seed convert ───────────────────────────────────────────────────────────────

_ITEMS = (
    "CREATE TABLE items ("
    " id INTEGER PRIMARY KEY, label TEXT, weight INTEGER, active BOOLEAN, price NUMERIC)"
)

_INSERTS = (
    "INSERT INTO items (id, label, weight, active, price) VALUES\n"
    "  (1, '', -5, true, 3.14),\n"
    "  (2, 'line one\nline two', 0, false, NULL),\n"
    "  (3, '\\N', 7, TRUE, 1e3),\n"
    "  (4, 'it''s a\ttab', NULL, NULL, -0.5);\n"
    "INSERT INTO items (id, label, weight, active, price) VALUES (5, 'café ☕ C:\\dir', 9, false, 0);\n"
)

_ROWS = [
    (1, "", -5, True, Decimal("3.14")),
    (2, "line one\nline two", 0, False, None),
    (3, "\\N", 7, True, Decimal("1000")),
    (4, "it's a\ttab", None, None, Decimal("-0.5")),
    (5, "café ☕ C:\\dir", 9, False, Decimal("0")),
]


@pytest.fixture
def psql_on_path() -> None:
    if shutil.which("psql") is None:
        pytest.skip("psql not on PATH")


def _rows(url: str) -> list[tuple]:
    with psycopg.connect(url) as conn:
        return conn.execute("SELECT * FROM items ORDER BY id").fetchall()


@pytest.mark.usefixtures("psql_on_path")
def test_convert_writes_copy_that_psql_loads_to_the_same_rows(
    fresh_database_factory: Callable[[str], str], tmp_path: Path
) -> None:
    inserts = tmp_path / "items.sql"
    inserts.write_text(_INSERTS)
    copy = tmp_path / "items_copy.sql"

    result = runner.invoke(app, ["seed", "convert", "--input", str(inserts), "--output", str(copy)])

    assert result.exit_code == 0, result.output
    assert "Rows: 5" in result.stdout
    text = copy.read_text()
    assert text.startswith("COPY items (id, label, weight, active, price) FROM stdin;\n")
    assert "INSERT" not in text
    from_copy = _database(fresh_database_factory, _ITEMS)
    from_inserts = _database(fresh_database_factory, _ITEMS)
    apply_sql_via_psql(from_copy, sql_file=copy)
    apply_sql_via_psql(from_inserts, sql_file=inserts)
    assert _rows(from_copy) == _rows(from_inserts) == _ROWS


def test_convert_without_output_writes_the_same_copy_to_stdout(tmp_path: Path) -> None:
    inserts = tmp_path / "items.sql"
    inserts.write_text(_INSERTS)
    copy = tmp_path / "items_copy.sql"
    written = runner.invoke(app, ["seed", "convert", "--input", str(inserts), "-o", str(copy)])
    assert written.exit_code == 0, written.output

    result = runner.invoke(app, ["seed", "convert", "--input", str(inserts)])

    assert result.exit_code == 0, result.output
    assert result.stdout == copy.read_text()


@pytest.mark.usefixtures("psql_on_path")
def test_convert_batch_converts_what_it_can_and_names_what_it_skipped(
    fresh_database: str, tmp_path: Path
) -> None:
    seeds = tmp_path / "seeds"
    seeds.mkdir()
    (seeds / "01_items.sql").write_text(_INSERTS)
    (seeds / "02_computed.sql").write_text(
        "INSERT INTO items (id, label) VALUES (6, upper('computed'));\n"
    )
    out = tmp_path / "seeds_copy"

    result = runner.invoke(
        app, ["seed", "convert", "--input", str(seeds), "--batch", "--output", str(out)]
    )

    assert result.exit_code == 0, result.output
    assert "02_computed.sql" in result.stdout
    assert sorted(p.name for p in out.iterdir()) == ["01_items.sql"]
    with psycopg.connect(fresh_database, autocommit=True) as conn:
        conn.execute(_ITEMS)
    apply_sql_via_psql(fresh_database, sql_file=out / "01_items.sql")
    assert _rows(fresh_database) == _ROWS


def test_convert_refuses_a_file_it_cannot_convert(tmp_path: Path) -> None:
    computed = tmp_path / "computed.sql"
    computed.write_text("INSERT INTO items (id, label) VALUES (6, upper('computed'));\n")
    copy = tmp_path / "computed_copy.sql"

    result = runner.invoke(app, ["seed", "convert", "--input", str(computed), "-o", str(copy)])

    assert result.exit_code == FINDINGS, result.output
    assert "Cannot convert" in result.stdout
    assert not copy.exists()
