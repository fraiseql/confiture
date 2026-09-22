"""Seeds the platform writes: in the model's column order, refused at write time when wrong.

A column the table does not have, one PostgreSQL fills, a NOT NULL column left out
or handed ``None`` — each would fail at apply time, one file into a run, far from
the code that wrote it. The model knows all four when the file is written, so that
is when they are refused. What is written is text PostgreSQL reads back as the
value it was handed: COPY's escapes, SQL's quoting, and one conversion of a Python
value to PostgreSQL's input text behind both.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from confiture import platform

EX06 = Path(__file__).resolve().parents[2] / "examples" / "06-prep-seed-validation"

DDL = """
CREATE TABLE app.item (
    pk_item BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id UUID NOT NULL UNIQUE,
    "Label" TEXT NOT NULL,
    note TEXT,
    active BOOLEAN NOT NULL DEFAULT true,
    payload JSONB,
    tags TEXT[],
    blob BYTEA
);
"""


@pytest.fixture(scope="module")
def model() -> platform.SchemaModel:
    return platform.parse_schema(DDL)


ROW = {
    "id": "00000000-0000-4000-8000-000000000001",
    "Label": "tab\there, line\nthere, back\\slash, vt\x0b, \\N",
    "note": None,
    "active": False,
    "payload": {"k": ["v", 1]},
    "tags": ["a b", 'quo"te', None],
    "blob": b"\x00\xff",
}


def test_a_copy_seed_names_the_table_and_columns_as_postgresql_reads_them(tmp_path, model) -> None:
    seed = platform.write_copy_seed(
        tmp_path / "01_items.sql", "app.item", list(ROW), [ROW], model=model
    )
    assert seed.path.read_text() == (
        'COPY app.item (id, "Label", note, active, payload, tags, blob) FROM stdin;\n'
        "00000000-0000-4000-8000-000000000001\t"
        "tab\\there, line\\nthere, back\\\\slash, vt\x0b, \\\\N\t"
        "\\N\tfalse\t"
        '{"k": ["v", 1]}\t'
        '{"a b","quo\\\\"te",NULL}\t'
        "\\\\x00ff\n"
        "\\.\n"
    )
    assert (seed.format, seed.rows, seed.columns) == ("copy", 1, tuple(ROW))
    assert (seed.table.schema, seed.table.name) == ("app", "item")


def test_an_insert_seed_quotes_every_value_as_a_literal(tmp_path, model) -> None:
    seed = platform.write_insert_seed(
        tmp_path / "01_items.sql", "app.item", list(ROW), [ROW], model=model
    )
    assert seed.path.read_text() == (
        'INSERT INTO app.item (id, "Label", note, active, payload, tags, blob) VALUES\n'
        "    ('00000000-0000-4000-8000-000000000001', "
        "E'tab\there, line\nthere, back\\\\slash, vt\x0b, \\\\N', "
        "NULL, 'false', "
        '\'{"k": ["v", 1]}\', '
        'E\'{"a b","quo\\\\"te",NULL}\', '
        "E'\\\\x00ff');\n"
    )
    assert seed.format == "insert"


def test_several_rows_are_one_statement_in_row_order(tmp_path, model) -> None:
    rows = [{"id": f"00000000-0000-4000-8000-00000000000{i}", "Label": str(i)} for i in (1, 2)]
    text = platform.write_insert_seed(
        tmp_path / "s.sql", "app.item", ["id", "Label"], rows, model=model
    ).path.read_text()
    assert text.count("INSERT INTO") == 1
    assert text.index("'1'") < text.index("'2'")


@pytest.mark.parametrize(
    ("columns", "row", "reason"),
    [
        (["id", "Label", "pk_item"], {"pk_item": 1}, "PostgreSQL fills"),
        (["id", "Label", "nope"], {"nope": 1}, "has no column"),
        (["id", "Label"], {"extra": 1}, "not among the columns"),
        (["id", "Label", "note"], {"note": ["a"]}, "neither an array nor JSON"),
    ],
    ids=["filled-by-postgresql", "unknown-column", "stray-key", "list-into-text"],
)
def test_a_seed_postgresql_would_refuse_is_refused_at_write_time(
    tmp_path, model, columns, row, reason
) -> None:
    full = {"id": "00000000-0000-4000-8000-000000000001", "Label": "x"} | row
    full = {k: v for k, v in full.items() if k in columns or k == "extra"}
    full = {"note": None, **full} if "note" in columns else full
    target = tmp_path / "bad.sql"
    with pytest.raises(platform.SeedError, match=reason):
        platform.write_copy_seed(target, "app.item", columns, [full], model=model)
    assert not target.exists()


def test_a_row_missing_a_column_is_refused(tmp_path, model) -> None:
    with pytest.raises(platform.SeedError, match="missing"):
        platform.write_copy_seed(
            tmp_path / "s.sql",
            "app.item",
            ["id", "Label", "note"],
            [{"id": "00000000-0000-4000-8000-000000000001", "Label": "x"}],
            model=model,
        )


def test_seeds_written_for_the_prep_seed_example_pass_static_validation(tmp_path) -> None:
    model = platform.parse_schema(EX06 / "db" / "schema")
    seeds = tmp_path / "seeds"
    seeds.mkdir()
    platform.write_copy_seed(
        seeds / "01_manufacturers.sql",
        "prep_seed.tb_manufacturer",
        ["id", "name", "country_code"],
        [
            {"id": "550e8400-e29b-41d4-a716-446655440000", "name": "Acme", "country_code": "US"},
            {"id": "550e8400-e29b-41d4-a716-446655440001", "name": "O'Brien", "country_code": "IE"},
        ],
        model=model,
    )
    report = platform.validate_seeds(seeds, schema_dir=EX06 / "db" / "schema", max_level=3)
    assert isinstance(report, platform.PrepSeedReport)
    assert report.violations == []
    assert report.scanned_files == [str(seeds / "01_manufacturers.sql")]


def test_levels_four_and_five_need_a_database() -> None:
    with pytest.raises(ValueError, match="database"):
        platform.validate_seeds(EX06 / "db" / "seeds" / "prep", schema_dir=EX06, max_level=4)
