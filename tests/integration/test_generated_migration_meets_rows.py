"""A generated migration never writes SQL that fails on the rows a table already holds (#766).

Each case builds the old tree into a throwaway database holding a row the new tree's
rule refuses, then generates the migration ``migrate diff --generate`` writes. A change
that existing rows can violate is written with a ``-- confiture:backfill`` placeholder:
``migrate up`` and ``migrate preflight`` refuse the file while it is there, and once the
author fills it in, the migration applies and the database is the new tree. A change
the database can satisfy alone (a declared ``DEFAULT``) applies as generated.
"""

import json
from dataclasses import dataclass
from pathlib import Path

import psycopg
import pytest
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.drift import SchemaDriftDetector
from confiture.core.migration_generator import MigrationGenerator
from confiture.platform import diff, parse_schema

runner = CliRunner()

_TABLE = (
    "CREATE TABLE tb_user (pk_user bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, "
    "id uuid NOT NULL, name text{extra});\n"
)
_SEED = "INSERT INTO tb_user (id, name) VALUES (gen_random_uuid(), 'abcdefgh');\n"


@dataclass(frozen=True)
class Case:
    new_columns: str
    fill: str | None
    seed: str = _SEED
    old_columns: str = ""


CASES = {
    "not_null_column": Case(", email text NOT NULL", "UPDATE tb_user SET email = 'x@example.com';"),
    "set_not_null": Case(
        "",
        "UPDATE tb_user SET name = '' WHERE name IS NULL;",
        seed="INSERT INTO tb_user (id) VALUES (gen_random_uuid());\n",
    ),
    "unique": Case(
        ", CONSTRAINT tb_user_name_key UNIQUE (name)",
        "DELETE FROM tb_user WHERE pk_user > (SELECT min(pk_user) FROM tb_user);",
        seed=_SEED + _SEED,
    ),
    "check": Case(
        ", CONSTRAINT tb_user_name_short CHECK (length(name) < 5)",
        "UPDATE tb_user SET name = left(name, 4);",
    ),
    "narrowing_retype": Case("", "UPDATE tb_user SET name = left(name, 5);"),
    "constant_default": Case(", email text NOT NULL DEFAULT ''", None),
    "volatile_default": Case(", token uuid NOT NULL DEFAULT gen_random_uuid()", None),
}


def _trees(case_name: str, case: Case) -> tuple[str, str]:
    old = _TABLE.format(extra=case.old_columns)
    if case_name == "set_not_null":
        return old, _TABLE.format(extra="").replace("name text", "name text NOT NULL")
    if case_name == "narrowing_retype":
        return old, _TABLE.format(extra="").replace("name text", "name varchar(5)")
    return old, _TABLE.format(extra=case.new_columns)


def _project(tmp_path: Path, url: str, old: str, new: str) -> tuple[Path, Path]:
    config = tmp_path / "local.yaml"
    config.write_text(f"name: test\ndatabase_url: {url}\n")
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    MigrationGenerator(migrations).generate_sql(
        diff(old, new), "change", version="20260101000000", destructive="allow"
    )
    return config, migrations


def _up_file(migrations: Path) -> Path:
    return migrations / "20260101000000_change.up.sql"


def _cli(command: str, migrations: Path, config: Path) -> tuple[int, dict]:
    result = runner.invoke(
        app,
        ["migrate", command, "--migrations-dir", str(migrations), "--config", str(config), "--format", "json"],
    )  # fmt: skip
    return result.exit_code, json.loads(result.output)


def _fill(migrations: Path, fill: str) -> None:
    """Replace each placeholder directive line with the author's SQL, as an author would."""
    up = _up_file(migrations)
    lines = up.read_text().splitlines()
    up.write_text(
        "\n".join(fill if line.startswith("-- confiture:backfill ") else line for line in lines)
        + "\n"
    )


def _drift(url: str, new: str) -> list[tuple[str, str]]:
    with psycopg.connect(url) as conn:
        report = SchemaDriftDetector(conn).compare_with_expected(parse_schema(new))
    return [(i.drift_type.value, i.object_name) for i in report.drift_items]


@pytest.mark.parametrize("case_name", sorted(CASES))
def test_a_generated_migration_meets_the_rows_it_finds(
    case_name: str, fresh_database: str, tmp_path: Path
) -> None:
    case = CASES[case_name]
    old, new = _trees(case_name, case)
    with psycopg.connect(fresh_database, autocommit=True) as conn:
        conn.execute(old)
        conn.execute(case.seed)
    config, migrations = _project(tmp_path, fresh_database, old, new)

    if case.fill is not None:
        code, payload = _cli("up", migrations, config)
        assert code == 5, payload
        assert payload["error"]["code"] == "VALID_010", payload
        _, report = _cli("preflight", migrations, config)
        assert [i["code"] for i in report["issues"] if i["code"] == "PFLIGHT_BACKFILL_PENDING"]
        _fill(migrations, case.fill)
    else:
        assert "confiture:backfill" not in _up_file(migrations).read_text()

    code, payload = _cli("up", migrations, config)
    assert code == 0, payload
    assert _drift(fresh_database, new) == []


def test_backfill_none_says_there_is_nothing_to_fix(fresh_database: str, tmp_path: Path) -> None:
    """On an empty table, ``-- confiture:backfill none`` lets the migration apply as written."""
    old, new = _trees("not_null_column", CASES["not_null_column"])
    with psycopg.connect(fresh_database, autocommit=True) as conn:
        conn.execute(old)
    config, migrations = _project(tmp_path, fresh_database, old, new)
    _fill(migrations, "-- confiture:backfill none")

    code, payload = _cli("up", migrations, config)

    assert code == 0, payload
    assert _drift(fresh_database, new) == []


def test_a_python_migration_is_refused_too(fresh_database: str, tmp_path: Path) -> None:
    """A generated ``.py`` migration carries its placeholders in ``backfill_pending``."""
    old, new = _trees("not_null_column", CASES["not_null_column"])
    with psycopg.connect(fresh_database, autocommit=True) as conn:
        conn.execute(old)
    config = tmp_path / "local.yaml"
    config.write_text(f"name: test\ndatabase_url: {fresh_database}\n")
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    MigrationGenerator(migrations).generate(
        diff(old, new), "change", version="20260101000000", destructive="allow"
    )

    code, payload = _cli("up", migrations, config)

    assert code == 5, payload
    assert payload["error"]["code"] == "VALID_010", payload
    assert "tb_user.email" in payload["error"]["message"]


#: The cases whose placeholder is followed by a constraint added ``NOT VALID`` and validated.
_VALIDATED = ("check", "not_null_column", "set_not_null")
_INDEX = "CREATE INDEX ix_tb_user_id ON tb_user (id);\n"


@pytest.mark.parametrize("case_name", _VALIDATED)
def test_a_non_transactional_migration_runs_again_once_the_rows_are_fixed(
    case_name: str, fresh_database: str, tmp_path: Path
) -> None:
    """Outside a transaction each statement commits; a retry after a failed VALIDATE applies (#785).

    The added index is written ``CONCURRENTLY``, so the file runs outside a
    transaction. The author's backfill misses the seeded row, ``VALIDATE`` fails
    after the ``ADD`` has committed, and once the row is fixed the same file runs
    to the end.
    """
    case = CASES[case_name]
    old, new = _trees(case_name, case)
    new += _INDEX
    with psycopg.connect(fresh_database, autocommit=True) as conn:
        conn.execute(old)
        conn.execute(case.seed)
    config, migrations = _project(tmp_path, fresh_database, old, new)
    assert "CONCURRENTLY" in _up_file(migrations).read_text()
    _fill(migrations, "-- confiture:backfill none")

    code, payload = _cli("up", migrations, config)
    assert code != 0, payload
    with psycopg.connect(fresh_database, autocommit=True) as conn:
        conn.execute(case.fill)

    code, payload = _cli("up", migrations, config)
    assert code == 0, payload
    assert _drift(fresh_database, new) == []
