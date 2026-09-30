"""An explicit renumber that changes the build order says so (#538).

Moving ``005_e`` to ``002_e`` is how a file is made to build earlier, so the move is
not refused. It is reported: the files it now builds before or after, so a reorder
nobody meant (a sibling directory that sorts in between) is seen. ``--compact``,
whose promise is to keep the order, refuses one instead (``VALID_005``).
"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.tree_renumber import TreeRenumber


def _schema(tmp_path: Path, *files: str) -> Path:
    schema = tmp_path / "db/schema"
    for name in files:
        path = schema / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"-- {name}\n")
    return schema


def _move(schema: Path, old: str, new: str):
    renumber = TreeRenumber(schema)
    return renumber.execute(renumber.build_plans(schema / old, schema / new))


def _names(paths: tuple[Path, ...], schema: Path) -> list[str]:
    return [p.relative_to(schema.resolve()).as_posix() for p in paths]


def test_a_move_that_builds_a_file_earlier_names_what_it_now_precedes(tmp_path: Path) -> None:
    schema = _schema(tmp_path, "x/001_a.sql", "x/003_c.sql", "x/004_d.sql", "x/005_e.sql")

    result = _move(schema, "x/005_e.sql", "x/002_e.sql")

    (change,) = result.reordered
    assert change.new_path.name == "002_e.sql"
    assert _names(change.now_before, schema) == ["x/003_c.sql", "x/004_d.sql"]
    assert change.now_after == ()


def test_a_move_that_builds_a_file_later_names_what_it_now_follows(tmp_path: Path) -> None:
    schema = _schema(tmp_path, "x/001_a.sql", "x/002_b.sql", "x/003_c.sql")

    (change,) = _move(schema, "x/001_a.sql", "x/005_a.sql").reordered

    assert change.now_before == ()
    assert _names(change.now_after, schema) == ["x/002_b.sql", "x/003_c.sql"]


def test_a_move_that_keeps_the_order_reports_nothing(tmp_path: Path) -> None:
    schema = _schema(tmp_path, "x/001_a.sql", "x/005_e.sql")

    assert _move(schema, "x/005_e.sql", "x/006_e.sql").reordered == []


def test_a_sibling_directory_that_sorts_in_between_is_named(tmp_path: Path) -> None:
    """The accidental reorder the issue feared: ``02x/`` sorts between ``05_c`` and ``02_c``."""
    schema = _schema(tmp_path, "t/01_a.sql", "t/02x/y.sql", "t/05_c.sql")

    (change,) = _move(schema, "t/05_c.sql", "t/02_c.sql").reordered

    assert _names(change.now_before, schema) == ["t/02x/y.sql"]


def test_the_cli_reports_it_in_json_and_text(tmp_path: Path) -> None:
    schema = _schema(tmp_path, "x/001_a.sql", "x/003_c.sql", "x/005_e.sql")
    argv = [
        "generate",
        "renumber",
        str(schema / "x/005_e.sql"),
        str(schema / "x/002_e.sql"),
        "--schema-dir",
        str(schema),
        "--migrations-dir",
        str(tmp_path / "db/migrations"),
        "--dry-run",
    ]

    as_json = CliRunner().invoke(app, [*argv, "--json"])
    as_text = CliRunner().invoke(app, argv, terminal_width=200)

    assert as_json.exit_code == 0, as_json.output
    (change,) = json.loads(as_json.stdout)["reordered"]
    assert Path(change["new"]).name == "002_e.sql"
    assert [Path(p).name for p in change["now_before"]] == ["003_c.sql"]
    assert "now builds before" in as_text.stdout
    assert (schema / "x/005_e.sql").exists()
