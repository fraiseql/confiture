"""Level 1 reads each seed statement — an ``INSERT``'s rows and a ``COPY`` block's —
and judges a value by the column it is written to (#366, #387).

A regex over ``INSERT … VALUES`` text saw no ``COPY`` at all, stopped at the first
``)`` so rows 2..n of a multi-row ``INSERT`` were never read, and took any quoted
value holding a hyphen for a UUID. Each test below is one of those, inverted.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from confiture import platform
from confiture.core.seed.validation.prep_seed.level_1_seed_files import (
    Level1SeedValidator,
    is_uuid_text,
)
from confiture.core.seed.validation.prep_seed.models import (
    PrepSeedPattern,
    PrepSeedViolation,
    ViolationSeverity,
)

OK = "550e8400-e29b-41d4-a716-446655440000"
EX08 = Path(__file__).resolve().parents[4] / "examples" / "08-generated-seeds"

REGION_DDL = """
CREATE SCHEMA prep_seed;
CREATE TABLE prep_seed.tb_region (id UUID PRIMARY KEY, slug TEXT);
"""


def _patterns(violations: list[PrepSeedViolation]) -> list[PrepSeedPattern]:
    return [v.pattern for v in violations]


def _uuid(violations: list[PrepSeedViolation]) -> list[PrepSeedViolation]:
    return [v for v in violations if v.pattern == PrepSeedPattern.INVALID_UUID_FORMAT]


# --- #366: a COPY seed is read ------------------------------------------------


def test_the_issues_copy_example_yields_all_three_findings() -> None:
    copy = "COPY catalog.tb_product (id, fk_vendor, name) FROM stdin;\nnot-a-uuid\t1\tx\n\\.\n"
    found = Level1SeedValidator().validate_seed_file(copy, "b.sql")
    assert sorted(p.name for p in _patterns(found)) == [
        "INVALID_FK_NAMING",
        "INVALID_UUID_FORMAT",
        "PREP_SEED_TARGET_MISMATCH",
    ]
    (bad,) = _uuid(found)
    assert bad.line_number == 2
    assert "'not-a-uuid'" in bad.message


def test_a_copy_column_list_decides_which_field_is_which() -> None:
    copy = (
        "COPY prep_seed.tb_product (name, fk_vendor_id) FROM stdin;\n"
        f"not-a-uuid-but-a-name\t{OK}\n"
        "Wi-Fi Router\tbad\n"
        "\\.\n"
    )
    (bad,) = _uuid(Level1SeedValidator().validate_seed_file(copy, "p.sql"))
    assert "'bad'" in bad.message
    assert "fk_vendor_id" in bad.message
    assert bad.line_number == 3


def test_a_copy_null_is_null_not_a_value() -> None:
    copy = "COPY prep_seed.tb_product (id, fk_vendor_id) FROM stdin;\n" + f"{OK}\t\\N\n\\.\n"
    assert Level1SeedValidator().validate_seed_file(copy, "p.sql") == []


def test_every_row_of_a_copy_is_read() -> None:
    rows = "".join(f"{OK}\t{OK}\n" for _ in range(40)) + f"{OK}\tnope\n"
    copy = f"-- header\nCOPY prep_seed.tb_product (id, fk_vendor_id) FROM stdin;\n{rows}\\.\n"
    (bad,) = _uuid(Level1SeedValidator().validate_seed_file(copy, "p.sql"))
    assert bad.line_number == 43
    assert "row 41" in bad.message


def test_the_issues_insert_example_leaves_a_hyphenated_name_alone() -> None:
    ins = f"INSERT INTO prep_seed.tb_product (id, name) VALUES ('{OK}', 'Wi-Fi Router');"
    assert Level1SeedValidator().validate_seed_file(ins, "a.sql") == []


# --- #387: every row, and a UUID is a column type, not a hyphen ---------------


@pytest.mark.parametrize(
    ("values", "bad_row"),
    [
        (f"('{OK}', 'north-america')", None),
        (f"('{OK}', '2024-01-31')", None),
        (f"('{OK}', 'Smith-Jones')", None),
        (f"('not-a-uuid', 'a'), ('{OK}', 'b')", 1),
        (f"('{OK}', 'a'), ('not-a-uuid', 'b')", 2),
    ],
)
def test_the_issues_five_rows_inverted(tmp_path: Path, values: str, bad_row: int | None) -> None:
    schema = tmp_path / "schema"
    schema.mkdir()
    (schema / "region.sql").write_text(REGION_DDL)
    seeds = tmp_path / "seeds"
    seeds.mkdir()
    rows = values.replace("), (", "),\n    (")
    (seeds / "region.sql").write_text(
        f"INSERT INTO prep_seed.tb_region (id, slug) VALUES\n    {rows};\n"
    )

    report = platform.validate_seeds(seeds, schema_dir=schema, max_level=1)

    found = _uuid(report.violations)
    if bad_row is None:
        assert report.violations == []
        return
    (bad,) = found
    assert bad.severity == ViolationSeverity.ERROR
    assert f"row {bad_row}" in bad.message
    assert bad.line_number == 1 + bad_row


def test_every_row_of_an_insert_is_read_by_every_per_row_check() -> None:
    ins = (
        "INSERT INTO prep_seed.tb_product (id, fk_vendor_id, name) VALUES\n"
        f"  ('{OK}', '{OK}', 'a'),\n"
        f"  ('{OK}', '{OK}', 'b'),\n"
        f"  ('{OK}', 'europe-5001-3', 'c');\n"
    )
    (bad,) = _uuid(Level1SeedValidator().validate_seed_file(ins, "p.sql"))
    assert bad.line_number == 4
    assert "row 3" in bad.message
    assert "fk_vendor_id" in bad.message


def test_with_a_schema_a_uuid_is_whatever_column_the_schema_types_uuid() -> None:
    model = platform.parse_schema("CREATE TABLE prep_seed.tb_x (id TEXT, ref UUID, fk_y_id TEXT);")
    ins = "INSERT INTO prep_seed.tb_x (id, ref, fk_y_id) VALUES ('Wi-Fi', 'not-a-uuid', 'x');"
    validator = Level1SeedValidator(model)
    (bad,) = _uuid(validator.validate_seed_file(ins, "x.sql"))
    assert "prep_seed.tb_x.ref" in bad.message
    assert "typed uuid" in bad.message
    assert validator.uuid_basis == "schema"


def test_without_a_schema_the_convention_names_the_uuid_columns() -> None:
    ins = "INSERT INTO prep_seed.tb_x (id, ref, fk_y_id) VALUES ('Wi-Fi', 'not-a-uuid', 'x');"
    validator = Level1SeedValidator()
    found = _uuid(validator.validate_seed_file(ins, "x.sql"))
    assert sorted(v.message.split("'")[1] for v in found) == ["Wi-Fi", "x"]
    assert all("convention" in v.message for v in found)
    assert validator.uuid_basis == "convention"


def test_a_table_the_schema_does_not_hold_falls_back_to_the_convention() -> None:
    model = platform.parse_schema("CREATE TABLE prep_seed.tb_other (id UUID);")
    ins = "INSERT INTO prep_seed.tb_x (id) VALUES ('nope');"
    (bad,) = _uuid(Level1SeedValidator(model).validate_seed_file(ins, "x.sql"))
    assert "convention" in bad.message


def test_without_a_column_list_the_schema_gives_the_columns_in_order() -> None:
    model = platform.parse_schema("CREATE TABLE prep_seed.tb_x (name TEXT, id UUID);")
    ins = "INSERT INTO prep_seed.tb_x VALUES ('Wi-Fi', 'nope');"
    (bad,) = _uuid(Level1SeedValidator(model).validate_seed_file(ins, "x.sql"))
    assert "'nope'" in bad.message


def test_the_report_says_which_basis_level_1_used(tmp_path: Path) -> None:
    seeds = tmp_path / "seeds"
    seeds.mkdir()
    (seeds / "a.sql").write_text(f"INSERT INTO prep_seed.tb_region (id) VALUES ('{OK}');\n")
    alone = platform.validate_seeds(seeds, schema_dir=tmp_path / "absent", max_level=1)
    assert alone.uuid_basis == "convention"
    schema = tmp_path / "schema"
    schema.mkdir()
    (schema / "r.sql").write_text(REGION_DDL)
    typed = platform.validate_seeds(seeds, schema_dir=schema, max_level=1)
    assert typed.uuid_basis == "schema"
    assert typed.to_dict()["uuid_basis"] == "schema"


@pytest.mark.parametrize(
    "value",
    [
        OK,
        OK.upper(),
        OK.replace("-", ""),
        "{" + OK + "}",
        "550e-8400-e29b-41d4-a716-4466-5544-0000",
    ],
)
def test_a_uuid_is_what_postgresqls_uuid_input_accepts(value: str) -> None:
    assert is_uuid_text(value)


@pytest.mark.parametrize(
    "value",
    [
        "",
        "not-a-uuid",
        OK[:-1],
        OK + "0",
        "{" + OK,
        f" {OK}",
        "550e8-400-e29b-41d4-a716446655440000",
    ],
)
def test_what_postgresqls_uuid_input_refuses_is_not_a_uuid(value: str) -> None:
    assert not is_uuid_text(value)


# --- what level 1 cannot read is a finding ------------------------------------


def test_a_seed_file_postgresql_rejects_is_a_finding() -> None:
    sql = f"INSERT INTO prep_seed.tb_x (id) VALUES ('{OK}');\nINSERT INTO oops VALUES (;\n"
    (bad,) = Level1SeedValidator().validate_seed_file(sql, "x.sql")
    assert bad.pattern == PrepSeedPattern.SEED_UNPARSEABLE
    assert bad.severity == ViolationSeverity.ERROR
    assert bad.line_number == 2


def test_an_insert_select_is_reported_as_not_checked() -> None:
    sql = "INSERT INTO prep_seed.tb_x (id) SELECT gen_random_uuid();"
    (note,) = Level1SeedValidator().validate_seed_file(sql, "x.sql")
    assert note.pattern == PrepSeedPattern.SEED_NOT_CHECKED
    assert note.severity == ViolationSeverity.INFO
    assert "computed at run time" in note.message


def test_a_csv_copy_is_read_row_by_row() -> None:
    """The issue's example (#397): a CSV row is checked like a text one."""
    sql = (
        "COPY prep_seed.tb_region (id, slug) FROM stdin (FORMAT csv, HEADER);\n"
        "id,slug\n"
        'not-a-uuid,"north,\namerica"\n'
        f"{OK},europe\n"
        "\\.\n"
    )
    (bad,) = _uuid(Level1SeedValidator().validate_seed_file(sql, "x.sql"))
    assert bad.line_number == 3
    assert "'not-a-uuid'" in bad.message


def test_a_csv_row_of_the_wrong_width_is_a_finding_at_the_line_it_starts_on() -> None:
    sql = f'COPY prep_seed.tb_x (id) FROM stdin (FORMAT csv);\n"{OK}\n",x\n\\.\n'
    (bad,) = Level1SeedValidator().validate_seed_file(sql, "x.sql")
    assert bad.pattern == PrepSeedPattern.SEED_ROW_WIDTH
    assert bad.line_number == 2


def test_a_csv_copy_with_a_default_marker_is_reported_as_not_checked() -> None:
    sql = "COPY prep_seed.tb_x (id) FROM stdin (FORMAT csv, DEFAULT 'D');\nD\n\\.\n"
    (note,) = Level1SeedValidator().validate_seed_file(sql, "x.sql")
    assert note.pattern == PrepSeedPattern.SEED_NOT_CHECKED
    assert "DEFAULT" in note.message


def test_a_binary_copy_is_still_reported_as_not_checked() -> None:
    sql = "COPY prep_seed.tb_x (id) FROM stdin (FORMAT binary);\nnope\n\\.\n"
    (note,) = Level1SeedValidator().validate_seed_file(sql, "x.sql")
    assert note.pattern == PrepSeedPattern.SEED_NOT_CHECKED
    assert "binary" in note.message


def test_a_row_of_the_wrong_width_is_a_finding() -> None:
    sql = f"COPY prep_seed.tb_x (id, fk_y_id) FROM stdin;\n{OK}\n\\.\n"
    (bad,) = Level1SeedValidator().validate_seed_file(sql, "x.sql")
    assert bad.pattern == PrepSeedPattern.SEED_ROW_WIDTH
    assert bad.line_number == 2


def test_a_computed_value_is_not_judged() -> None:
    sql = "INSERT INTO prep_seed.tb_x (id) VALUES (gen_random_uuid()), (NULL), ('{OK}'::uuid);"
    found = Level1SeedValidator().validate_seed_file(sql.replace("{OK}", OK), "x.sql")
    assert found == []


def test_the_generated_seeds_example_is_read_table_by_table() -> None:
    report = platform.validate_seeds(
        EX08 / "db" / "seeds" / "prep", schema_dir=EX08 / "db" / "schema", max_level=1
    )
    assert report.violations == []
    assert report.rows_read == {"prep_seed.tb_vendor": 4, "prep_seed.tb_product": 12}
