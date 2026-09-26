"""Unit tests for ``migrate baseline --from-db`` row-selection logic.

The ``_select_rows_to_copy`` helper is the pure-logic core of the
``--from-db`` flow: given the source DB's ``tb_confiture`` rows and the
local migration files, decide which rows should be copied and which
warnings to surface.

Issue #119.
"""

from __future__ import annotations

import pytest


class TestSelectRowsToCopy:
    """Pure-logic test of the source/local-file intersection."""

    def test_copies_rows_present_in_both_source_and_local(self) -> None:
        from confiture.core._migrator.baseline_copy import _select_rows_to_copy

        source_rows = [
            {"version": "001", "name": "create_users"},
            {"version": "002", "name": "add_posts"},
            {"version": "003", "name": "add_comments"},
        ]
        local_versions = {"001", "002", "003"}

        result = _select_rows_to_copy(source_rows, local_versions=local_versions)

        assert [r["version"] for r in result.rows] == ["001", "002", "003"]
        assert result.warnings == []
        assert result.source_only == []

    def test_warns_on_source_versions_missing_from_local(self) -> None:
        """Versions applied in source but not present locally are not copied,
        and the operator gets a warning so the gap is visible."""
        from confiture.core._migrator.baseline_copy import _select_rows_to_copy

        source_rows = [
            {"version": "001", "name": "create_users"},
            {"version": "002", "name": "add_posts"},
            {"version": "999", "name": "secret_hotfix"},
        ]
        local_versions = {"001", "002"}

        result = _select_rows_to_copy(source_rows, local_versions=local_versions)

        assert [r["version"] for r in result.rows] == ["001", "002"]
        assert result.source_only == ["999"]
        assert any("999" in w for w in result.warnings)

    def test_through_caps_the_version_list(self) -> None:
        from confiture.core._migrator.baseline_copy import _select_rows_to_copy

        source_rows = [
            {"version": "001", "name": "a"},
            {"version": "002", "name": "b"},
            {"version": "003", "name": "c"},
            {"version": "004", "name": "d"},
        ]
        local_versions = {"001", "002", "003", "004"}

        result = _select_rows_to_copy(source_rows, local_versions=local_versions, through="002")

        assert [r["version"] for r in result.rows] == ["001", "002"]

    def test_through_with_from_db_warns_when_capping_applies(self) -> None:
        from confiture.core._migrator.baseline_copy import _select_rows_to_copy

        source_rows = [
            {"version": "001", "name": "a"},
            {"version": "002", "name": "b"},
            {"version": "003", "name": "c"},
        ]
        local_versions = {"001", "002", "003"}

        result = _select_rows_to_copy(source_rows, local_versions=local_versions, through="002")

        # Source has 003 applied; cap excludes it — operator must see the gap.
        assert "003" not in [r["version"] for r in result.rows]
        assert any("through" in w.lower() and "003" in w for w in result.warnings)

    def test_through_unknown_version_raises(self) -> None:
        from confiture.core._migrator.baseline_copy import _select_rows_to_copy
        from confiture.exceptions import ConfigurationError

        source_rows = [{"version": "001", "name": "a"}]
        local_versions = {"001"}

        with pytest.raises(ConfigurationError, match="999"):
            _select_rows_to_copy(source_rows, local_versions=local_versions, through="999")

    def test_empty_source_returns_empty_with_no_warnings(self) -> None:
        from confiture.core._migrator.baseline_copy import _select_rows_to_copy

        result = _select_rows_to_copy([], local_versions={"001"})

        assert result.rows == []
        assert result.source_only == []
        assert result.warnings == []

    def test_local_files_can_have_extra_versions_no_warning(self) -> None:
        """The opposite case — local has migrations source has never applied —
        is fine.  Those are just pending migrations from source's perspective,
        not a problem."""
        from confiture.core._migrator.baseline_copy import _select_rows_to_copy

        source_rows = [{"version": "001", "name": "create_users"}]
        local_versions = {"001", "002", "003"}

        result = _select_rows_to_copy(source_rows, local_versions=local_versions)

        assert [r["version"] for r in result.rows] == ["001"]
        assert result.source_only == []
        assert result.warnings == []


# ---------------------------------------------------------------------------
# CLI surface tests — argument validation.
# ---------------------------------------------------------------------------


class TestMigrateBaselineCliArgs:
    """The CLI must surface a clean error when neither flag is set, and must
    accept ``--from-db`` without ``--through``."""

    def test_missing_both_flags_errors_cleanly(self, tmp_path) -> None:
        from typer.testing import CliRunner

        from confiture.cli.main import app

        # Provide a config + migrations dir so the validation under test
        # is the "missing both flags" check, not a path check.
        env_dir = tmp_path / "db" / "environments"
        env_dir.mkdir(parents=True)
        (tmp_path / "db" / "migrations").mkdir()
        cfg = env_dir / "test.yaml"
        cfg.write_text(
            "name: test\ndatabase_url: postgresql://localhost/x\ninclude_dirs:\n  - db\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            app,
            [
                "migrate",
                "baseline",
                "--config",
                str(cfg),
                "--migrations-dir",
                str(tmp_path / "db" / "migrations"),
            ],
        )
        assert result.exit_code != 0
        assert "--through" in result.output or "--from-db" in result.output

    def test_from_db_dispatches_to_copy_flow(self, tmp_path, monkeypatch) -> None:
        """When --from-db is set, the CLI delegates to
        ``Migrator.baseline_from_db`` rather than the manual mark loop."""
        from typer.testing import CliRunner

        from confiture.cli.commands.migrate import baseline as migrate_state
        from confiture.cli.main import app

        captured: dict = {}

        def _fake_flow(**kwargs) -> dict:
            captured.update(kwargs)
            return {
                "mode": "from_db",
                "source": kwargs["from_db"],
                "through": kwargs["through"],
                "copied": [],
                "skipped": [],
                "source_only": [],
                "warnings": [],
                "dry_run": kwargs["dry_run"],
            }

        monkeypatch.setattr(migrate_state, "_baseline_from_db_flow", _fake_flow)

        env_dir = tmp_path / "db" / "environments"
        env_dir.mkdir(parents=True)
        (tmp_path / "db" / "migrations").mkdir()
        cfg = env_dir / "test.yaml"
        cfg.write_text(
            "name: test\ndatabase_url: postgresql://localhost/x\ninclude_dirs:\n  - db\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            app,
            [
                "migrate",
                "baseline",
                "--config",
                str(cfg),
                "--migrations-dir",
                str(tmp_path / "db" / "migrations"),
                "--from-db",
                "postgresql://source-host/x",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0, result.output
        assert captured["from_db"] == "postgresql://source-host/x"
        assert captured["dry_run"] is True
        assert captured["through"] is None


def test_from_db_report_never_carries_the_source_password(tmp_path) -> None:
    """The source DSN is printed and emitted, so it is redacted before either."""
    from contextlib import nullcontext
    from unittest.mock import MagicMock, patch

    from confiture.cli.commands.migrate import baseline

    config = tmp_path / "local.yaml"
    config.write_text("database_url: postgresql://localhost/target\n")
    migrator = MagicMock()
    migrator.baseline_from_db.return_value = {
        "copied": [],
        "skipped": [],
        "source_only": [],
        "warnings": [],
        "dry_run": True,
    }
    with (
        patch.object(baseline, "open_connection", return_value=nullcontext(MagicMock())),
        patch.object(baseline._core_migrator, "Migrator", return_value=migrator),
    ):
        report = baseline._baseline_from_db_flow(
            from_db="postgresql://admin:hunter2@prod-host/app",
            through=None,
            source_table=None,
            migrations_dir=tmp_path,
            config=config,
            dry_run=True,
        )

    assert "hunter2" not in repr(report)
    assert report["source"].startswith("postgresql://admin:")


def test_from_db_report_writes_applied_at_in_iso_8601(tmp_path) -> None:
    """``applied_at`` is ISO 8601 (`T` between date and time), as every payload's timestamp."""
    from contextlib import nullcontext
    from datetime import UTC, datetime
    from unittest.mock import MagicMock, patch

    from confiture.cli.commands.migrate import baseline

    config = tmp_path / "local.yaml"
    config.write_text("database_url: postgresql://localhost/target\n")
    migrator = MagicMock()
    migrator.baseline_from_db.return_value = {
        "copied": [
            {
                "version": "002",
                "name": "add_note",
                "applied_at": datetime(2026, 9, 26, 11, 56, 41, 386666, tzinfo=UTC),
                "execution_time_ms": 0,
                "checksum": None,
            }
        ],
        "skipped": [],
        "source_only": [],
        "warnings": [],
        "dry_run": True,
    }
    with (
        patch.object(baseline, "open_connection", return_value=nullcontext(MagicMock())),
        patch.object(baseline._core_migrator, "Migrator", return_value=migrator),
    ):
        report = baseline._baseline_from_db_flow(
            from_db="postgresql://source-host/app",
            through=None,
            source_table=None,
            migrations_dir=tmp_path,
            config=config,
            dry_run=True,
        )

    assert report["copied"][0]["applied_at"] == "2026-09-26T11:56:41.386666+00:00"
