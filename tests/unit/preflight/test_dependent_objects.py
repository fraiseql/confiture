"""Tests for the dependent-objects preflight check."""

from __future__ import annotations

import pytest

from confiture.models.preflight import (
    CorTarget,
    DependentAnalysisReport,
    DependentEntry,
    DependentObject,
)


class TestDependentObjectShape:
    def test_dependent_object_to_dict(self) -> None:
        dep = DependentObject(
            kind="view",
            schema="public",
            name="v_active_users",
            referenced_columns=("id", "email"),
        )
        assert dep.to_dict() == {
            "kind": "view",
            "schema": "public",
            "name": "v_active_users",
            "referenced_columns": ["id", "email"],
        }

    def test_dependent_object_without_columns(self) -> None:
        dep = DependentObject(kind="function", schema="public", name="f_x")
        assert dep.referenced_columns == ()
        assert dep.to_dict()["referenced_columns"] == []


class TestCorTargetShape:
    def test_target_qualified_name(self) -> None:
        t = CorTarget(
            kind="view",
            schema="public",
            name="v_users",
            source_file=None,
            source_line=None,
        )
        assert t.qualified == "public.v_users"


class TestDependentEntryShape:
    def test_blocking_when_dependents_non_empty_and_severity_error(self) -> None:
        entry = DependentEntry(
            target=CorTarget(
                kind="view", schema="public", name="v_users", source_file=None, source_line=None
            ),
            dependents=[DependentObject(kind="view", schema="public", name="v_x")],
            severity="error",
        )
        assert entry.is_blocking() is True

    def test_non_blocking_when_warn(self) -> None:
        entry = DependentEntry(
            target=CorTarget(
                kind="view", schema="public", name="v_users", source_file=None, source_line=None
            ),
            dependents=[DependentObject(kind="view", schema="public", name="v_x")],
            severity="info",
        )
        assert entry.is_blocking() is False

    def test_non_blocking_when_no_dependents(self) -> None:
        entry = DependentEntry(
            target=CorTarget(
                kind="view", schema="public", name="v_users", source_file=None, source_line=None
            ),
            dependents=[],
            severity="error",
        )
        assert entry.is_blocking() is False


class TestDependentAnalysisReportShape:
    def test_empty_report_has_no_blocking(self) -> None:
        report = DependentAnalysisReport(entries=[], status="ok")
        assert not report.has_blocking()

    def test_report_with_blocking_entry(self) -> None:
        entry = DependentEntry(
            target=CorTarget(
                kind="view", schema="public", name="v_x", source_file=None, source_line=None
            ),
            dependents=[DependentObject(kind="view", schema="public", name="v_y")],
            severity="error",
        )
        report = DependentAnalysisReport(entries=[entry], status="ok")
        assert report.has_blocking()
        assert report.to_dict()["entries"][0]["dependents"][0]["name"] == "v_y"

    def test_skipped_report(self) -> None:
        report = DependentAnalysisReport(
            entries=[], status="skipped", skip_reason="no_preflight_db"
        )
        d = report.to_dict()
        assert d["status"] == "skipped"
        assert d["skip_reason"] == "no_preflight_db"


# --- DependentObjectsChecker exercised against a fake cursor (no live DB) ---
class _FakeCursor:
    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows
        self.executed_sql: list[tuple[str, dict]] = []

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *a: object) -> None:
        return None

    def execute(self, sql: str, params: dict) -> None:
        self.executed_sql.append((sql, params))

    def fetchall(self) -> list[tuple]:
        return self._rows


class _FakeConnection:
    def __init__(self, rows: list[tuple]) -> None:
        self._cursor = _FakeCursor(rows)

    def cursor(self) -> _FakeCursor:
        return self._cursor


class TestDependentObjectsCheckerLogic:
    def test_view_target_with_no_dependents_returns_empty_entry(self) -> None:
        from confiture.core.dependent_objects import DependentObjectsChecker

        target = CorTarget(
            kind="view", schema="public", name="v_x", source_file=None, source_line=None
        )
        checker = DependentObjectsChecker()
        conn = _FakeConnection(rows=[])

        report = checker.check([target], conn)

        assert report.status == "ok"
        assert len(report.entries) == 1
        assert report.entries[0].dependents == []
        assert not report.has_blocking()
        # The query bound schema + name + kinds for relkind 'v'.
        params = conn._cursor.executed_sql[0][1]
        assert params == {"schema": "public", "name": "v_x", "kinds": ["v"]}

    def test_view_target_with_dependents(self) -> None:
        from confiture.core.dependent_objects import DependentObjectsChecker

        target = CorTarget(
            kind="view",
            schema="public",
            name="v_users",
            source_file=None,
            source_line=None,
        )
        # (relkind, schema, name, referenced_columns)
        rows = [
            ("v", "public", "v_active_users", ["id", "email"]),
            ("v", "public", "v_admin_users", []),
        ]
        checker = DependentObjectsChecker()
        report = checker.check([target], _FakeConnection(rows))

        assert report.has_blocking()
        deps = report.entries[0].dependents
        assert len(deps) == 2
        assert deps[0].kind == "view"
        assert deps[0].referenced_columns == ("id", "email")
        assert deps[1].referenced_columns == ()

    def test_matview_target_uses_relkind_m(self) -> None:
        from confiture.core.dependent_objects import DependentObjectsChecker

        target = CorTarget(
            kind="matview", schema="public", name="mv_x", source_file=None, source_line=None
        )
        conn = _FakeConnection(rows=[])
        DependentObjectsChecker().check([target], conn)
        params = conn._cursor.executed_sql[0][1]
        assert params["kinds"] == ["m"]

    def test_function_target_uses_proc_query(self) -> None:
        from confiture.core.dependent_objects import DependentObjectsChecker

        target = CorTarget(
            kind="function", schema="public", name="f_x", source_file=None, source_line=None
        )
        conn = _FakeConnection(rows=[])
        DependentObjectsChecker().check([target], conn)
        sql, params = conn._cursor.executed_sql[0]
        # Different SQL than the view path
        assert "pg_proc" in sql
        assert "kinds" not in params

    def test_unknown_kind_returns_empty_dependents(self) -> None:
        from confiture.core.dependent_objects import DependentObjectsChecker

        target = CorTarget(
            kind="trigger", schema="public", name="t_x", source_file=None, source_line=None
        )
        checker = DependentObjectsChecker()
        conn = _FakeConnection(rows=[("v", "public", "v_y", [])])  # would match if asked
        report = checker.check([target], conn)
        # Unknown kind: no query executed, no dependents
        assert conn._cursor.executed_sql == []
        assert report.entries[0].dependents == []

    def test_warn_severity_is_non_blocking_even_with_dependents(self) -> None:
        from confiture.core.dependent_objects import DependentObjectsChecker

        target = CorTarget(
            kind="view", schema="public", name="v_x", source_file=None, source_line=None
        )
        rows = [("v", "public", "v_y", ["id"])]
        checker = DependentObjectsChecker(severity="info")
        report = checker.check([target], _FakeConnection(rows))
        assert report.entries[0].dependents  # the dependents are still surfaced
        assert not report.has_blocking()

    def test_severity_validation(self) -> None:
        from confiture.core.dependent_objects import DependentObjectsChecker

        with pytest.raises(ValueError, match="severity"):
            DependentObjectsChecker(severity="foo")
