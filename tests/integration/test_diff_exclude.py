"""``diff.exclude`` / ``--exclude`` leave the relations another tool owns out of a comparison (#767).

A runtime that creates its own bookkeeping tables at boot (FraiseQL's ``_fraiseql_*``)
has a database the tree never declares in full: without an exclusion, every one of
its tables is drift, and ``migrate diff --from db`` generates a ``DROP`` for it.
"""

import json
from collections.abc import Callable
from pathlib import Path

import psycopg
import pytest
from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()

TREE = "CREATE TABLE app_user (id BIGINT PRIMARY KEY, email TEXT NOT NULL);\n"

OTHER_TOOL = """
CREATE TABLE _fraiseql_meta (id SERIAL PRIMARY KEY, k TEXT UNIQUE, v JSONB);
CREATE INDEX _fraiseql_meta_v ON _fraiseql_meta USING gin (v);
CREATE TABLE _fraiseql_cron_state (job TEXT PRIMARY KEY, ran_at TIMESTAMPTZ);
"""


@pytest.fixture
def project(fresh_database_factory: Callable[[str], str], tmp_path: Path) -> tuple[Path, Path]:
    """A database holding the tree and another tool's tables; its config and the tree."""
    url = fresh_database_factory("confiture_exclude")
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(TREE + OTHER_TOOL)
    tree = tmp_path / "schema.sql"
    tree.write_text(TREE)
    config = tmp_path / "local.yaml"
    config.write_text(f"name: test\ndatabase_url: {url}\n")
    return config, tree


def _diff(config: Path, tree: Path, *extra: str) -> dict:
    result = runner.invoke(
        app,
        ["migrate", "diff", "--from", "db", "--to", str(tree), "--config", str(config),
         "--format", "json", *extra],
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


def _named(payload: dict) -> str:
    return json.dumps(payload["changes"])


class TestMigrateDiff:
    def test_without_an_exclusion_the_other_tools_tables_are_dropped(
        self, project: tuple[Path, Path]
    ) -> None:
        payload = _diff(*project)
        assert "_fraiseql_meta" in _named(payload)
        assert "_fraiseql_cron_state" in _named(payload)

    def test_the_option_leaves_them_out(self, project: tuple[Path, Path]) -> None:
        payload = _diff(*project, "--exclude", "_fraiseql_*")
        assert payload["changes"] == [], payload["changes"]

    def test_a_qualified_pattern_matches_its_schema_only(self, project: tuple[Path, Path]) -> None:
        payload = _diff(*project, "--exclude", "public._fraiseql_meta")
        assert "_fraiseql_meta" not in _named(payload)
        assert "_fraiseql_cron_state" in _named(payload)

    def test_a_pattern_of_another_schema_leaves_nothing_out(
        self, project: tuple[Path, Path]
    ) -> None:
        payload = _diff(*project, "--exclude", "other._fraiseql_*")
        assert "_fraiseql_meta" in _named(payload)

    def test_the_config_key_leaves_them_out_and_the_option_adds_to_it(
        self, project: tuple[Path, Path]
    ) -> None:
        config, tree = project
        config.write_text(config.read_text() + "diff:\n  exclude:\n    - _fraiseql_meta\n")
        assert "_fraiseql_meta" not in _named(_diff(config, tree))
        assert "_fraiseql_cron_state" in _named(_diff(config, tree))
        assert _diff(config, tree, "--exclude", "_fraiseql_cron_*")["changes"] == []

    def test_a_tree_object_on_an_excluded_relation_is_said(
        self, project: tuple[Path, Path]
    ) -> None:
        config, tree = project
        tree.write_text(
            TREE
            + "CREATE TABLE note (id BIGINT PRIMARY KEY, meta INT REFERENCES _fraiseql_meta);\n"
        )
        payload = _diff(config, tree, "--exclude", "_fraiseql_*")
        assert [w["code"] for w in payload["warnings"]] == ["DIFFER_411"]
        assert "note" in payload["warnings"][0]["message"]


class TestDrift:
    def _drift(self, config: Path, tree: Path, *extra: str, exit_code: int = 0) -> dict:
        result = runner.invoke(
            app,
            ["drift", "--config", str(config), "--schema", str(tree), "--format", "json",
             "--fail-on-warning", *extra],
        )  # fmt: skip
        assert result.exit_code == exit_code, result.output
        return json.loads(result.stdout)

    def test_without_an_exclusion_they_are_extra(self, project: tuple[Path, Path]) -> None:
        assert "_fraiseql_meta" in json.dumps(self._drift(*project, exit_code=1)["drift_items"])

    def test_the_option_leaves_them_out(self, project: tuple[Path, Path]) -> None:
        payload = self._drift(*project, "--exclude", "_fraiseql_*")
        assert payload["drift_items"] == [], payload["drift_items"]

    def test_the_config_key_leaves_them_out(self, project: tuple[Path, Path]) -> None:
        config, tree = project
        config.write_text(config.read_text() + "diff:\n  exclude: ['_fraiseql_*']\n")
        assert self._drift(config, tree)["drift_items"] == []


class TestValidateLiveDrift:
    def _validate(self, config: Path, tree: Path, *extra: str) -> str:
        result = runner.invoke(
            app,
            ["migrate", "validate", "--check-live-drift", "--config", str(config),
             "--schema", str(tree), "--format", "json", *extra],
        )  # fmt: skip
        assert result.exit_code == 0, result.output
        return result.stdout

    def test_the_option_leaves_them_out(self, project: tuple[Path, Path]) -> None:
        assert "_fraiseql_meta" in self._validate(*project)
        assert "_fraiseql_meta" not in self._validate(*project, "--exclude", "_fraiseql_*")

    def test_the_option_needs_the_check(self, project: tuple[Path, Path]) -> None:
        config, _tree = project
        result = runner.invoke(
            app, ["migrate", "validate", "--config", str(config), "--exclude", "_fraiseql_*"]
        )
        assert result.exit_code == 5, result.output
        assert "--exclude requires --check-live-drift" in result.output
