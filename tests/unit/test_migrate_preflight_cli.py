"""Unit tests for `migrate preflight --against` CLI option."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from confiture.cli.commands.migrate_analysis import (
    _preflight_version_from_filename,
    _resolve_preflight_pending,
)
from confiture.cli.main import app
from confiture.models.results import PreflightAgainstMigration, PreflightAgainstResult


@pytest.fixture()
def runner():
    return CliRunner()


def _mock_session(against_result):
    """Return a patched MigratorSession that yields a fixed run_against result."""
    mock_instance = MagicMock()
    mock_instance.__enter__ = lambda s: mock_instance
    mock_instance.__exit__ = MagicMock(return_value=False)
    mock_instance.run_against.return_value = against_result
    return mock_instance


# ---------------------------------------------------------------------------
# _preflight_version_from_filename
# ---------------------------------------------------------------------------


def test_version_from_up_sql():
    assert _preflight_version_from_filename("20260428000000_a.up.sql") == "20260428000000"


def test_version_from_py():
    assert _preflight_version_from_filename("20260428000000_add_idx.py") == "20260428000000"


def test_version_from_numeric_prefix():
    assert _preflight_version_from_filename("001_init.up.sql") == "001"


# ---------------------------------------------------------------------------
# _resolve_preflight_pending — since filtering
# ---------------------------------------------------------------------------


def test_since_filters_migrations(tmp_path):
    (tmp_path / "20260401000000_a.up.sql").write_text("")
    (tmp_path / "20260428000000_b.up.sql").write_text("")
    (tmp_path / "20260429000000_c.up.sql").write_text("")

    files = _resolve_preflight_pending(
        tmp_path,
        config_path=None,
        env_name=None,
        since="20260428000000",
    )
    versions = [_preflight_version_from_filename(f.name) for f in files]

    assert "20260401000000" not in versions  # before since — excluded
    assert "20260428000000" in versions  # equal to since — INCLUDED (>=)
    assert "20260429000000" in versions  # after since — included


def test_since_no_matches_returns_empty(tmp_path):
    (tmp_path / "20260401000000_a.up.sql").write_text("")
    files = _resolve_preflight_pending(
        tmp_path,
        config_path=None,
        env_name=None,
        since="20260501000000",
    )
    assert files == []


def test_no_filter_returns_all(tmp_path):
    (tmp_path / "20260401000000_a.up.sql").write_text("")
    (tmp_path / "20260428000000_b.up.sql").write_text("")
    files = _resolve_preflight_pending(
        tmp_path,
        config_path=None,
        env_name=None,
        since=None,
    )
    assert len(files) == 2


# ---------------------------------------------------------------------------
# _resolve_preflight_pending — --config pending detection
# ---------------------------------------------------------------------------


def test_config_detects_pending(tmp_path):
    with (
        patch("confiture.cli.commands.migrate_analysis._resolve_config") as mock_rc,
        patch("confiture.cli.commands.migrate_analysis.load_config") as mock_lc,
        patch("confiture.cli.commands.migrate_analysis.create_connection") as mock_cc,
        patch("confiture.cli.commands.migrate_analysis.Migrator") as MockMigrator,
    ):
        mock_rc.return_value = Path("db/environments/prod.yaml")
        mock_lc.return_value = {"database_url": "postgresql://prod/db"}
        mock_cc.return_value = MagicMock()
        mock_migrator = MagicMock()
        mock_migrator.find_pending.return_value = [tmp_path / "20260429000000_new.up.sql"]
        MockMigrator.return_value = mock_migrator

        files = _resolve_preflight_pending(
            tmp_path,
            config_path=Path("db/environments/prod.yaml"),
            env_name=None,
            since=None,
        )

    assert len(files) == 1
    assert "20260429000000" in files[0].name


# ---------------------------------------------------------------------------
# CLI: --against happy path
# ---------------------------------------------------------------------------


def test_against_no_filter_runs_all(runner, tmp_path):
    (tmp_path / "20260428000000_a.up.sql").write_text("SELECT 1;")
    (tmp_path / "20260428000000_a.down.sql").write_text("SELECT 1;")

    against_result = PreflightAgainstResult(
        migrations=[PreflightAgainstMigration("20260428000000", "a", True, execution_time_ms=42)],
        against_url="postgresql://localhost/preflight",
    )

    with patch(
        "confiture.cli.commands.migrate_analysis.MigratorSession",
        return_value=_mock_session(against_result),
    ):
        result = runner.invoke(
            app,
            [
                "migrate",
                "preflight",
                "--against",
                "postgresql://localhost/preflight",
                "--migrations-dir",
                str(tmp_path),
            ],
        )

    assert result.exit_code == 0
    assert "20260428000000" in result.output
    assert "Rolled back" in result.output


# ---------------------------------------------------------------------------
# CLI: replay failure → exit 7 (#151, via preflight_exit_code)
# ---------------------------------------------------------------------------


def test_against_failure_exits_7(runner, tmp_path):
    """A failed replay is an error-severity issue → exit 7 (#151), not the old exit 1."""
    (tmp_path / "20260428000000_a.up.sql").write_text("SELECT 1;")
    (tmp_path / "20260428000000_a.down.sql").write_text("SELECT 1;")

    against_result = PreflightAgainstResult(
        migrations=[
            PreflightAgainstMigration("20260428000000", "a", False, error="column does not exist"),
        ],
        against_url="postgresql://localhost/preflight",
    )

    with patch(
        "confiture.cli.commands.migrate_analysis.MigratorSession",
        return_value=_mock_session(against_result),
    ):
        result = runner.invoke(
            app,
            [
                "migrate",
                "preflight",
                "--against",
                "postgresql://localhost/preflight",
                "--migrations-dir",
                str(tmp_path),
            ],
        )

    assert result.exit_code == 7
    # Text mode is unchanged — the human still sees the DB error inline.
    assert "column does not exist" in result.output


# ---------------------------------------------------------------------------
# CLI: skipped migration → exit 0
# ---------------------------------------------------------------------------


def test_skipped_migration_exits_0(runner, tmp_path):
    """Skipped (non-transactional) migrations are neutral — exit 0."""
    (tmp_path / "20260428000000_a.up.sql").write_text("SELECT 1;")
    (tmp_path / "20260428000000_a.down.sql").write_text("SELECT 1;")

    against_result = PreflightAgainstResult(
        migrations=[
            PreflightAgainstMigration(
                "20260428000000",
                "add_idx",
                False,
                skipped=True,
                skipped_reason="non-transactional: cannot run inside SAVEPOINT",
            ),
        ],
        against_url="postgresql://localhost/preflight",
    )

    with patch(
        "confiture.cli.commands.migrate_analysis.MigratorSession",
        return_value=_mock_session(against_result),
    ):
        result = runner.invoke(
            app,
            [
                "migrate",
                "preflight",
                "--against",
                "postgresql://localhost/preflight",
                "--migrations-dir",
                str(tmp_path),
            ],
        )

    assert result.exit_code == 0
    assert "skipped" in result.output.lower()
    assert "non-transactional" in result.output


# ---------------------------------------------------------------------------
# CLI: --allow-non-transactional forwarded
# ---------------------------------------------------------------------------


def test_allow_non_transactional_flag_passed(runner, tmp_path):
    """--allow-non-transactional is forwarded to session.run_against()."""
    (tmp_path / "20260428000000_a.up.sql").write_text("SELECT 1;")
    (tmp_path / "20260428000000_a.down.sql").write_text("SELECT 1;")

    against_result = PreflightAgainstResult(
        migrations=[PreflightAgainstMigration("20260428000000", "a", True)],
        against_url="postgresql://localhost/preflight",
    )
    mock_instance = _mock_session(against_result)

    with patch(
        "confiture.cli.commands.migrate_analysis.MigratorSession",
        return_value=mock_instance,
    ):
        runner.invoke(
            app,
            [
                "migrate",
                "preflight",
                "--against",
                "postgresql://localhost/preflight",
                "--allow-non-transactional",
                "--migrations-dir",
                str(tmp_path),
            ],
        )

    mock_instance.run_against.assert_called_once()
    call_kwargs = mock_instance.run_against.call_args.kwargs
    assert call_kwargs.get("allow_non_transactional") is True


# ---------------------------------------------------------------------------
# CLI: JSON output structure
# ---------------------------------------------------------------------------


def test_against_json_is_unified_envelope(runner, tmp_path):
    """#151: --against JSON is the unified {ok, summary, issues[]} envelope.

    The legacy {static, against, hints} keys are gone; the shape now matches
    the no---against path, with run-level metadata (db_consumed) in summary.
    """
    (tmp_path / "20260428000000_a.up.sql").write_text("SELECT 1;")
    (tmp_path / "20260428000000_a.down.sql").write_text("SELECT 1;")

    against_result = PreflightAgainstResult(
        migrations=[PreflightAgainstMigration("20260428000000", "a", True)],
        against_url="postgresql://localhost/preflight",
    )

    with patch(
        "confiture.cli.commands.migrate_analysis.MigratorSession",
        return_value=_mock_session(against_result),
    ):
        result = runner.invoke(
            app,
            [
                "migrate",
                "preflight",
                "--against",
                "postgresql://localhost/preflight",
                "--format",
                "json",
                "--migrations-dir",
                str(tmp_path),
            ],
        )

    data = json.loads(result.output)
    assert "static" not in data
    assert "against" not in data
    assert "hints" not in data
    assert set(data) >= {"ok", "summary", "issues"}
    assert data["ok"] is True
    assert data["issues"] == []
    assert data["summary"]["migrations_checked"] == 1
    assert data["summary"]["db_consumed"] is False


def test_against_json_replay_failure_is_issue(runner, tmp_path):
    """#151: a failed replay surfaces as a PFLIGHT_REPLAY_FAILED issue, ok=False, exit 7."""
    (tmp_path / "20260428000000_a.up.sql").write_text("SELECT 1;")
    (tmp_path / "20260428000000_a.down.sql").write_text("SELECT 1;")

    against_result = PreflightAgainstResult(
        migrations=[
            PreflightAgainstMigration(
                "20260428000000", "a", False, error="column x does not exist"
            ),
        ],
        against_url="postgresql://localhost/preflight",
    )

    with patch(
        "confiture.cli.commands.migrate_analysis.MigratorSession",
        return_value=_mock_session(against_result),
    ):
        result = runner.invoke(
            app,
            [
                "migrate",
                "preflight",
                "--against",
                "postgresql://localhost/preflight",
                "--format",
                "json",
                "--migrations-dir",
                str(tmp_path),
            ],
        )

    assert result.exit_code == 7
    data = json.loads(result.output)
    assert data["ok"] is False
    replay = [i for i in data["issues"] if i["code"] == "PFLIGHT_REPLAY_FAILED"]
    assert len(replay) == 1
    assert replay[0]["migration"] == "20260428000000"
    assert replay[0]["details"]["error"] == "column x does not exist"
    assert data["summary"]["errors"] == 1


def test_against_static_error_exits_7(runner, tmp_path):
    """#151: a static error (missing .down.sql) fails the --against run too (exit 7)."""
    (tmp_path / "20260428000000_a.up.sql").write_text("SELECT 1;")
    # No .down.sql sibling → PFLIGHT_MISSING_DOWN (error).

    against_result = PreflightAgainstResult(
        migrations=[PreflightAgainstMigration("20260428000000", "a", True)],
        against_url="postgresql://localhost/preflight",
    )

    with patch(
        "confiture.cli.commands.migrate_analysis.MigratorSession",
        return_value=_mock_session(against_result),
    ):
        result = runner.invoke(
            app,
            [
                "migrate",
                "preflight",
                "--against",
                "postgresql://localhost/preflight",
                "--format",
                "json",
                "--migrations-dir",
                str(tmp_path),
            ],
        )

    assert result.exit_code == 7
    data = json.loads(result.output)
    assert data["ok"] is False
    assert any(i["code"] == "PFLIGHT_MISSING_DOWN" for i in data["issues"])


def test_json_output_without_against_is_structured_report(runner, tmp_path):
    """#148: no --against → the structured report {ok, summary, issues[]}."""
    (tmp_path / "20260428000000_a.up.sql").write_text("SELECT 1;")
    (tmp_path / "20260428000000_a.down.sql").write_text("SELECT 1;")

    result = runner.invoke(
        app,
        [
            "migrate",
            "preflight",
            "--format",
            "json",
            "--migrations-dir",
            str(tmp_path),
        ],
    )

    data = json.loads(result.output)
    assert "static" not in data  # not the --against envelope
    assert set(data.keys()) >= {"ok", "summary", "issues"}  # structured report
    assert data["ok"] is True
    assert data["summary"]["migrations_checked"] == 1


# ---------------------------------------------------------------------------
# CLI: unreachable URL → exit 3 (#151, harness/connection failure = CONFIG_006)
# ---------------------------------------------------------------------------


def test_against_unreachable_url_exits_3(runner, tmp_path):
    """An unreachable --against URL is a connection failure → exit 3, not exit 2."""
    (tmp_path / "20260428000000_a.up.sql").write_text("SELECT 1;")
    (tmp_path / "20260428000000_a.down.sql").write_text("SELECT 1;")

    with patch(
        "confiture.cli.commands.migrate_analysis.MigratorSession",
        side_effect=Exception("connection refused"),
    ):
        result = runner.invoke(
            app,
            [
                "migrate",
                "preflight",
                "--against",
                "postgresql://localhost/preflight",
                "--migrations-dir",
                str(tmp_path),
            ],
        )

    assert result.exit_code == 3


def test_against_unreachable_url_json_envelope_exits_3(runner, tmp_path):
    """In JSON mode the connection failure emits the {ok:false, error} envelope, exit 3."""
    (tmp_path / "20260428000000_a.up.sql").write_text("SELECT 1;")
    (tmp_path / "20260428000000_a.down.sql").write_text("SELECT 1;")

    with patch(
        "confiture.cli.commands.migrate_analysis.MigratorSession",
        side_effect=Exception("connection refused"),
    ):
        result = runner.invoke(
            app,
            [
                "migrate",
                "preflight",
                "--against",
                "postgresql://localhost/preflight",
                "--format",
                "json",
                "--migrations-dir",
                str(tmp_path),
            ],
        )

    assert result.exit_code == 3
    data = json.loads(result.output)
    assert data["ok"] is False
    assert data["error"]["code"] == "CONFIG_006"


# ---------------------------------------------------------------------------
# CLI: db_consumed warning in text + JSON output
# ---------------------------------------------------------------------------


def test_db_consumed_warning_shown_in_text(runner, tmp_path):
    """db_consumed=True shows the 'reprovision' warning."""
    (tmp_path / "20260428000000_a.up.sql").write_text("SELECT 1;")
    (tmp_path / "20260428000000_a.down.sql").write_text("SELECT 1;")

    against_result = PreflightAgainstResult(
        migrations=[PreflightAgainstMigration("20260428000000", "a", True)],
        against_url="postgresql://localhost/preflight",
        db_consumed=True,
    )

    with patch(
        "confiture.cli.commands.migrate_analysis.MigratorSession",
        return_value=_mock_session(against_result),
    ):
        result = runner.invoke(
            app,
            [
                "migrate",
                "preflight",
                "--against",
                "postgresql://localhost/preflight",
                "--migrations-dir",
                str(tmp_path),
            ],
        )

    assert result.exit_code == 0
    assert "reprovision" in result.output.lower()
    assert "Rolled back" not in result.output


def test_db_consumed_in_json_envelope(runner, tmp_path):
    """#151: db_consumed=True rides in summary (run-level metadata), not a separate block."""
    (tmp_path / "20260428000000_a.up.sql").write_text("SELECT 1;")
    (tmp_path / "20260428000000_a.down.sql").write_text("SELECT 1;")

    against_result = PreflightAgainstResult(
        migrations=[PreflightAgainstMigration("20260428000000", "a", True)],
        against_url="postgresql://localhost/preflight",
        db_consumed=True,
    )

    with patch(
        "confiture.cli.commands.migrate_analysis.MigratorSession",
        return_value=_mock_session(against_result),
    ):
        result = runner.invoke(
            app,
            [
                "migrate",
                "preflight",
                "--against",
                "postgresql://localhost/preflight",
                "--format",
                "json",
                "--migrations-dir",
                str(tmp_path),
            ],
        )

    data = json.loads(result.output)
    assert data["summary"]["db_consumed"] is True


# ---------------------------------------------------------------------------
# _resolve_preflight_pending: .py migration files included
# ---------------------------------------------------------------------------


def test_py_migrations_included_in_all(tmp_path):
    """Both .up.sql and .py files (non-underscore) are collected when no filter."""
    (tmp_path / "20260401000000_a.up.sql").write_text("")
    (tmp_path / "20260401000001_b.py").write_text("")
    (tmp_path / "__init__.py").write_text("")  # should be excluded

    files = _resolve_preflight_pending(
        tmp_path,
        config_path=None,
        env_name=None,
        since=None,
    )
    names = [f.name for f in files]
    assert "20260401000000_a.up.sql" in names
    assert "20260401000001_b.py" in names
    assert "__init__.py" not in names
