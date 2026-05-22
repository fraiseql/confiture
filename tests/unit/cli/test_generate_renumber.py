"""Unit tests for `confiture generate renumber` CLI command.

Uses Typer's CliRunner — no database required.
"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()


def _schema(tmp_path: Path) -> tuple[Path, Path]:
    schema = tmp_path / "schema"
    funcs = schema / "functions"
    funcs.mkdir(parents=True)
    return schema, funcs


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


class TestRenumberHappyPath:
    def test_moves_file(self, tmp_path: Path) -> None:
        schema, funcs = _schema(tmp_path)
        old = funcs / "00001_create_item.sql"
        old.write_text("SELECT 1;")
        new = funcs / "00005_create_item.sql"

        result = runner.invoke(
            app,
            [
                "generate",
                "renumber",
                str(old),
                str(new),
                "--schema-dir",
                str(schema),
            ],
        )

        assert result.exit_code == 0, result.output
        assert new.exists()
        assert not old.exists()

    def test_dry_run_no_disk_changes(self, tmp_path: Path) -> None:
        schema, funcs = _schema(tmp_path)
        old = funcs / "00001_create_item.sql"
        old.write_text("SELECT 1;")
        new = funcs / "00005_create_item.sql"

        result = runner.invoke(
            app,
            [
                "generate",
                "renumber",
                str(old),
                str(new),
                "--schema-dir",
                str(schema),
                "--dry-run",
            ],
        )

        assert result.exit_code == 0, result.output
        assert old.exists()
        assert not new.exists()

    def test_json_output_structure(self, tmp_path: Path) -> None:
        schema, funcs = _schema(tmp_path)
        old = funcs / "00001_create_item.sql"
        old.write_text("SELECT 1;")
        new = funcs / "00005_create_item.sql"

        result = runner.invoke(
            app,
            [
                "generate",
                "renumber",
                str(old),
                str(new),
                "--schema-dir",
                str(schema),
                "--json",
            ],
        )

        assert result.exit_code == 0, result.output
        data = json.loads(result.stdout)
        assert "moves" in data
        assert "ref_rewrites" in data
        assert "dangling_refs" in data

    def test_json_moves_list(self, tmp_path: Path) -> None:
        schema, funcs = _schema(tmp_path)
        old = funcs / "00001_create_item.sql"
        old.write_text("SELECT 1;")
        new = funcs / "00005_create_item.sql"

        result = runner.invoke(
            app,
            [
                "generate",
                "renumber",
                str(old),
                str(new),
                "--schema-dir",
                str(schema),
                "--json",
            ],
        )

        data = json.loads(result.stdout)
        assert len(data["moves"]) == 1
        assert data["moves"][0]["old"].endswith("00001_create_item.sql")
        assert data["moves"][0]["new"].endswith("00005_create_item.sql")

    def test_dry_run_json_shows_would_move(self, tmp_path: Path) -> None:
        schema, funcs = _schema(tmp_path)
        old = funcs / "00001_create_item.sql"
        old.write_text("SELECT 1;")
        new = funcs / "00005_create_item.sql"

        result = runner.invoke(
            app,
            [
                "generate",
                "renumber",
                str(old),
                str(new),
                "--schema-dir",
                str(schema),
                "--dry-run",
                "--json",
            ],
        )

        assert result.exit_code == 0, result.output
        data = json.loads(result.stdout)
        assert len(data["moves"]) == 1

    def test_subtree_moves_all_files(self, tmp_path: Path) -> None:
        schema, funcs = _schema(tmp_path)
        src = funcs / "catalog"
        src.mkdir()
        dst = funcs / "public"
        dst.mkdir()
        (src / "00001_create.sql").write_text("SELECT 1;")
        (src / "00002_update.sql").write_text("SELECT 2;")

        result = runner.invoke(
            app,
            [
                "generate",
                "renumber",
                str(src),
                str(dst),
                "--schema-dir",
                str(schema),
            ],
        )

        assert result.exit_code == 0, result.output
        assert len(list(dst.glob("*.sql"))) == 2

    def test_ref_rewrite_reported_in_json(self, tmp_path: Path) -> None:
        schema, funcs = _schema(tmp_path)
        old = funcs / "00001_create_item.sql"
        old.write_text("SELECT 1;")
        other = funcs / "00002_wrapper.sql"
        other.write_text("SELECT create_item();")
        new = funcs / "00003_update_item.sql"

        result = runner.invoke(
            app,
            [
                "generate",
                "renumber",
                str(old),
                str(new),
                "--schema-dir",
                str(schema),
                "--json",
            ],
        )

        assert result.exit_code == 0, result.output
        data = json.loads(result.stdout)
        assert len(data["ref_rewrites"]) == 1


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


class TestRenumberErrorPaths:
    def test_nonexistent_source_exits_1(self, tmp_path: Path) -> None:
        schema, funcs = _schema(tmp_path)
        old = funcs / "00001_missing.sql"
        new = funcs / "00002_missing.sql"

        result = runner.invoke(
            app,
            [
                "generate",
                "renumber",
                str(old),
                str(new),
                "--schema-dir",
                str(schema),
            ],
        )

        assert result.exit_code == 1, result.output

    def test_dangling_refs_exit_2(self, tmp_path: Path) -> None:
        schema, funcs = _schema(tmp_path)
        old = funcs / "00001_create_item.sql"
        old.write_text("SELECT 1;")
        # String literal that won't be rewritten
        other = funcs / "00002_dynamic.sql"
        other.write_text("EXECUTE 'SELECT create_item()';")
        new = funcs / "00003_update_item.sql"

        result = runner.invoke(
            app,
            [
                "generate",
                "renumber",
                str(old),
                str(new),
                "--schema-dir",
                str(schema),
            ],
        )

        assert result.exit_code == 2, result.output
