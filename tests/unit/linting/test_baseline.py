"""`lint --baseline`: adopt a rule without a flag day (#219, Phase 07).

A baseline records the identity of every finding a schema has today —
``rule_id``, object kind and qualified name, plus the file for file-scoped
rules, never a line number — and a later run fails only on identities the
file does not know, printing only those. When a rule's set shrinks the file
is rewritten (D12), so the ratchet only ever tightens; ``--write-baseline``
creates or resets it.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.linting.baseline import Baseline, identity
from confiture.core.linting.schema_linter import LintViolation, RuleSeverity

BASELINE = ".confiture-lint-baseline.json"


def _violation(rule: str, kind: str, name: str, *, line: int = 1, file: str | None = None):
    return LintViolation(
        rule_id=rule,
        rule_name=rule,
        severity=RuleSeverity.INFO,
        object_type=kind,
        object_name=name,
        message="m",
        line_number=line,
        file_path=file,
    )


class TestIdentity:
    def test_identity_is_rule_kind_and_qualified_name_never_the_line(self) -> None:
        a = _violation("doc_001", "table", "tenant.tb_x", line=3)
        b = _violation("doc_001", "table", "tenant.tb_x", line=40)
        assert identity(a) == identity(b) == "doc_001:table:tenant.tb_x"

    def test_file_scoped_findings_carry_their_file(self) -> None:
        v = _violation("build_001", "function", "app.f()", file="db/schema/010.sql")
        assert identity(v) == "build_001:function:app.f()@db/schema/010.sql"

    def test_diff_splits_new_known_and_fixed(self) -> None:
        base = Baseline.from_violations(
            [_violation("doc_001", "table", "a"), _violation("doc_001", "table", "b")]
        )
        current = [_violation("doc_001", "table", "b"), _violation("doc_001", "table", "c")]
        diff = base.diff(current)
        assert [identity(v) for v in diff.new] == ["doc_001:table:c"]
        assert diff.fixed == ["doc_001:table:a"]
        assert diff.known == 1

    def test_round_trip_through_json_sorts_identities_per_rule(self, tmp_path: Path) -> None:
        base = Baseline.from_violations(
            [
                _violation("pk_001", "table", "z"),
                _violation("doc_001", "table", "b"),
                _violation("doc_001", "table", "a"),
            ]
        )
        path = tmp_path / BASELINE
        base.write(path)
        data = json.loads(path.read_text())
        assert data == {
            "version": 1,
            "rules": {
                "doc_001": ["doc_001:table:a", "doc_001:table:b"],
                "pk_001": ["pk_001:table:z"],
            },
        }
        assert Baseline.load(path).identities == base.identities


_ENV = "database_url: postgresql://localhost/test\ninclude_dirs:\n  - path: db/schema\n"


def _table(name: str) -> str:
    return f"CREATE TABLE {name} (id INT PRIMARY KEY);\n"


@pytest.fixture
def project(tmp_path: Path) -> Iterator[Path]:
    """Three undocumented tables: doc_001 ×3 and nothing else."""
    (tmp_path / "db" / "schema").mkdir(parents=True)
    (tmp_path / "db" / "migrations").mkdir(parents=True)
    (tmp_path / "db" / "environments").mkdir(parents=True)
    (tmp_path / "db" / "environments" / "local.yaml").write_text(_ENV)
    (tmp_path / "db" / "schema" / "010_tables.sql").write_text(
        _table("tb_a") + _table("tb_b") + _table("tb_c")
    )
    old_cwd = Path.cwd()
    os.chdir(tmp_path)
    try:
        yield tmp_path
    finally:
        os.chdir(old_cwd)


def _lint(*args: str):  # type: ignore[no-untyped-def]
    return CliRunner().invoke(app, ["lint", *args])


def _schema(project: Path, sql: str) -> None:
    (project / "db" / "schema" / "010_tables.sql").write_text(sql)


def _stored(project: Path) -> list[str]:
    data = json.loads((project / BASELINE).read_text())
    return sorted(i for ids in data["rules"].values() for i in ids)


class TestBaselineCli:
    def test_write_baseline_records_identities_and_exits_zero(self, project: Path) -> None:
        result = _lint("--baseline", BASELINE, "--write-baseline")
        assert result.exit_code == 0, result.output
        assert _stored(project) == [
            "doc_001:table:tb_a",
            "doc_001:table:tb_b",
            "doc_001:table:tb_c",
        ]

    def test_a_rerun_against_the_baseline_is_silent_and_green(self, project: Path) -> None:
        _lint("--baseline", BASELINE, "--write-baseline")
        result = _lint("--baseline", BASELINE)
        assert result.exit_code == 0, result.output
        assert "doc_001" not in result.output
        assert "tb_a" not in result.output

    def test_a_new_finding_fails_and_is_the_only_one_printed(self, project: Path) -> None:
        _lint("--baseline", BASELINE, "--write-baseline")
        _schema(project, _table("tb_a") + _table("tb_b") + _table("tb_c") + _table("tb_d"))
        result = _lint("--baseline", BASELINE)
        assert result.exit_code == 1, result.output
        assert "tb_d" in result.output
        assert "tb_a" not in result.output and "tb_b" not in result.output

    def test_a_fixed_finding_shrinks_the_file(self, project: Path) -> None:
        _lint("--baseline", BASELINE, "--write-baseline")
        _schema(
            project,
            _table("tb_a") + _table("tb_b") + "COMMENT ON TABLE tb_b IS 'b';\n" + _table("tb_c"),
        )
        result = _lint("--baseline", BASELINE)
        assert result.exit_code == 0, result.output
        assert _stored(project) == ["doc_001:table:tb_a", "doc_001:table:tb_c"]

    def test_a_renamed_object_is_one_out_and_one_in_and_fails(self, project: Path) -> None:
        _lint("--baseline", BASELINE, "--write-baseline")
        _schema(project, _table("tb_a") + _table("tb_b") + _table("tb_renamed"))
        result = _lint("--baseline", BASELINE)
        assert result.exit_code == 1, result.output
        assert "tb_renamed" in result.output
        assert _stored(project) == ["doc_001:table:tb_a", "doc_001:table:tb_b"]

    def test_moving_lines_changes_nothing(self, project: Path) -> None:
        _lint("--baseline", BASELINE, "--write-baseline")
        _schema(
            project, "-- a long\n-- header\n\n" + _table("tb_c") + _table("tb_b") + _table("tb_a")
        )
        result = _lint("--baseline", BASELINE)
        assert result.exit_code == 0, result.output
        assert _stored(project) == [
            "doc_001:table:tb_a",
            "doc_001:table:tb_b",
            "doc_001:table:tb_c",
        ]

    def test_json_carries_new_fixed_and_known(self, project: Path) -> None:
        _lint("--baseline", BASELINE, "--write-baseline")
        _schema(project, _table("tb_a") + _table("tb_b") + _table("tb_d"))
        result = _lint("--baseline", BASELINE, "--format", "json")
        assert result.exit_code == 1, result.output
        payload = json.loads(result.stdout)
        assert payload["baseline"] == {
            "new": ["doc_001:table:tb_d"],
            "fixed": ["doc_001:table:tb_c"],
            "known": 2,
        }
        assert [i["location"] for i in payload["violations"]["items"]] == ["tb_d"]
        assert payload["violations"]["total"] == 1

    def test_json_without_a_baseline_has_no_baseline_key(self, project: Path) -> None:
        result = _lint("--format", "json")
        assert "baseline" not in json.loads(result.stdout)

    def test_a_malformed_baseline_is_a_config_error(self, project: Path) -> None:
        (project / BASELINE).write_text("{not json")
        result = _lint("--baseline", BASELINE, "--format", "json")
        assert result.exit_code == 5, result.output
        envelope = json.loads(result.stdout)
        assert envelope["ok"] is False
        assert envelope["error"]["code"].startswith("CONFIG_")
        assert BASELINE in envelope["error"]["message"]

    def test_write_baseline_needs_a_path(self, project: Path) -> None:
        result = _lint("--write-baseline")
        assert result.exit_code == 2, result.output

    def test_a_missing_baseline_file_without_write_is_a_config_error(self, project: Path) -> None:
        result = _lint("--baseline", "nope.json")
        assert result.exit_code == 5, result.output
