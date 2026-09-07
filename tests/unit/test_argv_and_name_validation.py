"""Values that become a filename or a subprocess argument are validated first.

Reviewer extras from the 2026-09-06 review:

* ``migrate generate NAME`` spliced NAME into a path — ``../../x`` walked out of
  the migrations directory; the contract is ``^[a-z0-9_]+$`` and exit 5;
* an SSH ``user`` could start with ``-``, so ``-oProxyCommand=x@host`` was an
  option to ``ssh``, not a destination; the argv now also carries ``--`` before
  the destination so no later change can reopen that;
* squawk and ``git diff`` receive ``--`` before any file list, and
  ``git ls-tree`` is never handed an option-shaped ref.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.config.environment import SshTunnelConfig
from confiture.core import unified_linter
from confiture.core.git_schema import GitSchemaBuilder
from confiture.core.ssh_tunnel import _build_ssh_cmd
from confiture.core.unified_linter import SquawkRunner, UnifiedLinter
from confiture.exceptions import GitError

runner = CliRunner()


# ---------------------------------------------------------------------------
# migrate generate NAME
# ---------------------------------------------------------------------------


class TestMigrateGenerateName:
    @pytest.mark.parametrize(
        "bad",
        ["../../x", "Bad Name", "x;rm -rf .", "CamelCase", "-dash", "with.dot", "ünïcode", ""],
    )
    def test_rejects_anything_but_snake_case_and_writes_nothing(
        self, tmp_path: Path, bad: str
    ) -> None:
        migrations = tmp_path / "db" / "migrations"
        # `--` so that a name beginning with `-` reaches the command instead of
        # being parsed by Click as an unknown option (that path exits 2).
        result = runner.invoke(
            app,
            [
                "migrate",
                "generate",
                "--migrations-dir",
                str(migrations),
                "--no-snapshot",
                "--",
                bad,
            ],
        )

        assert result.exit_code == 5, result.output
        assert list(tmp_path.rglob("*")) == [], "nothing may be written for a rejected name"

    def test_json_mode_reports_the_rejection_as_an_envelope(self, tmp_path: Path) -> None:
        import json

        migrations = tmp_path / "db" / "migrations"
        result = runner.invoke(
            app,
            [
                "migrate",
                "generate",
                "../../x",
                "--migrations-dir",
                str(migrations),
                "--no-snapshot",
                "--format",
                "json",
            ],
        )
        assert result.exit_code == 5, result.output
        payload = json.loads(result.stdout)
        assert payload["ok"] is False
        assert payload["error"]["code"] == "VALID_001"

    def test_snake_case_is_accepted(self, tmp_path: Path) -> None:
        migrations = tmp_path / "db" / "migrations"
        result = runner.invoke(
            app,
            [
                "migrate",
                "generate",
                "add_users_2",
                "--migrations-dir",
                str(migrations),
                "--no-snapshot",
            ],
        )
        assert result.exit_code == 0, result.output
        assert [p.name for p in migrations.glob("*_add_users_2.py")]


# ---------------------------------------------------------------------------
# ssh
# ---------------------------------------------------------------------------


class TestSshArgv:
    @pytest.mark.parametrize("bad", ["-oProxyCommand=x", "-", "-root", ".hidden", "@host"])
    def test_user_must_start_with_a_word_character(self, bad: str) -> None:
        with pytest.raises(ValueError):
            SshTunnelConfig(host="h", user=bad)

    @pytest.mark.parametrize("good", ["deploy", "lionel", "svc_account", "a.b-c@d", "u1"])
    def test_ordinary_users_are_accepted(self, good: str) -> None:
        assert SshTunnelConfig(host="h", user=good).user == good

    def test_argv_separates_options_from_the_destination(self) -> None:
        cmd = _build_ssh_cmd(SshTunnelConfig(host="h", user="u"), local_port=1234)
        assert cmd[-2:] == ["--", "u@h"]

    def test_argv_separator_present_without_user(self) -> None:
        cmd = _build_ssh_cmd(SshTunnelConfig(host="h"), local_port=1234)
        assert cmd[-2:] == ["--", "h"]


# ---------------------------------------------------------------------------
# squawk / git diff / git ls-tree
# ---------------------------------------------------------------------------


def _capture_run(monkeypatch: pytest.MonkeyPatch, module, stdout: str = "") -> dict:
    captured: dict = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = list(argv)
        return MagicMock(returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    return captured


class TestSubprocessSeparators:
    def test_squawk_gets_a_separator_before_the_file_list(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(unified_linter.shutil, "which", lambda name: "/usr/bin/squawk")
        captured = _capture_run(monkeypatch, unified_linter, stdout="[]")

        SquawkRunner().run([Path("-x.sql"), Path("a.sql")])

        argv = captured["argv"]
        separator = argv.index("--")
        assert argv[separator + 1 :] == ["-x.sql", "a.sql"]
        assert argv[:separator] == ["squawk", "--reporter=json"]

    def test_git_diff_ends_its_options_explicitly(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured = _capture_run(monkeypatch, unified_linter, stdout="")

        UnifiedLinter()._get_changed_sql_files()

        assert captured["argv"] == ["git", "diff", "--name-only", "--diff-filter=AM", "--"]

    @pytest.mark.parametrize("ref", ["--output=x", "-x", "--format=%(objectname)"])
    def test_git_ls_tree_never_receives_an_option_shaped_ref(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ref: str
    ) -> None:
        calls: list[list[str]] = []
        monkeypatch.setattr(
            subprocess, "run", lambda argv, **kw: calls.append(list(argv)) or MagicMock()
        )
        builder = GitSchemaBuilder.__new__(GitSchemaBuilder)
        builder.repo_path = tmp_path

        with pytest.raises(GitError):
            builder._get_files_at_ref(ref, Path("db/schema"), recursive=True)

        assert calls == []
