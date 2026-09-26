"""``seed apply --copy-format`` never trades a statement's meaning for speed.

A COPY cannot say ``ON CONFLICT``: converting ``INSERT … ON CONFLICT DO NOTHING``
turned a seed that re-applies cleanly into one that fails on its second run with a
duplicate key. A file is converted only when every statement in it can become COPY;
otherwise it runs as written, and the progress line says why.
"""

from __future__ import annotations

import json
from pathlib import Path

import psycopg
import pytest
from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()

ONE_STATEMENT = "INSERT INTO item (id, label) VALUES (1, 'a'), (2, 'b') ON CONFLICT DO NOTHING;\n"
TWO_STATEMENTS = (
    ONE_STATEMENT + "INSERT INTO item (id, label) VALUES (3, 'c') ON CONFLICT (id) DO NOTHING;\n"
)


def _apply(url: str, seeds: Path) -> tuple[int, dict, str]:
    result = runner.invoke(
        app,
        [
            "seed",
            "apply",
            "--seeds-dir",
            str(seeds),
            "--database-url",
            url,
            "--copy-format",
            "--copy-threshold",
            "1",
            "--format",
            "json",
        ],
    )
    return result.exit_code, json.loads(result.stdout), result.stderr


def _labels(url: str) -> list[tuple[int, str]]:
    with psycopg.connect(url) as conn:
        return conn.execute("SELECT id, label FROM item ORDER BY id").fetchall()


@pytest.mark.parametrize(
    ("seed", "rows"),
    [
        pytest.param(ONE_STATEMENT, [(1, "a"), (2, "b")], id="one-statement"),
        pytest.param(TWO_STATEMENTS, [(1, "a"), (2, "b"), (3, "c")], id="two-statements"),
    ],
)
def test_an_on_conflict_seed_reapplies_under_copy_format(
    fresh_database: str, tmp_path: Path, seed: str, rows: list[tuple[int, str]]
) -> None:
    with psycopg.connect(fresh_database, autocommit=True) as conn:
        conn.execute("CREATE TABLE item (id INT PRIMARY KEY, label TEXT NOT NULL)")
    seeds = tmp_path / "seeds"
    seeds.mkdir()
    (seeds / "01_item.sql").write_text(seed)

    first = _apply(fresh_database, seeds)
    second = _apply(fresh_database, seeds)

    assert (first[0], first[1]["failed_files"]) == (0, [])
    assert (second[0], second[1]["failed_files"]) == (0, [])
    assert "ON CONFLICT" in second[2]
    assert _labels(fresh_database) == rows


def test_a_plain_insert_seed_is_still_converted(fresh_database: str, tmp_path: Path) -> None:
    with psycopg.connect(fresh_database, autocommit=True) as conn:
        conn.execute("CREATE TABLE item (id INT PRIMARY KEY, label TEXT NOT NULL)")
    seeds = tmp_path / "seeds"
    seeds.mkdir()
    (seeds / "01_item.sql").write_text("INSERT INTO item (id, label) VALUES (1, 'a'), (2, 'b');\n")

    code, payload, stderr = _apply(fresh_database, seeds)

    assert (code, payload["succeeded"]) == (0, 1)
    assert "(COPY)" in stderr
    assert _labels(fresh_database) == [(1, "a"), (2, "b")]
