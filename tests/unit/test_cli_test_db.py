"""Unit tests for the `confiture test-db` CLI group (P2).

TestDbProvisioner is mocked, so no database is needed. Builder-backed commands
(provision-template, status) run against a tiny tmp project.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.test_db import (
    CloneResult,
    ManagedDatabase,
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
            ["test-db", "clone", "--template", "tmpl", "--target", "c0",
             "--database-url", _URL, "--format", "json"],
        )
        assert result.exit_code == 0
        prov.clone.assert_called_once_with("tmpl", "c0")
        assert '"target": "c0"' in result.stdout

    @patch("confiture.cli.test_db.TestDbProvisioner")
    def test_clone_json_redacts_dsn_password(self, mock_cls: MagicMock) -> None:
        prov = mock_cls.return_value
        prov.clone.return_value = CloneResult(
            "tmpl", "c0", "postgresql://user:secretpw@host:5432/c0"
        )
        result = runner.invoke(
            app,
            ["test-db", "clone", "--template", "tmpl", "--target", "c0",
             "--database-url", "postgresql://user:secretpw@host:5432/db",
             "--format", "json"],
        )
        assert result.exit_code == 0
        assert "secretpw" not in result.stdout
        assert "***" in result.stdout


class TestDrop:
    @patch("confiture.cli.test_db.TestDbProvisioner")
    def test_drop_invokes_provisioner(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.drop.return_value = True
        result = runner.invoke(
            app, ["test-db", "drop", "--target", "c0", "--database-url", _URL]
        )
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
            ["test-db", "provision-template", "--template", "tmpl",
             "--project-dir", str(tmp_path)],
        )
        assert result.exit_code == 0
        # DDL path → schema_sql passed, not from_artifact.
        _, kwargs = mock_cls.return_value.provision_template.call_args
        assert kwargs.get("schema_sql") is not None
        assert kwargs.get("from_artifact") is None


class TestListAndPrune:
    @patch("confiture.cli.test_db.TestDbProvisioner")
    def test_list_json(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.list_databases.return_value = [
            ManagedDatabase("tmpl", "template", "h"),
            ManagedDatabase("c0", "clone", "tmpl"),
        ]
        result = runner.invoke(
            app, ["test-db", "list", "--database-url", _URL, "--format", "json"]
        )
        assert result.exit_code == 0
        assert '"name": "c0"' in result.stdout

    @patch("confiture.cli.test_db.TestDbProvisioner")
    def test_prune_json(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.prune.return_value = ["c0", "c1"]
        result = runner.invoke(
            app,
            ["test-db", "prune", "--template", "tmpl", "--database-url", _URL,
             "--format", "json"],
        )
        assert result.exit_code == 0
        mock_cls.return_value.prune.assert_called_once_with("tmpl")
        assert '"dropped": [' in result.stdout
