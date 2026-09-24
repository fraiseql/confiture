"""A seeds directory is a tree: what one command reads, every command reads (#386).

Level 1 scanned ``seeds/sub/010_widget.sql`` while level 5 listed the top level
only, so a nested seed was checked and never executed — and its missing table
never reported. ``apply_seeds`` loaded the top level of the tree
``validate_seeds`` read whole. Both now read the tree the build reads, through
``builder.files_under``.
"""

from __future__ import annotations

from pathlib import Path

import psycopg
import pytest
from typer.testing import CliRunner

from confiture import platform
from confiture.cli.main import app

SCHEMA_DDL = """
CREATE SCHEMA prep_seed;
CREATE SCHEMA catalog;
CREATE TABLE prep_seed.tb_widget (id UUID PRIMARY KEY, name TEXT);
CREATE TABLE catalog.tb_widget (
    pk_widget BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id UUID NOT NULL UNIQUE,
    name TEXT
);
"""

# The table this seed writes does not exist: level 5 must say so.
MISSING_TABLE_SEED = (
    "INSERT INTO prep_seed.tb_gadget (id, name) "
    "VALUES ('00000000-0000-0000-0000-000000000001', 'x');\n"
)


def _schema(tmp_path: Path) -> Path:
    schema = tmp_path / "schema"
    schema.mkdir()
    (schema / "10_tables.sql").write_text(SCHEMA_DDL)
    return schema


@pytest.fixture
def built(fresh_database: str, tmp_path: Path) -> str:
    with psycopg.connect(fresh_database) as conn:
        conn.execute(SCHEMA_DDL)
    return fresh_database


@pytest.mark.parametrize("where", ["010_widget.sql", "sub/010_widget.sql"])
def test_level_5_executes_the_seed_level_1_scanned(built: str, tmp_path: Path, where: str) -> None:
    seeds = tmp_path / "seeds"
    (seeds / where).parent.mkdir(parents=True, exist_ok=True)
    (seeds / where).write_text(MISSING_TABLE_SEED)

    report = platform.validate_seeds(
        seeds, schema_dir=_schema(tmp_path), max_level=5, database=built
    )

    assert [v.message for v in report.violations if "tb_gadget" in v.message], report.violations


def test_apply_seeds_applies_a_nested_file(built: str, tmp_path: Path) -> None:
    seeds = tmp_path / "seeds"
    (seeds / "sub").mkdir(parents=True)
    (seeds / "sub" / "010_widget.sql").write_text(
        "INSERT INTO prep_seed.tb_widget (id, name) "
        "VALUES ('00000000-0000-0000-0000-000000000001', 'nested');\n"
    )

    result = platform.apply_seeds(built, seeds)

    assert result.total == 1
    with psycopg.connect(built) as conn:
        assert conn.execute("SELECT name FROM prep_seed.tb_widget").fetchall() == [("nested",)]


def test_apply_seeds_refuses_a_missing_directory(built: str, tmp_path: Path) -> None:
    with pytest.raises(platform.SeedError, match="not found"):
        platform.apply_seeds(built, tmp_path / "nope")


def test_seed_apply_applies_a_nested_file(built: str, tmp_path: Path) -> None:
    seeds = tmp_path / "seeds"
    (seeds / "sub").mkdir(parents=True)
    (seeds / "sub" / "010_widget.sql").write_text(
        "INSERT INTO prep_seed.tb_widget (id, name) "
        "VALUES ('00000000-0000-0000-0000-000000000002', 'by-cli');\n"
    )

    result = CliRunner().invoke(
        app, ["seed", "apply", "--seeds-dir", str(seeds), "--database-url", built]
    )

    assert result.exit_code == 0, result.output
    with psycopg.connect(built) as conn:
        assert conn.execute("SELECT name FROM prep_seed.tb_widget").fetchall() == [("by-cli",)]
