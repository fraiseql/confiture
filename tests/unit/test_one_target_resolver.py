"""One answer to "environment name, config file or URL" (#750).

``sync --from/--to``, ``ProductionSyncer``, ``seed drift --against`` and
``migrate schema-to-schema --source/--target`` each name a database the same
way. They resolve it through :func:`confiture.core.connection.resolve_target`
and open it through ``open_connection``, so an environment's ``ssh_tunnel`` is
honoured by every one of them.
"""

import ast
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.connection import resolve_target
from confiture.core.syncer import ProductionSyncer
from confiture.exceptions import ConfigurationError

PACKAGE = Path(__file__).resolve().parents[2] / "python" / "confiture"

_TUNNELLED = """\
name: production
database_url: postgresql://app:secret@localhost:${TUNNEL_LOCAL_PORT}/app
include_dirs: [db/schema]
ssh_tunnel:
  host: bastion.example.com
  user: deploy
"""


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    envs = tmp_path / "db" / "environments"
    envs.mkdir(parents=True)
    (tmp_path / "db" / "schema").mkdir()
    (envs / "production.yaml").write_text(_TUNNELLED)
    monkeypatch.chdir(tmp_path)
    return tmp_path


class TestResolveTarget:
    def test_a_url_opens_as_given_and_is_named_masked(self):
        target = resolve_target("postgresql://u:pw@db/app", flag="--from")
        assert target.opens == "postgresql://u:pw@db/app"
        assert "pw" not in target.label
        assert target.environment is None

    def test_a_name_is_its_environment(self, project: Path):
        target = resolve_target("production", flag="--from")
        assert target.opens["ssh_tunnel"]["host"] == "bastion.example.com"
        assert (target.label, target.environment) == ("production", "production")

    def test_a_name_needs_no_schema_tree(self, project: Path):
        """A machine that only connects (a deploy host, a sync box) has no ``db/schema``."""
        (project / "db" / "schema").rmdir()
        target = resolve_target("production", flag="--from")
        assert target.environment == "production"

    def test_a_yaml_path_is_that_config_file(self, project: Path):
        path = project / "db" / "environments" / "production.yaml"
        target = resolve_target(str(path), flag="--source")
        assert target.opens["ssh_tunnel"]["host"] == "bastion.example.com"
        assert target.label == str(path)

    def test_a_missing_config_file_is_config_004(self, project: Path):
        with pytest.raises(ConfigurationError) as raised:
            resolve_target("nowhere.yaml", flag="--source")
        assert raised.value.error_code == "CONFIG_004"

    def test_a_missing_environment_is_config_001(self, project: Path):
        with pytest.raises(ConfigurationError) as raised:
            resolve_target("staging", flag="--to")
        assert raised.value.error_code == "CONFIG_001"

    def test_neither_is_config_003_and_is_not_echoed(self, project: Path):
        with pytest.raises(ConfigurationError) as raised:
            resolve_target("postgress://u:hunter2@db/app", flag="--to")
        assert raised.value.error_code == "CONFIG_003"
        assert "hunter2" not in str(raised.value)
        assert "--to" in str(raised.value)


@contextmanager
def _tunnel_opened(seen: list[Any]) -> Generator[None]:
    @contextmanager
    def fake_tunnel(config: Any, url: str) -> Generator[str]:
        seen.append(config.host)
        yield url.replace("${TUNNEL_LOCAL_PORT}", "15432")

    with (
        patch("confiture.core.connection._core_ssh_tunnel.ssh_tunnel", fake_tunnel),
        patch("confiture.core.connection.psycopg.connect", return_value=MagicMock()),
    ):
        yield


def test_the_syncer_opens_an_environment_through_its_tunnel(project: Path):
    seen: list[Any] = []
    with _tunnel_opened(seen), ProductionSyncer("production", "postgresql://localhost/t"):
        pass
    assert seen == ["bastion.example.com"]


def test_sync_from_an_environment_with_a_tunnel_opens_it(project: Path):
    seen: list[Any] = []
    with _tunnel_opened(seen), patch.object(ProductionSyncer, "sync", return_value={}):
        result = CliRunner().invoke(
            app, ["sync", "--from", "production", "--to", "postgresql://localhost/t"]
        )
    assert result.exit_code == 0, result.output
    assert seen == ["bastion.example.com"]


def _resolves_a_target(function: ast.FunctionDef) -> bool:
    """A URL-prefix test and an environment or config-file load in one function."""
    tests_prefix = loads = False
    for node in ast.walk(function):
        if not isinstance(node, ast.Call):
            continue
        callee = node.func
        if isinstance(callee, ast.Attribute) and callee.attr == "startswith":
            tests_prefix |= "postgres" in ast.unparse(node)
        name = callee.attr if isinstance(callee, ast.Attribute) else getattr(callee, "id", "")
        target = ast.unparse(callee)
        loads |= target == "Environment.load" or name == "load_config"
    return tests_prefix and loads


def test_no_second_target_resolver():
    """Only ``resolve_target`` turns a ``--from``-style value into what to open."""
    found = sorted(
        f"{path.relative_to(PACKAGE)}:{node.name}"
        for path in PACKAGE.rglob("*.py")
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.FunctionDef) and _resolves_a_target(node)
    )
    assert found == ["core/connection.py:resolve_target"]
