"""Tests for the Replica001ForwardCompat lint rule (issue #139, Phase 2)."""

from __future__ import annotations

from pathlib import Path

from confiture.core.linting.libraries.replica import Replica001ForwardCompat
from confiture.core.linting.schema_linter import RuleSeverity


def _mig(tmp_path: Path, name: str, body: str) -> None:
    (tmp_path / f"{name}.up.sql").write_text(body)


def test_unsafe_drop_column_flagged(tmp_path: Path) -> None:
    _mig(tmp_path, "20260531_1200_drop", "ALTER TABLE t DROP COLUMN c;")
    violations = Replica001ForwardCompat(has_replicas=True).check(tmp_path)
    assert len(violations) == 1
    assert violations[0].rule_id == "replica_001"
    assert violations[0].severity == RuleSeverity.ERROR
    assert "deprecate" in violations[0].message


def test_safe_add_nullable_no_violation(tmp_path: Path) -> None:
    _mig(tmp_path, "20260531_1200_add", "ALTER TABLE t ADD COLUMN c int;")
    assert Replica001ForwardCompat(has_replicas=True).check(tmp_path) == []


def test_concurrently_index_is_safe(tmp_path: Path) -> None:
    _mig(tmp_path, "m", "CREATE INDEX CONCURRENTLY idx ON t (c);")
    assert Replica001ForwardCompat(has_replicas=True).check(tmp_path) == []


def test_warns_by_default_without_replicas(tmp_path: Path) -> None:
    _mig(tmp_path, "20260531_1200_drop", "ALTER TABLE t DROP COLUMN c;")
    violations = Replica001ForwardCompat(has_replicas=False).check(tmp_path)
    assert len(violations) == 1
    assert violations[0].severity == RuleSeverity.WARNING


def test_bypass_downgrades(tmp_path: Path) -> None:
    _mig(tmp_path, "20260531_1200_drop", "ALTER TABLE t DROP COLUMN c;")
    violations = Replica001ForwardCompat(has_replicas=True, bypass=True).check(tmp_path)
    assert violations[0].severity == RuleSeverity.WARNING


def test_create_table_no_violation(tmp_path: Path) -> None:
    _mig(tmp_path, "m", "CREATE TABLE t (id int);")
    assert Replica001ForwardCompat(has_replicas=True).check(tmp_path) == []


def test_rule_has_category_tag() -> None:
    assert Replica001ForwardCompat.category == "replica"


def test_empty_dir_no_violations(tmp_path: Path) -> None:
    assert Replica001ForwardCompat().check(tmp_path / "nope") == []
