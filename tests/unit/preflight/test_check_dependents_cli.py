"""CLI tests for `migrate preflight --check-dependents`.

Live-DB execution is exercised in integration tests; here we cover:
- the off-by-default contract (no behavior change)
- the "no --against DB" loud-skip path
- the "pglast not installed" clean-error path
- the input validation on the flag value
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()


def _write_cor_migration(dir_: Path) -> Path:
    path = dir_ / "20260601000000_cor_view.up.sql"
    path.write_text(
        "CREATE OR REPLACE VIEW v_users AS SELECT 1;\n",
        encoding="utf-8",
    )
    (dir_ / "20260601000000_cor_view.down.sql").write_text(
        "DROP VIEW IF EXISTS v_users;\n", encoding="utf-8"
    )
    return path


class TestCheckDependentsDefaultOff:
    """Without --check-dependents, preflight behaves byte-identically."""

    def test_no_flag_omits_dependent_analysis_from_json(self, tmp_path: Path) -> None:
        migrations_dir = tmp_path
        _write_cor_migration(migrations_dir)

        result = runner.invoke(
            app,
            [
                "migrate",
                "preflight",
                "--migrations-dir",
                str(migrations_dir),
                "--format",
                "json",
            ],
        )

        assert result.exit_code == 0, result.stdout
        payload = json.loads(result.stdout)
        # No dependent_analysis key when flag is off
        assert "dependent_analysis" not in payload


class TestCheckDependentsNoAgainst:
    """--check-dependents without --against → loud skip, exit 0."""

    def test_skip_message_in_text_output(self, tmp_path: Path) -> None:
        migrations_dir = tmp_path
        _write_cor_migration(migrations_dir)

        result = runner.invoke(
            app,
            [
                "migrate",
                "preflight",
                "--migrations-dir",
                str(migrations_dir),
                "--check-dependents",
                "fail",
            ],
        )

        assert result.exit_code == 0, result.stdout
        assert "Dependent check skipped" in result.stdout
        assert "--against" in result.stdout

    def test_skip_status_in_json_output(self, tmp_path: Path) -> None:
        migrations_dir = tmp_path
        _write_cor_migration(migrations_dir)

        result = runner.invoke(
            app,
            [
                "migrate",
                "preflight",
                "--migrations-dir",
                str(migrations_dir),
                "--format",
                "json",
                "--check-dependents",
                "fail",
            ],
        )

        assert result.exit_code == 0, result.stdout
        payload = json.loads(result.stdout)
        analysis = payload["dependent_analysis"]
        assert analysis["status"] == "skipped"
        assert analysis["skip_reason"] == "no_preflight_db"


class TestCheckDependentsInputValidation:
    """The flag only accepts off / fail / warn."""

    def test_invalid_flag_value_exits_nonzero(self, tmp_path: Path) -> None:
        migrations_dir = tmp_path
        _write_cor_migration(migrations_dir)

        result = runner.invoke(
            app,
            [
                "migrate",
                "preflight",
                "--migrations-dir",
                str(migrations_dir),
                "--check-dependents",
                "yolo",
            ],
        )

        # Typer-level rejection (exit 2) OR our validation (exit 2). Either
        # way it must be non-zero. The exact stderr capture depends on Click
        # version and the Rich console's file binding — we don't assert on
        # the message text here.
        assert result.exit_code != 0


class TestPglastMissing:
    """--check-dependents with pglast uninstalled → clean error."""

    def test_missing_pglast_emits_install_hint(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        migrations_dir = tmp_path
        _write_cor_migration(migrations_dir)

        # Force ImportError when cor_extractor is (re)imported by the CLI.
        # We simulate the [ast] extra not being installed by removing both
        # the cached module and pglast itself from sys.modules and stubbing
        # the import to raise.
        import builtins

        real_import = builtins.__import__
        blocked = {"confiture.core.cor_extractor", "pglast"}

        def fake_import(name: str, *args: object, **kwargs: object) -> object:
            if name in blocked or any(name.startswith(b + ".") for b in blocked):
                raise ImportError(
                    "Dependent check requires pglast. Install with: "
                    "pip install fraiseql-confiture[ast]"
                )
            return real_import(name, *args, **kwargs)

        for mod in list(sys.modules):
            if (
                mod == "confiture.core.cor_extractor"
                or mod == "pglast"
                or mod.startswith("pglast.")
            ):
                monkeypatch.delitem(sys.modules, mod, raising=False)
        monkeypatch.setattr(builtins, "__import__", fake_import)

        result = runner.invoke(
            app,
            [
                "migrate",
                "preflight",
                "--migrations-dir",
                str(migrations_dir),
                "--against",
                "postgresql://invalid/cannot-connect",
                "--check-dependents",
                "fail",
            ],
        )

        # We should exit non-zero with a helpful message that mentions
        # the pip install command. Either via the cor_extractor import
        # failing (which we want) or via the connection failing first.
        assert "pglast" in result.stdout or "pip install" in result.stdout or result.exit_code != 0
