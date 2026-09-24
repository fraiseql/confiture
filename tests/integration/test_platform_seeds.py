"""What the platform writes is what ``seed apply`` reads, value for value.

``seed apply`` ran each file through the driver's ``execute``, which cannot read
the data rows of a ``COPY … FROM stdin`` — so a COPY seed, ``seed convert``'s
output and every file ``--copy-format`` converted failed with a syntax error on
its first data row. And it refused any file whose text held ``BEGIN`` or
``COMMIT`` anywhere, data included, so a seeded sentence could stop a run. The
values here are the ones each escape exists for.
"""

from __future__ import annotations

from pathlib import Path

import psycopg
import pytest
from tests.unit.test_platform_leaks_no_driver_types import driver_objects
from typer.testing import CliRunner

from confiture import platform
from confiture.cli.main import app
from confiture.config.environment import SeedConfig

runner = CliRunner()

DDL = """
CREATE SCHEMA app;
CREATE TABLE app.item (
    pk_item BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id INT NOT NULL UNIQUE,
    label TEXT,
    active BOOLEAN,
    payload JSONB,
    tags TEXT[],
    blob BYTEA
);
"""

HARD = [
    "vertical\x0btab",
    "tab\there",
    "back\\slash",
    "new\nline",
    "carriage\rreturn",
    "\\N",
    "Begin; COMMIT; ROLLBACK",
    "it's",
    "",
    None,
]


def _rows() -> list[dict]:
    return [
        {
            "id": i,
            "label": text,
            "active": i % 2 == 0,
            "payload": {"i": i, "text": text},
            "tags": [text, "x"],
            "blob": (text or "").encode(),
        }
        for i, text in enumerate(HARD)
    ]


def _database(url: str) -> platform.SchemaModel:
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(DDL)
    return platform.parse_schema(DDL)


def _loaded(url: str) -> list[tuple]:
    with psycopg.connect(url) as conn:
        return conn.execute(
            "SELECT id, label, active, payload, tags, blob FROM app.item ORDER BY id"
        ).fetchall()


def _expected() -> list[tuple]:
    return [(r["id"], r["label"], r["active"], r["payload"], r["tags"], r["blob"]) for r in _rows()]


def test_seed_apply_reads_a_copy_block(fresh_database: str, tmp_path: Path) -> None:
    """A COPY seed as ``seed convert`` or ``pg_dump`` writes one, written by hand."""
    _database(fresh_database)
    (tmp_path / "01_items.sql").write_text(
        "-- two rows\nCOPY app.item (id, label) FROM stdin;\n1\tone\n2\t\\N\n\\.\n"
        "INSERT INTO app.item (id, label) VALUES (3, 'three');\n"
    )
    result = runner.invoke(
        app, ["seed", "apply", "--seeds-dir", str(tmp_path), "--database-url", fresh_database]
    )
    assert result.exit_code == 0, result.output
    assert [row[:2] for row in _loaded(fresh_database)] == [(1, "one"), (2, None), (3, "three")]


def test_a_transaction_word_in_the_data_is_data(fresh_database: str, tmp_path: Path) -> None:
    _database(fresh_database)
    (tmp_path / "01_items.sql").write_text(
        "INSERT INTO app.item (id, label) VALUES (1, 'Begin here, then commit.');\n"
    )
    result = runner.invoke(
        app, ["seed", "apply", "--seeds-dir", str(tmp_path), "--database-url", fresh_database]
    )
    assert result.exit_code == 0, result.output
    assert _loaded(fresh_database)[0][:2] == (1, "Begin here, then commit.")


def test_a_transaction_statement_is_still_refused(fresh_database: str, tmp_path: Path) -> None:
    _database(fresh_database)
    (tmp_path / "01_items.sql").write_text(
        "BEGIN;\nINSERT INTO app.item (id) VALUES (1);\nCOMMIT;\n"
    )
    result = runner.invoke(
        app, ["seed", "apply", "--seeds-dir", str(tmp_path), "--database-url", fresh_database]
    )
    assert result.exit_code != 0
    assert "transaction control" in result.output
    assert _loaded(fresh_database) == []


@pytest.mark.parametrize("writer", ["write_copy_seed", "write_insert_seed"])
def test_seed_apply_loads_what_the_platform_wrote(
    fresh_database: str, tmp_path: Path, writer: str
) -> None:
    model = _database(fresh_database)
    columns = ["id", "label", "active", "payload", "tags", "blob"]
    getattr(platform, writer)(tmp_path / "01_items.sql", "app.item", columns, _rows(), model=model)
    result = runner.invoke(
        app, ["seed", "apply", "--seeds-dir", str(tmp_path), "--database-url", fresh_database]
    )
    assert result.exit_code == 0, result.output
    assert _loaded(fresh_database) == _expected()


def test_copy_format_converts_and_loads(fresh_database: str, tmp_path: Path) -> None:
    """``--copy-format`` turned an INSERT file into COPY and then could not run it."""
    model = _database(fresh_database)
    columns = ["id", "label"]
    rows = [{"id": i, "label": f"row {i}"} for i in range(5)]
    platform.write_insert_seed(tmp_path / "01_items.sql", "app.item", columns, rows, model=model)
    result = runner.invoke(
        app,
        [
            "seed",
            "apply",
            "--seeds-dir",
            str(tmp_path),
            "--database-url",
            fresh_database,
            "--copy-format",
            "--copy-threshold",
            "1",
        ],
    )
    assert result.exit_code == 0, result.output
    with psycopg.connect(fresh_database) as conn:
        assert conn.execute("SELECT count(*) FROM app.item").fetchone() == (5,)


def test_apply_seeds_by_url_commits_the_run(fresh_database: str, tmp_path: Path) -> None:
    model = _database(fresh_database)
    platform.write_copy_seed(
        tmp_path / "01_items.sql",
        "app.item",
        ["id", "label"],
        [{"id": 1, "label": "a"}],
        model=model,
    )
    result = platform.apply_seeds(fresh_database, tmp_path)
    assert (result.total, result.succeeded, result.failed) == (1, 1, 0)
    assert driver_objects(result) == set()
    assert _loaded(fresh_database)[0][:2] == (1, "a")


def test_apply_seeds_by_url_is_all_or_nothing(fresh_database: str, tmp_path: Path) -> None:
    model = _database(fresh_database)
    platform.write_copy_seed(
        tmp_path / "01_items.sql",
        "app.item",
        ["id", "label"],
        [{"id": 1, "label": "a"}],
        model=model,
    )
    (tmp_path / "02_broken.sql").write_text("INSERT INTO app.item (id) VALUES (1);\n")
    with pytest.raises(platform.SeedError, match="02_broken"):
        platform.apply_seeds(fresh_database, tmp_path)
    assert _loaded(fresh_database) == []


def test_apply_seeds_can_keep_what_applied(fresh_database: str, tmp_path: Path) -> None:
    model = _database(fresh_database)
    platform.write_copy_seed(
        tmp_path / "01_items.sql",
        "app.item",
        ["id", "label"],
        [{"id": 1, "label": "a"}],
        model=model,
    )
    (tmp_path / "02_broken.sql").write_text("INSERT INTO app.item (id) VALUES (1);\n")
    result = platform.apply_seeds(fresh_database, tmp_path, continue_on_error=True)
    assert (result.succeeded, result.failed, result.failed_files) == (1, 1, ["02_broken.sql"])
    assert len(_loaded(fresh_database)) == 1


def test_apply_seeds_on_a_connection_leaves_the_transaction_to_the_caller(
    fresh_database: str, tmp_path: Path
) -> None:
    model = _database(fresh_database)
    seed = platform.write_copy_seed(
        tmp_path / "01_items.sql",
        "app.item",
        ["id", "label"],
        [{"id": 1, "label": "a"}],
        model=model,
    )
    with psycopg.connect(fresh_database) as conn:
        platform.apply_seeds(conn, [seed.path])
        assert conn.execute("SELECT count(*) FROM app.item").fetchone() == (1,)
        conn.rollback()
    assert _loaded(fresh_database) == []


def test_apply_seeds_refuses_a_connection_in_autocommit(
    fresh_database: str, tmp_path: Path
) -> None:
    """Refused before any file runs, and the mode is left as the caller set it."""
    model = _database(fresh_database)
    seed = platform.write_copy_seed(
        tmp_path / "01_items.sql", "app.item", ["id"], [{"id": 1}], model=model
    )
    with psycopg.connect(fresh_database, autocommit=True) as conn:
        with pytest.raises(platform.ConfigurationError, match="apply_seeds") as caught:
            platform.apply_seeds(conn, [seed.path])
        assert caught.value.error_code == "CONFIG_013"
        assert conn.autocommit is True
    assert _loaded(fresh_database) == []


def test_apply_seeds_records_the_profile_it_applied(fresh_database: str, tmp_path: Path) -> None:
    model = _database(fresh_database)
    for number in (1, 2):
        platform.write_copy_seed(
            tmp_path / f"0{number}_items.sql", "app.item", ["id"], [{"id": number}], model=model
        )
    lean = SeedConfig.model_validate({"profiles": {"lean": {"exclude": ["02_*"]}}})
    result = platform.apply_seeds(fresh_database, tmp_path, profile=lean.get_profile("lean"))
    assert (result.total, result.seed_profile) == (1, "lean")
    assert platform.apply_seeds(fresh_database, tmp_path / "02_items.sql").seed_profile is None


def test_an_insert_seed_of_no_rows_applies(fresh_database: str, tmp_path: Path) -> None:
    model = _database(fresh_database)
    for write in (platform.write_copy_seed, platform.write_insert_seed):
        write(tmp_path / f"{write.__name__}.sql", "app.item", ["id"], [], model=model)
    result = platform.apply_seeds(fresh_database, tmp_path)
    assert (result.succeeded, result.failed) == (2, 0)
    assert _loaded(fresh_database) == []
