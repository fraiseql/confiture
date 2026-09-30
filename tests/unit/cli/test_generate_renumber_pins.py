"""`confiture generate renumber`: pins and `--compact` (#538)."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()


def _project(tmp_path: Path, *files: str) -> Path:
    root = tmp_path / "project"
    (root / "db/migrations").mkdir(parents=True)
    (root / "pyproject.toml").write_text("")
    for name in files:
        path = root / "db/schema" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"-- {name}\n")
    return root


def _renumber(root: Path, *args: str):
    return runner.invoke(
        app,
        [
            "generate",
            "renumber",
            *args,
            "--schema-dir",
            str(root / "db/schema"),
            "--migrations-dir",
            str(root / "db/migrations"),
            "--json",
        ],
    )


def test_a_pinned_file_is_refused_even_with_force(tmp_path: Path) -> None:
    root = _project(tmp_path, "x/002_a.sql")
    (root / "db/migrations/20260101000000_m.py").write_text(
        "from pathlib import Path\n\n"
        "class M:\n"
        "    def up(self):\n"
        '        self.execute(Path("db/schema/x/002_a.sql").read_text())\n'
    )
    old, new = root / "db/schema/x/002_a.sql", root / "db/schema/x/001_a.sql"

    result = _renumber(root, str(old), str(new), "--force")

    assert result.exit_code == 5
    assert json.loads(result.stdout)["error"]["code"] == "VALID_003"
    assert old.exists()
    assert not new.exists()


def test_compact_closes_the_gaps(tmp_path: Path) -> None:
    root = _project(tmp_path, "t/01_a.sql", "t/02_b.sql", "t/05_c.sql", "t/07_d/01_x.sql")

    result = _renumber(root, "--compact", str(root / "db/schema/t"))

    assert result.exit_code == 0, result.output
    moves = [(Path(m["old"]).name, Path(m["new"]).name) for m in json.loads(result.stdout)["moves"]]
    assert moves == [("05_c.sql", "03_c.sql"), ("07_d", "04_d")]
    assert (root / "db/schema/t/04_d/01_x.sql").exists()


def test_compact_dry_run_moves_nothing(tmp_path: Path) -> None:
    root = _project(tmp_path, "t/01_a.sql", "t/05_c.sql")

    result = _renumber(root, "--compact", str(root / "db/schema/t"), "--dry-run")

    assert result.exit_code == 0, result.output
    assert len(json.loads(result.stdout)["moves"]) == 1
    assert (root / "db/schema/t/05_c.sql").exists()


def test_compact_takes_no_target(tmp_path: Path) -> None:
    root = _project(tmp_path, "t/01_a.sql")

    result = _renumber(root, "--compact", str(root / "db/schema/t"), str(root / "db/schema/u"))

    assert result.exit_code == 5
    assert "--compact" in json.loads(result.stdout)["error"]["message"]


def test_a_move_needs_a_target(tmp_path: Path) -> None:
    root = _project(tmp_path, "t/01_a.sql")

    result = _renumber(root, str(root / "db/schema/t/01_a.sql"))

    assert result.exit_code == 5
    assert "NEW_PATH" in json.loads(result.stdout)["error"]["message"]
