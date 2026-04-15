"""Unit tests for `confiture generate alloc` CLI command.

Uses Typer's CliRunner — no database required.  Temporary directories
are created with pytest's ``tmp_path`` fixture.
"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()


def _make_schema(tmp_path: Path, *subdirs: str) -> tuple[Path, Path]:
    """Create schema_dir and an optional nested target dir.

    Returns ``(schema_dir, target_dir)`` where *target_dir* is the last
    sub-path created (or *schema_dir* itself when no subdirs supplied).
    """
    schema = tmp_path / "schema"
    schema.mkdir()
    target = schema
    for sub in subdirs:
        target = target / sub
        target.mkdir()
    return schema, target


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


class TestAllocHappyPath:
    """Tests for successful `generate alloc` invocations."""

    def test_prints_filename_for_empty_dir(self, tmp_path: Path) -> None:
        schema, target = _make_schema(tmp_path, "functions")

        result = runner.invoke(
            app,
            ["generate", "alloc", str(target), "--schema-dir", str(schema)],
        )

        assert result.exit_code == 0
        assert "00001.sql" in result.stdout

    def test_prints_next_filename_after_existing(self, tmp_path: Path) -> None:
        schema, target = _make_schema(tmp_path, "functions")
        (target / "00001_create.sql").touch()
        (target / "00002_update.sql").touch()

        result = runner.invoke(
            app,
            ["generate", "alloc", str(target), "--schema-dir", str(schema)],
        )

        assert result.exit_code == 0
        assert "00003.sql" in result.stdout

    def test_verb_included_in_filename(self, tmp_path: Path) -> None:
        schema, target = _make_schema(tmp_path, "functions")

        result = runner.invoke(
            app,
            [
                "generate",
                "alloc",
                str(target),
                "--schema-dir",
                str(schema),
                "--verb",
                "create",
            ],
        )

        assert result.exit_code == 0
        assert "00001_create.sql" in result.stdout

    def test_json_output_structure(self, tmp_path: Path) -> None:
        schema, target = _make_schema(tmp_path, "functions")

        result = runner.invoke(
            app,
            [
                "generate",
                "alloc",
                str(target),
                "--schema-dir",
                str(schema),
                "--json",
            ],
        )

        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert "path" in data
        assert data["path"].endswith("00001.sql")

    def test_json_output_contains_absolute_path(self, tmp_path: Path) -> None:
        schema, target = _make_schema(tmp_path, "functions")

        result = runner.invoke(
            app,
            [
                "generate",
                "alloc",
                str(target),
                "--schema-dir",
                str(schema),
                "--json",
            ],
        )

        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert Path(data["path"]).is_absolute()

    def test_json_with_verb(self, tmp_path: Path) -> None:
        schema, target = _make_schema(tmp_path, "functions", "catalog")
        (target / "03321_create.sql").touch()

        result = runner.invoke(
            app,
            [
                "generate",
                "alloc",
                str(target),
                "--schema-dir",
                str(schema),
                "--verb",
                "update",
                "--json",
            ],
        )

        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["path"].endswith("03322_update.sql")

    def test_nested_subtree(self, tmp_path: Path) -> None:
        schema, target = _make_schema(tmp_path, "functions", "catalog", "manufacturer")
        (target / "00010_create.sql").touch()

        result = runner.invoke(
            app,
            ["generate", "alloc", str(target), "--schema-dir", str(schema)],
        )

        assert result.exit_code == 0
        assert "00011.sql" in result.stdout

    def test_hex_scheme_auto_detected(self, tmp_path: Path) -> None:
        schema, target = _make_schema(tmp_path, "functions")
        (target / "0001a_create.sql").touch()
        (target / "0001b_update.sql").touch()

        result = runner.invoke(
            app,
            ["generate", "alloc", str(target), "--schema-dir", str(schema)],
        )

        assert result.exit_code == 0
        assert "0001c.sql" in result.stdout

    def test_output_is_deterministic(self, tmp_path: Path) -> None:
        schema, target = _make_schema(tmp_path, "functions")
        (target / "00005_create.sql").touch()

        first = runner.invoke(
            app,
            ["generate", "alloc", str(target), "--schema-dir", str(schema), "--json"],
        )
        second = runner.invoke(
            app,
            ["generate", "alloc", str(target), "--schema-dir", str(schema), "--json"],
        )

        assert json.loads(first.stdout)["path"] == json.loads(second.stdout)["path"]


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


class TestAllocErrorPaths:
    """Tests for `generate alloc` validation failures."""

    def test_nonexistent_target_exits_1(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        schema.mkdir()
        target = schema / "does_not_exist"

        result = runner.invoke(
            app,
            ["generate", "alloc", str(target), "--schema-dir", str(schema)],
        )

        assert result.exit_code == 1

    def test_target_outside_schema_root_exits_1(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        schema.mkdir()
        outside = tmp_path / "other"
        outside.mkdir()

        result = runner.invoke(
            app,
            ["generate", "alloc", str(outside), "--schema-dir", str(schema)],
        )

        assert result.exit_code == 1

    def test_error_message_on_nonexistent_dir(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        schema.mkdir()
        target = schema / "missing"

        result = runner.invoke(
            app,
            ["generate", "alloc", str(target), "--schema-dir", str(schema)],
        )

        assert result.exit_code == 1
        assert "does not exist" in result.stdout

    def test_error_message_on_outside_schema(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        schema.mkdir()
        outside = tmp_path / "other"
        outside.mkdir()

        result = runner.invoke(
            app,
            ["generate", "alloc", str(outside), "--schema-dir", str(schema)],
        )

        assert result.exit_code == 1
        assert "not within schema root" in result.stdout
