"""Unit tests for the `confiture test-db` CLI group (P2).

TestDbProvisioner is mocked, so no database is needed. Builder-backed commands
(provision-template, status) run against a tiny tmp project.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.cli.test_db import (
    _guard_ram_location,
    _prepare_location_dir,
    _resolve_owner,
)
from confiture.core.test_db import (
    CloneResult,
    ManagedDatabase,
    RamSetupResult,
    TemplateState,
    TemplateStatus,
)
from confiture.exceptions import ConfigurationError

runner = CliRunner()

_URL = "postgresql://localhost/confiture_test"


def _project(tmp_path: Path) -> None:
    schema_dir = tmp_path / "db" / "schema"
    schema_dir.mkdir(parents=True)
    (schema_dir / "01.sql").write_text("CREATE TABLE t (id int);")
    env_dir = tmp_path / "db" / "environments"
    env_dir.mkdir(parents=True)
    (env_dir / "local.yaml").write_text(
        f'name: local\ndatabase_url: "{_URL}"\ninclude_dirs:\n  - {schema_dir}\n'
    )


class TestClone:
    @patch("confiture.cli.test_db.TestDbProvisioner")
    def test_clone_invokes_provisioner(self, mock_cls: MagicMock) -> None:
        prov = mock_cls.return_value
        prov.clone.return_value = CloneResult("tmpl", "c0", f"{_URL[:-15]}/c0")
        result = runner.invoke(
            app,
            [
                "test-db",
                "clone",
                "--template",
                "tmpl",
                "--target",
                "c0",
                "--database-url",
                _URL,
                "--format",
                "json",
            ],
        )
        assert result.exit_code == 0
        prov.clone.assert_called_once_with("tmpl", "c0", sync_commit_off=True, max_concurrency=None)
        assert '"target": "c0"' in result.stdout

    @patch("confiture.cli.test_db.TestDbProvisioner")
    def test_clone_no_sync_commit_off_flag(self, mock_cls: MagicMock) -> None:
        prov = mock_cls.return_value
        prov.clone.return_value = CloneResult("tmpl", "c0", f"{_URL[:-15]}/c0")
        result = runner.invoke(
            app,
            [
                "test-db",
                "clone",
                "--template",
                "tmpl",
                "--target",
                "c0",
                "--database-url",
                _URL,
                "--no-sync-commit-off",
            ],
        )
        assert result.exit_code == 0
        prov.clone.assert_called_once_with(
            "tmpl", "c0", sync_commit_off=False, max_concurrency=None
        )

    @patch("confiture.cli.test_db.TestDbProvisioner")
    def test_clone_max_concurrency_flag(self, mock_cls: MagicMock) -> None:
        prov = mock_cls.return_value
        prov.clone.return_value = CloneResult("tmpl", "c0", f"{_URL[:-15]}/c0")
        result = runner.invoke(
            app,
            [
                "test-db",
                "clone",
                "--template",
                "tmpl",
                "--target",
                "c0",
                "--database-url",
                _URL,
                "--max-clone-concurrency",
                "3",
            ],
        )
        assert result.exit_code == 0
        prov.clone.assert_called_once_with("tmpl", "c0", sync_commit_off=True, max_concurrency=3)

    @patch("confiture.cli.test_db.TestDbProvisioner")
    def test_clone_json_redacts_dsn_password(self, mock_cls: MagicMock) -> None:
        prov = mock_cls.return_value
        prov.clone.return_value = CloneResult(
            "tmpl", "c0", "postgresql://user:secretpw@host:5432/c0"
        )
        result = runner.invoke(
            app,
            [
                "test-db",
                "clone",
                "--template",
                "tmpl",
                "--target",
                "c0",
                "--database-url",
                "postgresql://user:secretpw@host:5432/db",
                "--format",
                "json",
            ],
        )
        assert result.exit_code == 0
        assert "secretpw" not in result.stdout
        assert "***" in result.stdout


class TestDrop:
    @patch("confiture.cli.test_db.TestDbProvisioner")
    def test_drop_invokes_provisioner(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.drop.return_value = True
        result = runner.invoke(app, ["test-db", "drop", "--target", "c0", "--database-url", _URL])
        assert result.exit_code == 0
        mock_cls.return_value.drop.assert_called_once_with("c0", force=False)

    @patch("confiture.cli.test_db.TestDbProvisioner")
    def test_drop_unmanaged_exits_5(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.drop.side_effect = ConfigurationError(
            "Refusing to drop 'postgres': not a confiture-managed template/clone.",
            error_code="CONFIG_010",
        )
        result = runner.invoke(
            app, ["test-db", "drop", "--target", "postgres", "--database-url", _URL]
        )
        assert result.exit_code == 5


class TestStatus:
    @patch("confiture.cli.test_db.TestDbProvisioner")
    def test_status_current_exits_0(self, mock_cls: MagicMock, tmp_path: Path) -> None:
        _project(tmp_path)
        mock_cls.return_value.template_status.return_value = TemplateStatus(
            "tmpl", TemplateState.CURRENT, "h", "h"
        )
        result = runner.invoke(
            app,
            ["test-db", "status", "--template", "tmpl", "--project-dir", str(tmp_path)],
        )
        assert result.exit_code == 0

    @patch("confiture.cli.test_db.TestDbProvisioner")
    def test_status_stale_exits_1(self, mock_cls: MagicMock, tmp_path: Path) -> None:
        _project(tmp_path)
        mock_cls.return_value.template_status.return_value = TemplateStatus(
            "tmpl", TemplateState.STALE, "old", "new"
        )
        result = runner.invoke(
            app,
            ["test-db", "status", "--template", "tmpl", "--project-dir", str(tmp_path)],
        )
        assert result.exit_code == 1


class TestProvisionTemplate:
    @patch("confiture.cli.test_db.TestDbProvisioner")
    def test_provision_ddl_path(self, mock_cls: MagicMock, tmp_path: Path) -> None:
        _project(tmp_path)
        mock_cls.return_value.provision_template.return_value = TemplateStatus(
            "tmpl", TemplateState.CURRENT, "h", "h"
        )
        result = runner.invoke(
            app,
            ["test-db", "provision-template", "--template", "tmpl", "--project-dir", str(tmp_path)],
        )
        assert result.exit_code == 0
        # DDL path → schema_sql passed, not from_artifact.
        _, kwargs = mock_cls.return_value.provision_template.call_args
        assert kwargs.get("schema_sql") is not None
        assert kwargs.get("from_artifact") is None


class TestRamSetupHelpers:
    """The pure CLI-layer helpers (allowlist, owner resolution, dir prep)."""

    def test_guard_allows_tmpfs_roots(self) -> None:
        _guard_ram_location("/dev/shm/ram_ts", force=False)  # no raise
        _guard_ram_location("/run/ram_ts", force=False)  # no raise

    def test_guard_rejects_non_tmpfs_without_force(self) -> None:
        with pytest.raises(ConfigurationError, match="Refusing"):
            _guard_ram_location("/var/lib/postgresql/data", force=False)

    def test_guard_bypassed_by_force(self) -> None:
        _guard_ram_location("/var/lib/postgresql/data", force=True)  # no raise

    def test_resolve_owner_unknown_user_raises(self) -> None:
        with pytest.raises(ConfigurationError, match="does not exist"):
            _resolve_owner("definitely_no_such_user_xyz")

    def test_resolve_owner_root_resolves_to_uid_0(self) -> None:
        # root exists on every Linux host → deterministic.
        assert _resolve_owner("root") == (0, 0)

    @patch("confiture.cli.test_db.os.chown")
    @patch("confiture.cli.test_db.os.makedirs")
    def test_prepare_dir_true_on_success(self, _md: MagicMock, _chown: MagicMock) -> None:
        assert _prepare_location_dir("/dev/shm/ram_ts", 70, 70) is True

    @patch("confiture.cli.test_db.os.chown", side_effect=PermissionError("not permitted"))
    @patch("confiture.cli.test_db.os.makedirs")
    def test_prepare_dir_false_when_chown_denied(self, _md: MagicMock, _chown: MagicMock) -> None:
        assert _prepare_location_dir("/dev/shm/ram_ts", 70, 70) is False


class TestRamSetupCli:
    def _pw(self) -> object:
        return type("PW", (), {"pw_uid": 70, "pw_gid": 70})()

    @patch("confiture.cli.test_db.os.makedirs")
    @patch("confiture.cli.test_db.os.chown", side_effect=PermissionError("not permitted"))
    @patch("confiture.cli.test_db.pwd.getpwnam")
    def test_guided_mode_prints_sudo_command(
        self, mock_getpwnam: MagicMock, _chown: MagicMock, _md: MagicMock
    ) -> None:
        # chown denied → guided mode: no DB is touched (setup returns early), the
        # privileged command is printed, and the action-required exit code is used.
        mock_getpwnam.return_value = self._pw()
        result = runner.invoke(
            app,
            [
                "test-db",
                "ram-setup",
                "--tablespace",
                "ram_ts",
                "--location",
                "/dev/shm/ram_ts",
                "--database-url",
                _URL,
            ],
        )
        assert result.exit_code == 5
        assert "sudo install -d" in result.stdout
        assert "/dev/shm/ram_ts" in result.stdout

    @patch("confiture.cli.test_db.os.makedirs")
    @patch("confiture.cli.test_db.os.chown", side_effect=PermissionError("not permitted"))
    @patch("confiture.cli.test_db.pwd.getpwnam")
    def test_guided_mode_json_payload(
        self, mock_getpwnam: MagicMock, _chown: MagicMock, _md: MagicMock
    ) -> None:
        mock_getpwnam.return_value = self._pw()
        result = runner.invoke(
            app,
            [
                "test-db",
                "ram-setup",
                "--tablespace",
                "ram_ts",
                "--location",
                "/dev/shm/ram_ts",
                "--database-url",
                _URL,
                "--format",
                "json",
            ],
        )
        assert result.exit_code == 5
        assert '"action_required": true' in result.stdout
        assert '"action_command":' in result.stdout

    def test_rejects_non_tmpfs_location(self) -> None:
        result = runner.invoke(
            app,
            [
                "test-db",
                "ram-setup",
                "--tablespace",
                "ram_ts",
                "--location",
                "/var/lib/postgresql/data",
                "--database-url",
                _URL,
            ],
        )
        assert result.exit_code == 5  # hard CONFIG_010 (allowlist), not action_required

    @patch("confiture.cli.test_db._prepare_location_dir", return_value=True)
    @patch("confiture.cli.test_db._resolve_owner", return_value=(70, 70))
    @patch("confiture.cli.test_db.TestDbProvisioner")
    def test_success_path_threads_args(
        self, mock_cls: MagicMock, _owner: MagicMock, _prep: MagicMock
    ) -> None:
        mock_cls.return_value.setup_ram_tablespace.return_value = RamSetupResult(
            "ram_ts", "/dev/shm/ram_ts", "postgres", True, False, ["ram_ts_db_gw0"]
        )
        result = runner.invoke(
            app,
            [
                "test-db",
                "ram-setup",
                "--tablespace",
                "ram_ts",
                "--location",
                "/dev/shm/ram_ts",
                "--database-url",
                _URL,
                "--force",
            ],
        )
        assert result.exit_code == 0
        _, kwargs = mock_cls.return_value.setup_ram_tablespace.call_args
        assert kwargs["dir_prepared"] is True
        assert kwargs["force"] is True
        assert kwargs["owner"] == "postgres"
        assert "Reset" in result.stdout

    @patch("confiture.cli.test_db._prepare_location_dir", return_value=True)
    @patch("confiture.cli.test_db._resolve_owner", return_value=(70, 70))
    @patch("confiture.cli.test_db.TestDbProvisioner")
    def test_success_path_json(
        self, mock_cls: MagicMock, _owner: MagicMock, _prep: MagicMock
    ) -> None:
        mock_cls.return_value.setup_ram_tablespace.return_value = RamSetupResult(
            "ram_ts", "/dev/shm/ram_ts", "postgres", False, False, []
        )
        result = runner.invoke(
            app,
            [
                "test-db",
                "ram-setup",
                "--tablespace",
                "ram_ts",
                "--location",
                "/dev/shm/ram_ts",
                "--database-url",
                _URL,
                "--format",
                "json",
            ],
        )
        assert result.exit_code == 0
        assert '"action_required": false' in result.stdout
        assert '"recreated": false' in result.stdout


class TestListAndPrune:
    @patch("confiture.cli.test_db.TestDbProvisioner")
    def test_list_json(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.list_databases.return_value = [
            ManagedDatabase("tmpl", "template", "h"),
            ManagedDatabase("c0", "clone", "tmpl"),
        ]
        result = runner.invoke(app, ["test-db", "list", "--database-url", _URL, "--format", "json"])
        assert result.exit_code == 0
        assert '"name": "c0"' in result.stdout

    @patch("confiture.cli.test_db.TestDbProvisioner")
    def test_prune_json(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.prune.return_value = ["c0", "c1"]
        result = runner.invoke(
            app,
            ["test-db", "prune", "--template", "tmpl", "--database-url", _URL, "--format", "json"],
        )
        assert result.exit_code == 0
        mock_cls.return_value.prune.assert_called_once_with("tmpl")
        assert '"dropped": [' in result.stdout
