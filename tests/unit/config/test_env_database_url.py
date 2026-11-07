"""``${VAR}`` in an environment's connection URLs (#813).

The module docstring of ``config/environment.py`` promised ``database_url: ${DATABASE_URL}``,
but ``Environment.load`` expanded only ``acls``, ``ownership`` and ``function_coverage``, so
the URL validator saw the literal ``${…}`` and refused it. The raw-config path that every
``--config`` command reads (``dsn_from_config``) passed it to libpq unexpanded.

A URL is expanded when it is read, not when the file is: ``build`` and ``lint`` load an
environment without connecting, and need none of the variables its URLs name. An expanded
URL carries a password: no error may print the expansion.
"""

import textwrap
from pathlib import Path

import pytest

from confiture.config._env_vars import expand_env_vars
from confiture.config.environment import Environment
from confiture.core.connection import dsn_from_config, scratch_url_from_config
from confiture.exceptions import ConfigurationError

SECRET = "s3cret-Pw"


def _project(tmp_path: Path, body: str) -> Path:
    env_dir = tmp_path / "db" / "environments"
    env_dir.mkdir(parents=True)
    (env_dir / "test.yaml").write_text("include_dirs: []\n" + textwrap.dedent(body))
    return tmp_path


def test_database_url_is_expanded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"postgresql://app:{SECRET}@db/app")
    env = Environment.load("test", _project(tmp_path, "database_url: ${DATABASE_URL}\n"))
    assert env.database_url == f"postgresql://app:{SECRET}@db/app"


def test_a_reference_inside_the_url_is_expanded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DB_PASSWORD", SECRET)
    body = "database_url: postgresql://app:${DB_PASSWORD}@db/app\n"
    env = Environment.load("test", _project(tmp_path, body))
    assert env.database_url == f"postgresql://app:{SECRET}@db/app"


def test_scratch_url_is_expanded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCRATCH_URL", "postgresql://localhost/postgres")
    body = "database_url: postgresql://localhost/app\nscratch_url: ${SCRATCH_URL}\n"
    env = Environment.load("test", _project(tmp_path, body))
    assert env.scratch_url == "postgresql://localhost/postgres"


def test_an_unset_variable_is_named_never_emptied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    env = Environment.load("test", _project(tmp_path, "database_url: ${DATABASE_URL}\n"))
    with pytest.raises(ConfigurationError, match="DATABASE_URL") as excinfo:
        _ = env.database_url
    assert "database_url" in str(excinfo.value)


def test_loading_needs_no_variable_set(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The environment a build reads loads whether or not its password is in the environment."""
    monkeypatch.delenv("DB_PASSWORD", raising=False)
    body = "database_url: postgresql://app:${DB_PASSWORD}@db/app\nscratch_url: ${SCRATCH_URL}\n"
    env = Environment.load("test", _project(tmp_path, body))
    assert env.written_database_url == "postgresql://app:${DB_PASSWORD}@db/app"


def test_a_lowercase_reference_is_refused(tmp_path: Path) -> None:
    project = _project(tmp_path, "database_url: ${database_url}\n")
    with pytest.raises(ConfigurationError, match="DATABASE_URL"):
        Environment.load("test", project)


def test_the_tunnel_placeholder_is_left_for_the_tunnel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``${TUNNEL_LOCAL_PORT}`` is the port ``ssh_tunnel`` opens, not an environment variable."""
    monkeypatch.setenv("DB_PASSWORD", SECRET)
    monkeypatch.delenv("TUNNEL_LOCAL_PORT", raising=False)
    body = "database_url: postgresql://app:${DB_PASSWORD}@localhost:${TUNNEL_LOCAL_PORT}/app\n"
    env = Environment.load("test", _project(tmp_path, body))
    assert env.database_url == f"postgresql://app:{SECRET}@localhost:${{TUNNEL_LOCAL_PORT}}/app"


def test_a_malformed_expansion_never_prints_the_password(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``redact_url`` cannot mask a value with no scheme; the error quotes the file instead."""
    monkeypatch.setenv("DATABASE_URL", f"app:{SECRET}@db/app")
    env = Environment.load("test", _project(tmp_path, "database_url: ${DATABASE_URL}\n"))
    with pytest.raises(ConfigurationError) as excinfo:
        _ = env.database_url
    message = str(excinfo.value)
    assert SECRET not in message
    assert "${DATABASE_URL}" in message


def test_a_nested_reference_never_prints_the_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"postgresql://app:{SECRET}${{X}}@db/app")
    with pytest.raises(ConfigurationError, match="DATABASE_URL") as excinfo:
        expand_env_vars("${DATABASE_URL}", context="database_url")
    assert SECRET not in str(excinfo.value)


def test_a_url_with_no_reference_is_still_checked_at_load(tmp_path: Path) -> None:
    project = _project(tmp_path, "database_url: mysql://localhost/app\n")
    with pytest.raises(ConfigurationError, match="postgresql://"):
        Environment.load("test", project)


def test_the_model_reads_and_writes_the_keys_the_file_uses() -> None:
    """``database_url`` stays the key: a Python caller validates the same mapping."""
    env = Environment.model_validate({"database_url": "postgresql://localhost/app"})
    assert env.database_url == "postgresql://localhost/app"
    assert env.model_dump(by_alias=True)["database_url"] == "postgresql://localhost/app"


class TestTheRawConfigPath:
    """``--config <file>`` reads the YAML as a dict; its URL is derived in one place."""

    def test_database_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/app")
        assert dsn_from_config({"database_url": "${DATABASE_URL}"}) == "postgresql://localhost/app"

    def test_the_database_block(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PROD_DB_PASSWORD", SECRET)
        dsn = dsn_from_config({"database": {"host": "db", "password": "${PROD_DB_PASSWORD}"}})
        assert f"password={SECRET}" in dsn

    def test_scratch_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SCRATCH_URL", "postgresql://localhost/postgres")
        url = scratch_url_from_config({"scratch_url": "${SCRATCH_URL}"})
        assert url == "postgresql://localhost/postgres"

    def test_an_unset_variable_is_named(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        with pytest.raises(ConfigurationError, match="DATABASE_URL"):
            dsn_from_config({"database_url": "${DATABASE_URL}"})


def test_build_reads_an_environment_whose_url_is_a_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The issue's shape: ``build --env … --schema-only`` with only the variable set."""
    from typer.testing import CliRunner

    from confiture.cli.main import app

    (tmp_path / "db" / "schema").mkdir(parents=True)
    (tmp_path / "db" / "schema" / "t.sql").write_text("CREATE TABLE tb_probe (id bigint);\n")
    env_dir = tmp_path / "db" / "environments"
    env_dir.mkdir(parents=True)
    (env_dir / "ci.yaml").write_text("database_url: ${DATABASE_URL}\ninclude_dirs: [db/schema]\n")
    monkeypatch.setenv("DATABASE_URL", f"postgresql://app:{SECRET}@db/app")
    output = tmp_path / "schema.sql"

    result = CliRunner().invoke(
        app,
        [
            "build",
            "--env",
            "ci",
            "--project-dir",
            str(tmp_path),
            "--schema-only",
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "tb_probe" in output.read_text()
    assert SECRET not in result.output
