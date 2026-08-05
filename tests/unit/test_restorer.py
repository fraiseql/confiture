"""Unit tests for DatabaseRestorer.

All tests mock subprocess.Popen and psycopg.connect via monkeypatch /
unittest.mock — no real database or pg_restore binary is required.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from confiture.core.restorer import (
    DatabaseRestorer,
    RestoreOptions,
    RestoreResult,
    TocEntry,
)
from confiture.exceptions import RestoreError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_proc(stderr_lines: list[str], returncode: int) -> MagicMock:
    """Build a mock Popen context manager with the given stderr and exit code."""
    mock_proc = MagicMock()
    mock_proc.stderr = iter(stderr_lines)
    mock_proc.wait.return_value = returncode
    mock_proc.__enter__ = lambda s: s
    mock_proc.__exit__ = MagicMock(return_value=False)
    return mock_proc


def _make_db_mock(cursor_row: tuple):
    """Return a context-manager mock for psycopg.connect returning one row."""
    mock_cursor = MagicMock()
    mock_cursor.__enter__ = lambda s: mock_cursor
    mock_cursor.__exit__ = MagicMock(return_value=False)
    mock_cursor.fetchone.return_value = cursor_row

    mock_conn = MagicMock()
    mock_conn.__enter__ = lambda s: mock_conn
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_conn.cursor.return_value = mock_cursor
    return mock_conn, mock_cursor


# ---------------------------------------------------------------------------
# Cycle 1: dataclass defaults
# ---------------------------------------------------------------------------


class TestRestoreOptionsDefaults:
    def test_defaults(self):
        opts = RestoreOptions(backup_path=Path("dump.pgdump"), target_db="staging")
        assert opts.host == "/var/run/postgresql"
        assert opts.port == 5432
        assert opts.username is None
        assert opts.jobs == 4
        assert opts.no_owner is False
        assert opts.no_acl is False
        assert opts.exit_on_error is True
        assert opts.superuser is None
        assert opts.min_tables == 0
        assert opts.min_tables_schema == "public"
        assert opts.parallel_restore is False


class TestRestoreResultDefaults:
    def test_defaults(self):
        result = RestoreResult(success=True, phases_completed=["pre-data"])
        assert result.errors == []
        assert result.warnings == []
        assert result.table_count is None
        assert result.diagnostics == []


# ---------------------------------------------------------------------------
# Cycle 2: dump format validation
# ---------------------------------------------------------------------------


class TestDumpFormatValidation:
    def test_custom_format_file_is_accepted(self, tmp_path):
        dump = tmp_path / "dump.pgdump"
        dump.write_bytes(b"PGDMP\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00")
        DatabaseRestorer()._validate_dump_format(dump)  # must not raise

    def test_directory_format_is_accepted(self, tmp_path):
        dump_dir = tmp_path / "dump_dir"
        dump_dir.mkdir()
        (dump_dir / "toc.dat").write_bytes(b"PGDMP\x00\x00")
        DatabaseRestorer()._validate_dump_format(dump_dir)  # must not raise

    def test_directory_without_toc_raises(self, tmp_path):
        dump_dir = tmp_path / "nodump"
        dump_dir.mkdir()
        with pytest.raises(RestoreError, match="toc.dat"):
            DatabaseRestorer()._validate_dump_format(dump_dir)

    def test_plain_text_sql_raises_restore_error(self, tmp_path):
        dump = tmp_path / "dump.sql"
        dump.write_text("-- PostgreSQL database dump\nCREATE TABLE foo (id int);")
        with pytest.raises(RestoreError, match="plain.text"):
            DatabaseRestorer()._validate_dump_format(dump)

    def test_plain_text_starting_with_set_raises(self, tmp_path):
        dump = tmp_path / "dump.sql"
        dump.write_text("SET client_encoding = 'UTF8';\nCREATE TABLE foo (id int);")
        with pytest.raises(RestoreError, match="plain.text"):
            DatabaseRestorer()._validate_dump_format(dump)

    def test_unrecognised_format_raises_restore_error(self, tmp_path):
        dump = tmp_path / "dump.bin"
        dump.write_bytes(b"\x00\x01\x02\x03")
        with pytest.raises(RestoreError, match="custom.*directory|directory.*custom"):
            DatabaseRestorer()._validate_dump_format(dump)

    def test_missing_file_raises_restore_error(self, tmp_path):
        dump = tmp_path / "nonexistent.pgdump"
        with pytest.raises(RestoreError, match="Cannot read"):
            DatabaseRestorer()._validate_dump_format(dump)


# ---------------------------------------------------------------------------
# Cycle 3: _build_command
# ---------------------------------------------------------------------------


class TestBuildCommand:
    def _opts(self, **kwargs) -> RestoreOptions:
        defaults = {"backup_path": Path("dump.pgdump"), "target_db": "mydb"}
        defaults.update(kwargs)
        return RestoreOptions(**defaults)

    def test_minimal_command(self):
        cmd = DatabaseRestorer()._build_command("pre-data", self._opts(), parallel=False)
        assert "pg_restore" in cmd
        assert "-h" in cmd
        assert "/var/run/postgresql" in cmd
        assert "-p" in cmd
        assert "5432" in cmd
        assert "-d" in cmd
        assert "mydb" in cmd
        assert "--section=pre-data" in cmd
        assert "--exit-on-error" in cmd
        assert "-j" not in cmd

    def test_username_added_when_set(self):
        cmd = DatabaseRestorer()._build_command(
            "pre-data", self._opts(username="appuser"), parallel=False
        )
        assert "-U" in cmd
        assert "appuser" in cmd

    def test_no_username_when_none(self):
        cmd = DatabaseRestorer()._build_command(
            "pre-data", self._opts(username=None), parallel=False
        )
        assert "-U" not in cmd

    def test_parallel_adds_jobs(self):
        cmd = DatabaseRestorer()._build_command("data", self._opts(jobs=8), parallel=True)
        assert "-j" in cmd
        assert "8" in cmd

    def test_jobs_1_omits_j_flag(self):
        cmd = DatabaseRestorer()._build_command("data", self._opts(jobs=1), parallel=True)
        assert "-j" not in cmd

    def test_parallel_false_omits_jobs_regardless(self):
        cmd = DatabaseRestorer()._build_command("post-data", self._opts(jobs=8), parallel=False)
        assert "-j" not in cmd

    def test_no_owner_flag_only_when_true(self):
        restorer = DatabaseRestorer()
        assert "--no-owner" in restorer._build_command("pre-data", self._opts(no_owner=True), False)
        assert "--no-owner" not in restorer._build_command(
            "pre-data", self._opts(no_owner=False), False
        )

    def test_no_acl_flag_only_when_true(self):
        restorer = DatabaseRestorer()
        assert "--no-acl" in restorer._build_command("pre-data", self._opts(no_acl=True), False)
        assert "--no-acl" not in restorer._build_command(
            "pre-data", self._opts(no_acl=False), False
        )

    def test_exit_on_error_false_omits_flag(self):
        cmd = DatabaseRestorer()._build_command("pre-data", self._opts(exit_on_error=False), False)
        assert "--exit-on-error" not in cmd

    def test_superuser_prepends_sudo(self):
        cmd = DatabaseRestorer()._build_command(
            "pre-data", self._opts(superuser="postgres"), parallel=False
        )
        assert cmd[:3] == ["sudo", "-u", "postgres"]

    def test_custom_port(self):
        cmd = DatabaseRestorer()._build_command("pre-data", self._opts(port=5433), False)
        assert "-p" in cmd
        assert "5433" in cmd

    def test_backup_path_is_last_arg(self):
        cmd = DatabaseRestorer()._build_command("pre-data", self._opts(), False)
        assert cmd[-1] == "dump.pgdump"


# ---------------------------------------------------------------------------
# Cycle 4: _run_section
# ---------------------------------------------------------------------------


class TestRunSection:
    def _opts(self, **kwargs) -> RestoreOptions:
        defaults = {"backup_path": Path("d.pgdump"), "target_db": "db"}
        defaults.update(kwargs)
        return RestoreOptions(**defaults)

    def test_success_returns_true(self):
        mock_proc = _make_proc(["pg_restore: connecting to database\n"], 0)
        with patch("subprocess.Popen", return_value=mock_proc):
            result = DatabaseRestorer()._run_section("pre-data", self._opts(), parallel=False)
        assert result.success is True
        assert result.phases_completed == ["pre-data"]

    def test_on_stderr_line_callback_called(self):
        mock_proc = _make_proc(["pg_restore: connecting\n"], 0)
        lines: list[str] = []
        with patch("subprocess.Popen", return_value=mock_proc):
            DatabaseRestorer()._run_section(
                "pre-data", self._opts(), parallel=False, on_stderr_line=lines.append
            )
        assert lines == ["pg_restore: connecting"]

    def test_exit_code_1_with_error_returns_failure(self):
        mock_proc = _make_proc(["pg_restore: error: could not execute query: FK violation\n"], 1)
        with patch("subprocess.Popen", return_value=mock_proc):
            result = DatabaseRestorer()._run_section("pre-data", self._opts(), parallel=False)
        assert result.success is False
        assert any("FK violation" in e for e in result.errors)

    def test_exit_code_1_with_only_warnings_lenient_mode(self):
        mock_proc = _make_proc(['pg_restore: warning: table "foo" does not exist, skipping\n'], 1)
        with patch("subprocess.Popen", return_value=mock_proc):
            result = DatabaseRestorer()._run_section(
                "pre-data", self._opts(exit_on_error=False), parallel=False
            )
        assert result.success is True
        assert len(result.warnings) == 1

    def test_exit_code_1_with_exit_on_error_true_always_fails(self):
        mock_proc = _make_proc(["pg_restore: warning: something\n"], 1)
        with patch("subprocess.Popen", return_value=mock_proc):
            result = DatabaseRestorer()._run_section(
                "pre-data", self._opts(exit_on_error=True), parallel=False
            )
        assert result.success is False

    def test_keyboard_interrupt_kills_process(self):
        mock_proc = MagicMock()
        mock_proc.stderr = iter([])
        mock_proc.wait.side_effect = KeyboardInterrupt
        mock_proc.__enter__ = lambda s: s
        mock_proc.__exit__ = MagicMock(return_value=False)
        with patch("subprocess.Popen", return_value=mock_proc):
            with pytest.raises(RestoreError, match="interrupted"):
                DatabaseRestorer()._run_section("data", self._opts(), parallel=True)
        mock_proc.kill.assert_called_once()

    def test_pg_restore_not_found_raises_restore_error(self):
        with patch("subprocess.Popen", side_effect=FileNotFoundError("pg_restore")):
            with pytest.raises(RestoreError, match="pg_restore not found"):
                DatabaseRestorer()._run_section("pre-data", self._opts(), parallel=False)

    def test_errors_and_warnings_separated(self):
        mock_proc = _make_proc(
            [
                "pg_restore: error: FK violation\n",
                "pg_restore: warning: skipping foo\n",
            ],
            1,
        )
        with patch("subprocess.Popen", return_value=mock_proc):
            result = DatabaseRestorer()._run_section("pre-data", self._opts(), parallel=False)
        assert len(result.errors) == 1
        assert len(result.warnings) == 1


# ---------------------------------------------------------------------------
# Cycle 5: restore orchestration
# ---------------------------------------------------------------------------


class TestRestoreOrchestration:
    def _opts(self, **kwargs) -> RestoreOptions:
        defaults = {"backup_path": Path("d.pgdump"), "target_db": "db"}
        defaults.update(kwargs)
        return RestoreOptions(**defaults)

    def test_calls_three_phases_in_order(self):
        restorer = DatabaseRestorer()
        calls: list[tuple[str, bool]] = []

        def fake_validate(path):
            pass

        def fake_run(section, opts, parallel, on_stderr_line=None, use_list=None):
            calls.append((section, parallel))
            return RestoreResult(success=True, phases_completed=[section])

        restorer._validate_dump_format = fake_validate  # type: ignore[method-assign]
        restorer._list_toc = lambda o: []  # type: ignore[method-assign]  # fast path: no matviews
        restorer._run_section = fake_run  # type: ignore[method-assign]
        result = restorer.restore(self._opts())
        assert calls == [("pre-data", False), ("data", True), ("post-data", False)]
        assert result.success is True
        assert result.phases_completed == ["pre-data", "data", "post-data"]

    def test_format_validation_runs_before_any_phase(self):
        restorer = DatabaseRestorer()
        run_called = []

        def fake_validate(path):
            raise RestoreError("bad format")

        def fake_run(section, opts, parallel, on_stderr_line=None, use_list=None):
            run_called.append(section)
            return RestoreResult(success=True, phases_completed=[section])

        restorer._validate_dump_format = fake_validate  # type: ignore[method-assign]
        restorer._run_section = fake_run  # type: ignore[method-assign]
        with pytest.raises(RestoreError, match="bad format"):
            restorer.restore(self._opts())
        assert run_called == []

    def test_failure_in_pre_data_short_circuits(self):
        restorer = DatabaseRestorer()
        calls: list[str] = []

        restorer._validate_dump_format = lambda p: None  # type: ignore[method-assign]
        restorer._list_toc = lambda o: []  # type: ignore[method-assign]  # fast path: no matviews

        def fake_run(section, opts, parallel, on_stderr_line=None, use_list=None):
            calls.append(section)
            if section == "pre-data":
                return RestoreResult(success=False, phases_completed=[], errors=["DDL error"])
            return RestoreResult(success=True, phases_completed=[section])

        restorer._run_section = fake_run  # type: ignore[method-assign]
        result = restorer.restore(self._opts())
        assert calls == ["pre-data"]
        assert result.success is False

    def test_failure_in_data_phase_short_circuits(self):
        restorer = DatabaseRestorer()
        calls: list[str] = []
        restorer._validate_dump_format = lambda p: None  # type: ignore[method-assign]
        restorer._list_toc = lambda o: []  # type: ignore[method-assign]  # fast path: no matviews

        def fake_run(section, opts, parallel, on_stderr_line=None, use_list=None):
            calls.append(section)
            if section == "data":
                return RestoreResult(success=False, phases_completed=[], errors=["data error"])
            return RestoreResult(success=True, phases_completed=[section])

        restorer._run_section = fake_run  # type: ignore[method-assign]
        result = restorer.restore(self._opts())
        assert calls == ["pre-data", "data"]
        assert result.success is False

    def test_warnings_accumulated_across_phases(self):
        restorer = DatabaseRestorer()
        restorer._validate_dump_format = lambda p: None  # type: ignore[method-assign]
        restorer._list_toc = lambda o: []  # type: ignore[method-assign]  # fast path: no matviews

        def fake_run(section, opts, parallel, on_stderr_line=None, use_list=None):
            return RestoreResult(
                success=True, phases_completed=[section], warnings=[f"warn from {section}"]
            )

        restorer._run_section = fake_run  # type: ignore[method-assign]
        result = restorer.restore(self._opts())
        assert len(result.warnings) == 3

    def test_skips_min_tables_when_zero(self):
        restorer = DatabaseRestorer()
        validate_table_called = []
        restorer._validate_dump_format = lambda p: None  # type: ignore[method-assign]
        restorer._list_toc = lambda o: []  # type: ignore[method-assign]  # fast path: no matviews
        restorer._run_section = (  # type: ignore[method-assign]
            lambda s, o, p, on_stderr_line=None, use_list=None: RestoreResult(
                success=True, phases_completed=[s]
            )
        )

        def fake_validate_table(opts):
            validate_table_called.append(True)
            return RestoreResult(success=True, phases_completed=[], table_count=0)

        restorer._validate_table_count = fake_validate_table  # type: ignore[method-assign]
        restorer.restore(self._opts(min_tables=0))
        assert validate_table_called == []

    def test_calls_validate_table_count_when_min_tables_set(self):
        restorer = DatabaseRestorer()
        validate_table_called = []
        restorer._validate_dump_format = lambda p: None  # type: ignore[method-assign]
        restorer._list_toc = lambda o: []  # type: ignore[method-assign]  # fast path: no matviews
        restorer._run_section = (  # type: ignore[method-assign]
            lambda s, o, p, on_stderr_line=None, use_list=None: RestoreResult(
                success=True, phases_completed=[s]
            )
        )

        def fake_validate_table(opts):
            validate_table_called.append(True)
            return RestoreResult(
                success=True, phases_completed=["pre-data", "data", "post-data"], table_count=350
            )

        restorer._validate_table_count = fake_validate_table  # type: ignore[method-assign]
        result = restorer.restore(self._opts(min_tables=100))
        assert validate_table_called == [True]
        assert result.table_count == 350


# ---------------------------------------------------------------------------
# Cycle 6: _validate_table_count
# ---------------------------------------------------------------------------


class TestValidateTableCount:
    def _opts(self, **kwargs) -> RestoreOptions:
        defaults = {
            "backup_path": Path("d.pgdump"),
            "target_db": "db",
            "host": "localhost",
            "port": 5432,
        }
        defaults.update(kwargs)
        return RestoreOptions(**defaults)

    def test_passes_when_count_meets_minimum(self):
        mock_conn, _ = _make_db_mock((350,))
        with patch("psycopg.connect", return_value=mock_conn):
            result = DatabaseRestorer()._validate_table_count(self._opts(min_tables=300))
        assert result.success is True
        assert result.table_count == 350

    def test_fails_when_count_below_minimum(self):
        mock_conn, _ = _make_db_mock((50,))
        with patch("psycopg.connect", return_value=mock_conn):
            result = DatabaseRestorer()._validate_table_count(self._opts(min_tables=300))
        assert result.success is False
        assert "50" in result.errors[0]
        assert "300" in result.errors[0]

    def test_uses_schema_from_options(self):
        mock_conn, mock_cursor = _make_db_mock((10,))
        with patch("psycopg.connect", return_value=mock_conn):
            DatabaseRestorer()._validate_table_count(
                self._opts(min_tables=5, min_tables_schema="myschema")
            )
        call_args = mock_cursor.execute.call_args
        assert call_args[0][1] == ("myschema",)

    def test_connection_error_raises_restore_error(self):
        import psycopg as _psycopg

        with patch("psycopg.connect", side_effect=_psycopg.OperationalError("refused")):
            with pytest.raises(RestoreError, match="Cannot connect"):
                DatabaseRestorer()._validate_table_count(self._opts(min_tables=1))


# ---------------------------------------------------------------------------
# Cycle 7: RestoreError exception hierarchy
# ---------------------------------------------------------------------------


class TestRestoreErrorHierarchy:
    def test_restore_error_is_confiture_error(self):
        from confiture.exceptions import ConfiturError
        from confiture.exceptions import RestoreError as RE

        err = RE("pg_restore failed")
        assert isinstance(err, ConfiturError)
        assert str(err) == "pg_restore failed"

    def test_restore_error_can_be_raised_and_caught(self):
        with pytest.raises(RestoreError, match="test message"):
            raise RestoreError("test message")


# ---------------------------------------------------------------------------
# Cycle 9 (partial): _classify_stderr_line
# ---------------------------------------------------------------------------


class TestClassifyStderrLine:
    def test_error_line(self):
        assert DatabaseRestorer._classify_stderr_line("pg_restore: error: FK violation") == "error"

    def test_warning_line(self):
        assert (
            DatabaseRestorer._classify_stderr_line("pg_restore: warning: table missing")
            == "warning"
        )

    def test_info_line(self):
        assert (
            DatabaseRestorer._classify_stderr_line("pg_restore: connecting to database") == "info"
        )

    def test_empty_line(self):
        assert DatabaseRestorer._classify_stderr_line("") == "info"


# ---------------------------------------------------------------------------
# Cycle 10: _diagnose_post_data_errors  (Issue #55)
# ---------------------------------------------------------------------------


class TestDiagnosePostDataErrors:
    def test_out_of_shared_memory_produces_hint(self):
        lines = ["pg_restore: error: out of shared memory"]
        hints = DatabaseRestorer._diagnose_post_data_errors(lines)
        assert len(hints) == 1
        assert "max_locks_per_transaction" in hints[0]

    def test_out_of_shared_memory_in_warning_produces_hint(self):
        lines = ["pg_restore: warning: out of shared memory"]
        hints = DatabaseRestorer._diagnose_post_data_errors(lines)
        assert len(hints) == 1

    def test_unrelated_errors_produce_no_diagnostics(self):
        lines = [
            "pg_restore: error: FK violation",
            "pg_restore: warning: table does not exist",
        ]
        hints = DatabaseRestorer._diagnose_post_data_errors(lines)
        assert hints == []

    def test_empty_lines_produce_no_diagnostics(self):
        assert DatabaseRestorer._diagnose_post_data_errors([]) == []

    def test_restore_result_diagnostics_populated_on_post_data_failure(self):
        """End-to-end: out-of-shared-memory error in post-data → hint in RestoreResult."""
        restorer = DatabaseRestorer()
        restorer._validate_dump_format = lambda p: None  # type: ignore[method-assign]
        restorer._list_toc = lambda o: []  # type: ignore[method-assign]  # fast path: no matviews

        def fake_run(section, opts, parallel, on_stderr_line=None, use_list=None):
            if section == "post-data":
                return RestoreResult(
                    success=False,
                    phases_completed=[],
                    errors=["pg_restore: error: out of shared memory"],
                )
            return RestoreResult(success=True, phases_completed=[section])

        restorer._run_section = fake_run  # type: ignore[method-assign]
        result = restorer.restore(RestoreOptions(backup_path=Path("d.pgdump"), target_db="db"))
        assert result.success is False
        assert len(result.diagnostics) == 1
        assert "max_locks_per_transaction" in result.diagnostics[0]

    def test_restore_result_diagnostics_populated_on_success_with_warning(self):
        """out-of-shared-memory in a warning on a lenient restore → hint in RestoreResult."""
        restorer = DatabaseRestorer()
        restorer._validate_dump_format = lambda p: None  # type: ignore[method-assign]
        restorer._list_toc = lambda o: []  # type: ignore[method-assign]  # fast path: no matviews

        def fake_run(section, opts, parallel, on_stderr_line=None, use_list=None):
            if section == "post-data":
                return RestoreResult(
                    success=True,
                    phases_completed=["post-data"],
                    warnings=["pg_restore: warning: out of shared memory"],
                )
            return RestoreResult(success=True, phases_completed=[section])

        restorer._run_section = fake_run  # type: ignore[method-assign]
        result = restorer.restore(RestoreOptions(backup_path=Path("d.pgdump"), target_db="db"))
        assert result.success is True
        assert len(result.diagnostics) == 1
        assert "max_locks_per_transaction" in result.diagnostics[0]

    def test_restore_result_no_diagnostics_on_clean_restore(self):
        restorer = DatabaseRestorer()
        restorer._validate_dump_format = lambda p: None  # type: ignore[method-assign]
        restorer._list_toc = lambda o: []  # type: ignore[method-assign]  # fast path: no matviews
        restorer._run_section = (  # type: ignore[method-assign]
            lambda s, o, p, on_stderr_line=None, use_list=None: RestoreResult(
                success=True, phases_completed=[s]
            )
        )
        result = restorer.restore(RestoreOptions(backup_path=Path("d.pgdump"), target_db="db"))
        assert result.diagnostics == []


# ---------------------------------------------------------------------------
# Cycle 11: parallel_restore flag  (Issue #54)
# ---------------------------------------------------------------------------


class TestParallelRestoreFlag:
    def _opts(self, **kwargs) -> RestoreOptions:
        defaults = {"backup_path": Path("d.pgdump"), "target_db": "db"}
        defaults.update(kwargs)
        return RestoreOptions(**defaults)

    def _make_restorer(self):
        restorer = DatabaseRestorer()
        restorer._validate_dump_format = lambda p: None  # type: ignore[method-assign]
        restorer._list_toc = lambda o: []  # type: ignore[method-assign]  # fast path: no matviews
        restorer._run_section = (  # type: ignore[method-assign]
            lambda s, o, p, on_stderr_line=None, use_list=None: RestoreResult(
                success=True, phases_completed=[s]
            )
        )
        return restorer

    def test_parallel_restore_false_does_not_override(self):
        """exit_on_error=True stays True when parallel_restore=False."""
        seen_options: list[RestoreOptions] = []

        restorer = DatabaseRestorer()
        restorer._validate_dump_format = lambda p: None  # type: ignore[method-assign]
        restorer._list_toc = lambda o: []  # type: ignore[method-assign]  # fast path: no matviews

        def capture_run(section, opts, parallel, on_stderr_line=None, use_list=None):
            seen_options.append(opts)
            return RestoreResult(success=True, phases_completed=[section])

        restorer._run_section = capture_run  # type: ignore[method-assign]
        restorer.restore(self._opts(parallel_restore=False, exit_on_error=True))
        assert all(o.exit_on_error is True for o in seen_options)

    def test_parallel_restore_true_overrides_exit_on_error(self):
        """exit_on_error is overridden to False when parallel_restore=True."""
        seen_options: list[RestoreOptions] = []

        restorer = DatabaseRestorer()
        restorer._validate_dump_format = lambda p: None  # type: ignore[method-assign]
        restorer._list_toc = lambda o: []  # type: ignore[method-assign]  # fast path: no matviews

        def capture_run(section, opts, parallel, on_stderr_line=None, use_list=None):
            seen_options.append(opts)
            return RestoreResult(success=True, phases_completed=[section])

        restorer._run_section = capture_run  # type: ignore[method-assign]
        restorer.restore(self._opts(parallel_restore=True, exit_on_error=True))
        assert all(o.exit_on_error is False for o in seen_options)

    def test_parallel_restore_does_not_mutate_original_options(self):
        """The caller's RestoreOptions object is not mutated."""
        original = self._opts(parallel_restore=True, exit_on_error=True)
        restorer = self._make_restorer()
        restorer.restore(original)
        assert original.exit_on_error is True  # unchanged

    def test_parallel_restore_logs_warning(self, caplog):
        """A warning is logged when exit_on_error is overridden."""
        import logging

        restorer = self._make_restorer()
        with caplog.at_level(logging.WARNING, logger="confiture.core.restorer"):
            restorer.restore(self._opts(parallel_restore=True, exit_on_error=True))
        assert any("parallel_restore" in msg for msg in caplog.messages)

    def test_parallel_restore_true_exit_on_error_already_false_no_warning(self, caplog):
        """No warning when exit_on_error is already False."""
        import logging

        restorer = self._make_restorer()
        with caplog.at_level(logging.WARNING, logger="confiture.core.restorer"):
            restorer.restore(self._opts(parallel_restore=True, exit_on_error=False))
        assert not any("parallel_restore" in msg for msg in caplog.messages)


# ---------------------------------------------------------------------------
# Issue #172, Phase 1: TOC parsing
# ---------------------------------------------------------------------------

# A representative `pg_restore -l` listing: header comments, a table + its data,
# a matview definition (pre-data) + its DATA entry (the REFRESH), an index and an
# FK constraint (post-data). Owners/tablespaces vary in real output.
_SAMPLE_TOC = """;
; Archive created at 2026-07-07 09:00:00 UTC
;     dbname: prod
;     TOC Entries: 8
;     Compression: -1
;     Dump Version: 1.14-0
;     Format: CUSTOM
;
;
; Selected TOC Entries:
;
215; 1259 16405 TABLE public tb_order postgres
3001; 0 16405 TABLE DATA public tb_order postgres
216; 1259 16410 MATERIALIZED VIEW public mv_maintenance_price postgres
3002; 0 16410 MATERIALIZED VIEW DATA public mv_maintenance_price postgres
217; 1259 16420 MATERIALIZED VIEW public mv_count_all postgres
3003; 0 16420 MATERIALIZED VIEW DATA public mv_count_all postgres
2801; 1259 16430 INDEX public tb_order_pkey postgres
2900; 2606 16435 FK CONSTRAINT public tb_order tb_order_customer_fkey postgres
"""


class TestParseTocLines:
    def _parse(self):
        return DatabaseRestorer._parse_toc_lines(_SAMPLE_TOC.splitlines())

    def test_skips_comment_and_blank_lines(self):
        entries = self._parse()
        # 8 real entries; every comment (`;`) and blank line dropped.
        assert len(entries) == 8
        assert all(isinstance(e, TocEntry) for e in entries)

    def test_extracts_dump_id(self):
        entries = self._parse()
        assert [e.dump_id for e in entries] == [215, 3001, 216, 3002, 217, 3003, 2801, 2900]

    def test_preserves_raw_line_for_use_list_round_trip(self):
        entries = self._parse()
        matview_data = [e for e in entries if e.is_matview_data]
        assert "3002; 0 16410 MATERIALIZED VIEW DATA public mv_maintenance_price postgres" in [
            e.raw_line for e in matview_data
        ]

    def test_matview_data_detected(self):
        entries = self._parse()
        mv_data = [e for e in entries if e.is_matview_data]
        assert len(mv_data) == 2
        assert {e.dump_id for e in mv_data} == {3002, 3003}

    def test_matview_definition_is_not_matview_data(self):
        """CREATE MATERIALIZED VIEW (pre-data) must not be mistaken for its DATA entry."""
        entries = self._parse()
        definitions = [e for e in entries if e.dump_id in (216, 217)]
        assert len(definitions) == 2
        assert all(not e.is_matview_data for e in definitions)
        assert all(e.description == "MATERIALIZED VIEW" for e in definitions)

    def test_table_data_classified(self):
        entries = self._parse()
        table_data = [e for e in entries if e.description == "TABLE DATA"]
        assert [e.dump_id for e in table_data] == [3001]
        assert all(not e.is_matview_data for e in table_data)

    def test_matview_data_description(self):
        entries = self._parse()
        mv_data = [e for e in entries if e.is_matview_data]
        assert all(e.description == "MATERIALIZED VIEW DATA" for e in mv_data)

    def test_empty_input_returns_empty(self):
        assert DatabaseRestorer._parse_toc_lines([]) == []

    def test_comment_only_input_returns_empty(self):
        lines = [";", "; header", ";     dbname: x", ""]
        assert DatabaseRestorer._parse_toc_lines(lines) == []


# ---------------------------------------------------------------------------
# Issue #172, Phase 2: use-list partitioning + _build_command -L
# ---------------------------------------------------------------------------


class TestPartitionEntries:
    def _entries(self):
        return DatabaseRestorer._parse_toc_lines(_SAMPLE_TOC.splitlines())

    def test_partition_splits_matview_data_from_the_rest(self):
        non_matview, matview_data = DatabaseRestorer._partition_entries(self._entries())
        assert {e.dump_id for e in matview_data} == {3002, 3003}
        # Everything else (table, table-data, matview definitions, index, FK) stays.
        assert {e.dump_id for e in non_matview} == {215, 3001, 216, 217, 2801, 2900}

    def test_partition_no_matviews_returns_empty_matview_list(self):
        no_mv = [
            "215; 1259 16405 TABLE public tb_order postgres",
            "3001; 0 16405 TABLE DATA public tb_order postgres",
        ]
        entries = DatabaseRestorer._parse_toc_lines(no_mv)
        non_matview, matview_data = DatabaseRestorer._partition_entries(entries)
        assert matview_data == []
        assert len(non_matview) == 2

    def test_write_use_list_preserves_raw_lines(self, tmp_path):
        _, matview_data = DatabaseRestorer._partition_entries(self._entries())
        path = tmp_path / "matviews.list"
        DatabaseRestorer._write_use_list(matview_data, path)
        written = path.read_text().splitlines()
        assert (
            "3002; 0 16410 MATERIALIZED VIEW DATA public mv_maintenance_price postgres" in written
        )
        assert "3003; 0 16420 MATERIALIZED VIEW DATA public mv_count_all postgres" in written
        assert len(written) == 2


class TestBuildCommandUseList:
    def _opts(self, **kwargs) -> RestoreOptions:
        defaults = {"backup_path": Path("dump.pgdump"), "target_db": "mydb"}
        defaults.update(kwargs)
        return RestoreOptions(**defaults)

    def test_use_list_adds_dash_L_with_path(self, tmp_path):
        use_list = tmp_path / "tables.list"
        cmd = DatabaseRestorer()._build_command(
            "data", self._opts(), parallel=True, use_list=use_list
        )
        assert "-L" in cmd
        assert str(use_list) in cmd
        # -L must reference the list, immediately following the flag.
        assert cmd[cmd.index("-L") + 1] == str(use_list)

    def test_no_use_list_omits_dash_L(self):
        cmd = DatabaseRestorer()._build_command("data", self._opts(), parallel=True)
        assert "-L" not in cmd

    def test_backup_path_still_last_with_use_list(self, tmp_path):
        use_list = tmp_path / "tables.list"
        cmd = DatabaseRestorer()._build_command(
            "data", self._opts(), parallel=True, use_list=use_list
        )
        assert cmd[-1] == "dump.pgdump"

    def test_section_none_omits_section_flag(self, tmp_path):
        """The deferred refresh runs with -L but no --section (version-robust)."""
        use_list = tmp_path / "matviews.list"
        cmd = DatabaseRestorer()._build_command(
            None, self._opts(), parallel=False, use_list=use_list
        )
        assert not any(a.startswith("--section") for a in cmd)
        assert "-L" in cmd
        assert cmd[-1] == "dump.pgdump"


# ---------------------------------------------------------------------------
# Issue #172, Phase 3: ANALYZE phase
# ---------------------------------------------------------------------------


class TestBuildAnalyzeCommand:
    def _opts(self, **kwargs) -> RestoreOptions:
        defaults = {"backup_path": Path("dump.pgdump"), "target_db": "mydb"}
        defaults.update(kwargs)
        return RestoreOptions(**defaults)

    def test_runs_psql_analyze_on_target_db(self):
        cmd = DatabaseRestorer()._build_analyze_command(self._opts())
        assert "psql" in cmd
        assert "-d" in cmd
        assert "mydb" in cmd
        assert "ANALYZE" in cmd
        assert "-h" in cmd
        assert "/var/run/postgresql" in cmd
        assert "-p" in cmd
        assert "5432" in cmd

    def test_stops_on_error(self):
        cmd = DatabaseRestorer()._build_analyze_command(self._opts())
        assert "ON_ERROR_STOP=1" in cmd

    def test_username_added_when_set(self):
        cmd = DatabaseRestorer()._build_analyze_command(self._opts(username="appuser"))
        assert "-U" in cmd
        assert "appuser" in cmd

    def test_no_username_when_none(self):
        cmd = DatabaseRestorer()._build_analyze_command(self._opts(username=None))
        assert "-U" not in cmd

    def test_superuser_prepends_sudo(self):
        cmd = DatabaseRestorer()._build_analyze_command(self._opts(superuser="postgres"))
        assert cmd[:3] == ["sudo", "-u", "postgres"]


class TestRunAnalyze:
    def _opts(self, **kwargs) -> RestoreOptions:
        defaults = {"backup_path": Path("d.pgdump"), "target_db": "db"}
        defaults.update(kwargs)
        return RestoreOptions(**defaults)

    def test_success_returns_analyze_phase(self):
        mock_proc = _make_proc(["ANALYZE\n"], 0)
        with patch("subprocess.Popen", return_value=mock_proc):
            result = DatabaseRestorer()._run_analyze(self._opts())
        assert result.success is True
        assert result.phases_completed == ["analyze"]

    def test_nonzero_exit_with_error_line_returns_failure(self):
        mock_proc = _make_proc(["ERROR:  permission denied for table tb_order\n"], 1)
        with patch("subprocess.Popen", return_value=mock_proc):
            result = DatabaseRestorer()._run_analyze(self._opts())
        assert result.success is False
        assert any("permission denied" in e for e in result.errors)

    def test_nonzero_exit_without_error_line_still_fails(self):
        mock_proc = _make_proc(["some noise\n"], 2)
        with patch("subprocess.Popen", return_value=mock_proc):
            result = DatabaseRestorer()._run_analyze(self._opts())
        assert result.success is False
        assert result.errors  # a synthetic exit-code error is recorded

    def test_psql_not_found_raises_restore_error(self):
        with patch("subprocess.Popen", side_effect=FileNotFoundError("psql")):
            with pytest.raises(RestoreError, match="psql not found"):
                DatabaseRestorer()._run_analyze(self._opts())

    def test_keyboard_interrupt_kills_process(self):
        mock_proc = MagicMock()
        mock_proc.stderr = iter([])
        mock_proc.wait.side_effect = KeyboardInterrupt
        mock_proc.__enter__ = lambda s: s
        mock_proc.__exit__ = MagicMock(return_value=False)
        with patch("subprocess.Popen", return_value=mock_proc):
            with pytest.raises(RestoreError, match="interrupted"):
                DatabaseRestorer()._run_analyze(self._opts())
        mock_proc.kill.assert_called_once()

    def test_on_stderr_line_callback_called(self):
        mock_proc = _make_proc(["ANALYZE\n"], 0)
        lines: list[str] = []
        with patch("subprocess.Popen", return_value=mock_proc):
            DatabaseRestorer()._run_analyze(self._opts(), on_stderr_line=lines.append)
        assert lines == ["ANALYZE"]


# ---------------------------------------------------------------------------
# Issue #172, Phase 4: deferred-matview orchestration
# ---------------------------------------------------------------------------


class TestDeferredMatviewOrchestration:
    """restore() with a backup that contains materialized-view data."""

    def _opts(self, **kwargs) -> RestoreOptions:
        defaults = {"backup_path": Path("d.pgdump"), "target_db": "db"}
        defaults.update(kwargs)
        return RestoreOptions(**defaults)

    def _restorer_with_matviews(self, calls: list, *, refresh_ok=True, analyze_ok=True):
        """A restorer whose TOC has 2 matview-data entries; phase runs are recorded."""
        restorer = DatabaseRestorer()
        entries = DatabaseRestorer._parse_toc_lines(_SAMPLE_TOC.splitlines())
        restorer._validate_dump_format = lambda p: None  # type: ignore[method-assign]
        restorer._list_toc = lambda o: entries  # type: ignore[method-assign]

        def fake_run(section, opts, parallel, on_stderr_line=None, use_list=None):
            calls.append(("section", section, parallel, use_list.name if use_list else None))
            ok = refresh_ok or use_list is None or use_list.name != "matviews.list"
            return RestoreResult(
                success=ok,
                phases_completed=[section] if ok else [],
                errors=[] if ok else ["refresh boom"],
            )

        def fake_analyze(opts, on_stderr_line=None):
            calls.append(("analyze",))
            return RestoreResult(
                success=analyze_ok,
                phases_completed=["analyze"] if analyze_ok else [],
                errors=[] if analyze_ok else ["analyze boom"],
            )

        restorer._run_section = fake_run  # type: ignore[method-assign]
        restorer._run_analyze = fake_analyze  # type: ignore[method-assign]
        return restorer

    def test_defers_matview_refresh_past_analyze(self):
        calls: list = []
        restorer = self._restorer_with_matviews(calls)
        result = restorer.restore(self._opts())

        assert result.success is True
        # Every phase excludes matview data (tables.list); the refresh runs
        # serially after ANALYZE with no --section (section=None).
        assert calls == [
            ("section", "pre-data", False, "tables.list"),
            ("section", "data", True, "tables.list"),
            ("section", "post-data", False, "tables.list"),
            ("analyze",),
            ("section", None, False, "matviews.list"),
        ]

    def test_reports_deferred_and_refreshed_counts(self):
        calls: list = []
        restorer = self._restorer_with_matviews(calls)
        result = restorer.restore(self._opts())
        assert result.matviews_deferred == 2
        assert result.matviews_refreshed == 2
        assert result.analyze_ran is True
        assert "analyze" in result.phases_completed
        assert "refresh-matviews" in result.phases_completed

    def test_no_refresh_matviews_skips_analyze_and_refresh(self):
        calls: list = []
        restorer = self._restorer_with_matviews(calls)
        result = restorer.restore(self._opts(no_refresh_matviews=True))

        assert result.success is True
        # Matview data filtered out of every phase, but no analyze / no refresh.
        assert calls == [
            ("section", "pre-data", False, "tables.list"),
            ("section", "data", True, "tables.list"),
            ("section", "post-data", False, "tables.list"),
        ]
        assert result.matviews_deferred == 2
        assert result.matviews_refreshed == 0
        assert result.analyze_ran is False

    def test_analyze_failure_aborts_before_refresh(self):
        calls: list = []
        restorer = self._restorer_with_matviews(calls, analyze_ok=False)
        result = restorer.restore(self._opts())

        assert result.success is False
        assert any("analyze boom" in e for e in result.errors)
        # The matview refresh never runs after a failed ANALYZE.
        assert ("section", None, False, "matviews.list") not in calls
        assert result.matviews_deferred == 2

    def test_refresh_failure_surfaces_as_failure(self):
        calls: list = []
        restorer = self._restorer_with_matviews(calls, refresh_ok=False)
        result = restorer.restore(self._opts())

        assert result.success is False
        assert any("refresh boom" in e for e in result.errors)
        assert result.analyze_ran is True

    def test_no_matview_toc_takes_classic_path(self):
        """A TOC without matview data → no use-list, no analyze phase."""
        calls: list = []
        restorer = DatabaseRestorer()
        no_mv = DatabaseRestorer._parse_toc_lines(
            [
                "215; 1259 16405 TABLE public tb_order postgres",
                "3001; 0 16405 TABLE DATA public tb_order postgres",
            ]
        )
        restorer._validate_dump_format = lambda p: None  # type: ignore[method-assign]
        restorer._list_toc = lambda o: no_mv  # type: ignore[method-assign]

        def fake_run(section, opts, parallel, on_stderr_line=None, use_list=None):
            calls.append((section, parallel, use_list))
            return RestoreResult(success=True, phases_completed=[section])

        restorer._run_section = fake_run  # type: ignore[method-assign]
        result = restorer.restore(self._opts())

        assert calls == [
            ("pre-data", False, None),
            ("data", True, None),  # no -L use-list: byte-for-byte the classic path
            ("post-data", False, None),
        ]
        assert result.matviews_deferred is None
        assert result.matviews_refreshed is None
        assert result.analyze_ran is False

    def test_use_lists_written_with_correct_partition(self):
        """_prepare_use_lists writes tables.list (no matview) + matviews.list (only matview)."""
        entries = DatabaseRestorer._parse_toc_lines(_SAMPLE_TOC.splitlines())
        non_matview, matview_data = DatabaseRestorer._partition_entries(entries)
        import contextlib

        with contextlib.ExitStack() as stack:
            tables_list, matviews_list = DatabaseRestorer()._prepare_use_lists(
                stack, non_matview, matview_data
            )
            assert tables_list is not None and matviews_list is not None
            tables_txt = tables_list.read_text()
            matviews_txt = matviews_list.read_text()

        # matview REFRESH entries only in matviews.list; base table data only in tables.list.
        assert "MATERIALIZED VIEW DATA" not in tables_txt
        assert "TABLE DATA public tb_order" in tables_txt
        assert "MATERIALIZED VIEW DATA public mv_maintenance_price" in matviews_txt
        assert "TABLE DATA" not in matviews_txt


# ---------------------------------------------------------------------------
# Password handling: a password-authenticated server
# ---------------------------------------------------------------------------


class TestPasswordReachesTheSubprocess:
    """A password-authenticated server is reachable, and the password stays off argv.

    Every restore phase — pg_restore per section and the psql ANALYZE — runs as a
    subprocess, so a password held only by the caller never reaches libpq unless
    it is put in the child's environment. Without this, `confiture restore` and
    `confiture test-db provision --from-artifact` fail with `fe_sendauth: no
    password supplied` against any server that is not trust/peer-authenticated.
    """

    def _opts(self, **kwargs) -> RestoreOptions:
        defaults = {
            "backup_path": Path("d.pgdump"),
            "target_db": "db",
            "host": "db.internal",
            "username": "migrator",
            "password": "s3cret",
        }
        defaults.update(kwargs)
        return RestoreOptions(**defaults)

    def test_pg_restore_gets_pgpassword_in_env(self):
        mock_proc = _make_proc([], 0)
        with patch("subprocess.Popen", return_value=mock_proc) as popen:
            DatabaseRestorer()._run_section("pre-data", self._opts(), parallel=False)
        assert popen.call_args.kwargs["env"]["PGPASSWORD"] == "s3cret"

    def test_password_never_appears_on_argv(self):
        mock_proc = _make_proc([], 0)
        with patch("subprocess.Popen", return_value=mock_proc) as popen:
            DatabaseRestorer()._run_section("pre-data", self._opts(), parallel=False)
        assert "s3cret" not in " ".join(popen.call_args.args[0])

    def test_analyze_gets_pgpassword_in_env(self):
        mock_proc = _make_proc([], 0)
        with patch("subprocess.Popen", return_value=mock_proc) as popen:
            DatabaseRestorer()._run_analyze(self._opts())
        assert popen.call_args.kwargs["env"]["PGPASSWORD"] == "s3cret"

    def test_no_password_leaves_env_alone(self):
        """Without a password the child inherits the ambient env, PG* vars included."""
        mock_proc = _make_proc([], 0)
        with patch("subprocess.Popen", return_value=mock_proc) as popen:
            DatabaseRestorer()._run_section("pre-data", self._opts(password=None), parallel=False)
        assert "PGPASSWORD" not in popen.call_args.kwargs["env"]

    def test_table_count_validation_connects_with_the_password(self):
        """--min-tables opens its own psycopg connection; it needs the credential too."""
        mock_conn, _ = _make_db_mock((7,))
        with patch("psycopg.connect", return_value=mock_conn) as connect:
            DatabaseRestorer()._validate_table_count(self._opts(min_tables=1))
        assert connect.call_args.kwargs["password"] == "s3cret"
