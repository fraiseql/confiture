"""`confiture lint --list-rules` / `--select` / `--ignore` (#150).

The three legacy per-rule flags stay, as documented aliases over the same
dispatch — #150 explicitly requires no breakage for 0.19.0 / 0.28.0 users, so
each one is pinned here against its `--select` equivalent rather than against a
hand-written expectation.

Every test builds a real project and chdirs into it: `SchemaLinter` resolves
`db/environments/<env>.yaml` from the working directory, so a test that skips
this silently borrows confiture's own `db/`.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()

_SCHEMA = """
CREATE TABLE BadName (
    id INT,
    userPassword TEXT
);
"""


@pytest.fixture
def lint_project(tmp_path: Path) -> Iterator[Path]:
    """A project whose schema trips naming_001, naming_002, pk_001, doc_001 and sec_001."""
    (tmp_path / "db" / "schema").mkdir(parents=True)
    (tmp_path / "db" / "migrations").mkdir(parents=True)
    (tmp_path / "db" / "environments").mkdir(parents=True)
    (tmp_path / "db" / "environments" / "local.yaml").write_text(
        "database_url: postgresql://localhost/test\ninclude_dirs:\n  - path: db/schema\n"
    )
    (tmp_path / "db" / "schema" / "010_tables.sql").write_text(_SCHEMA)

    old_cwd = Path.cwd()
    os.chdir(tmp_path)
    try:
        yield tmp_path
    finally:
        os.chdir(old_cwd)


def _lint(*args: str):  # type: ignore[no-untyped-def]
    return runner.invoke(app, ["lint", *args])


class TestListRules:
    def test_lists_every_rule_with_its_family_and_default_state(self, lint_project: Path) -> None:
        result = _lint("--list-rules")

        assert result.exit_code == 0, result.output
        for code in ("naming_001", "pk_001", "acl_001", "tenant_001", "replica_001", "sec_002"):
            assert code in result.output
        assert "security-definer" in result.output

    def test_does_not_advertise_rules_with_no_implementation(self, lint_project: Path) -> None:
        """`check_indexes` computes nothing and `check_constraints` has no code."""
        result = _lint("--list-rules")

        assert "fk_001" not in result.output
        assert "constraint" not in result.output.lower()

    def test_json_output_is_machine_readable(self, lint_project: Path) -> None:
        result = _lint("--list-rules", "--format", "json")

        payload = json.loads(result.stdout)
        assert payload["status"] == "ok"
        codes = [rule["code"] for rule in payload["rules"]]
        assert "replica_001" in codes
        replica = next(r for r in payload["rules"] if r["code"] == "replica_001")
        assert replica["family"] == "replica"
        assert replica["default_on"] is False
        assert replica["legacy_flag"] == "--replica-safe"

    def test_report_mode_never_fails_even_on_a_dirty_schema(self, lint_project: Path) -> None:
        """It prints a catalogue; the schema is not consulted."""
        result = _lint("--list-rules", "--fail-on-warning")

        assert result.exit_code == 0, result.output


class TestSelect:
    def test_selecting_one_family_suppresses_the_others(self, lint_project: Path) -> None:
        result = _lint("--select", "pk")

        assert "pk_001" in result.output
        assert "naming_001" not in result.output

    def test_selecting_a_single_code_runs_only_that_rule(self, lint_project: Path) -> None:
        result = _lint("--select", "naming_001")

        assert "naming_001" in result.output
        assert "naming_002" not in result.output

    def test_unknown_rule_exits_5_naming_the_valid_set(self, lint_project: Path) -> None:
        """Exit 5 is this repo's usage error; exit 2 is "tracking table absent"."""
        result = _lint("--select", "nameing")

        assert result.exit_code == 5, result.output
        assert "naming" in result.output

    def test_default_selector_keeps_the_usual_rules(self, lint_project: Path) -> None:
        selected = _lint("--select", "default")
        plain = _lint()

        assert selected.output == plain.output


class TestIgnore:
    def test_ignore_removes_a_rule_from_the_default_set(self, lint_project: Path) -> None:
        result = _lint("--ignore", "naming")

        assert "naming_001" not in result.output
        assert "pk_001" in result.output

    def test_ignore_wins_over_select(self, lint_project: Path) -> None:
        result = _lint("--select", "naming", "--ignore", "naming_001")

        assert "naming_001" not in result.output
        assert "naming_002" in result.output


class TestLegacyFlagsAreAliases:
    """0.19.0 / 0.28.0 invocations keep working, and mean what they always meant."""

    def test_replica_safe_equals_select_default_replica(self, lint_project: Path) -> None:
        legacy = _lint("--replica-safe")
        modern = _lint("--select", "default,replica")

        assert legacy.exit_code == modern.exit_code
        assert legacy.output == modern.output

    def test_check_tenant_isolation_equals_select_default_tenant(self, lint_project: Path) -> None:
        legacy = _lint("--check-tenant-isolation")
        modern = _lint("--select", "default,tenant")

        assert legacy.exit_code == modern.exit_code
        assert legacy.output == modern.output

    def test_check_security_definer_equals_select_default_security_definer(
        self, lint_project: Path
    ) -> None:
        legacy = _lint("--check-security-definer")
        modern = _lint("--select", "default,security-definer")

        assert legacy.exit_code == modern.exit_code
        assert legacy.output == modern.output

    def test_a_legacy_flag_still_runs_the_default_rules(self, lint_project: Path) -> None:
        """The flags add a family; they never replaced the default lint."""
        result = _lint("--replica-safe")

        assert "naming_001" in result.output
