"""``--check-acls`` and ``--check-ownership-coverage`` read the project ``migrate up`` runs (#715).

The grant sweep is found where the git checks find it — relative to the directory
the command runs in, as ``--migrations-dir`` is — not beside the config file, which
``confiture init`` puts in ``db/environments/``. A sweep directory that does not
exist is said so, never dropped in silence. The migrations directory is listed
flat, as the runner lists it: a file nested below it is never applied, so it is
never linted.
"""

import json
import textwrap
from pathlib import Path

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app

_ACLS = """\
    acls:
      - schema: public
        apply_to: ALL_TABLES
        grants:
          - role: my_app
            privileges: [SELECT]
    """

_SWEEP = "migration:\n  grant_dir: db/grants\n"

_OWNERSHIP = """\
    ownership:
      expected_owner: migrator
      apply_to:
        - schema: public
          relkinds: [r]
    """


def _project(root: Path, *blocks: str, migration: dict[str, str]) -> None:
    """The layout ``confiture init`` writes: the config in ``db/environments/``."""
    (root / "db" / "environments").mkdir(parents=True)
    (root / "db" / "environments" / "local.yaml").write_text(
        "name: local\n"
        "database_url: postgresql://localhost/nonexistent\n"
        "include_dirs: []\n" + "".join(textwrap.dedent(block) for block in blocks)
    )
    for name, body in migration.items():
        path = root / "db" / "migrations" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)


def _validate(flag: str, *extra: str):
    return CliRunner().invoke(
        app,
        [
            "migrate",
            "validate",
            flag,
            "--config",
            "db/environments/local.yaml",
            "--migrations-dir",
            "db/migrations",
            *extra,
        ],
    )


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_the_default_grant_sweep_is_read_from_the_project(project: Path) -> None:
    _project(project, _ACLS, migration={"001_foo.up.sql": "CREATE TABLE foo (id int);\n"})
    (project / "db" / "7_grant").mkdir()
    (project / "db" / "7_grant" / "foo.sql").write_text("GRANT SELECT ON foo TO my_app;\n")

    result = _validate("--check-acls")

    assert result.exit_code == 0, result.output


def test_a_missing_grant_sweep_is_said(project: Path) -> None:
    _project(
        project,
        _ACLS,
        _SWEEP,
        migration={"001_foo.up.sql": "CREATE TABLE foo (id int);\n"},
    )

    result = _validate("--check-acls")

    assert result.exit_code == 1, result.output
    assert "db/grants" in result.output
    assert "does not exist" in result.output


def test_a_missing_grant_sweep_is_in_the_json(project: Path) -> None:
    _project(
        project,
        _ACLS,
        _SWEEP,
        migration={
            "001_foo.up.sql": "CREATE TABLE foo (id int);\nGRANT SELECT ON foo TO my_app;\n"
        },
    )

    result = _validate("--check-acls", "--format", "json")

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert [d["code"] for d in payload["degraded"]] == ["acl_001"]
    assert "db/grants" in payload["degraded"][0]["reason"]


def test_a_present_grant_sweep_degrades_nothing(project: Path) -> None:
    _project(project, _ACLS, migration={"001_foo.up.sql": "CREATE TABLE foo (id int);\n"})
    (project / "db" / "7_grant").mkdir()
    (project / "db" / "7_grant" / "foo.sql").write_text("GRANT SELECT ON foo TO my_app;\n")

    result = _validate("--check-acls", "--format", "json")

    assert json.loads(result.output)["degraded"] == []


def test_acl_001_does_not_lint_a_nested_file(project: Path) -> None:
    _project(
        project,
        _ACLS,
        migration={"archive/002_bar.up.sql": "CREATE TABLE bar (id int);\n"},
    )

    result = _validate("--check-acls")

    assert result.exit_code == 0, result.output


def test_own_001_does_not_lint_a_nested_file(project: Path) -> None:
    _project(
        project,
        _OWNERSHIP,
        migration={"archive/002_bar.up.sql": "CREATE TABLE public.bar (id int);\n"},
    )

    result = _validate("--check-ownership-coverage")

    assert result.exit_code == 0, result.output
    assert "own_001" not in result.output


def test_own_002_does_not_lint_a_nested_file(project: Path) -> None:
    _project(
        project,
        _OWNERSHIP,
        migration={"archive/002_bar.up.sql": "ALTER TABLE public.bar OWNER TO migrator;\n"},
    )

    result = _validate("--check-ownership-coverage")

    assert "own_002" not in result.output


def test_a_flat_migration_is_still_linted(project: Path) -> None:
    _project(
        project,
        _OWNERSHIP,
        migration={"001_bar.up.sql": "CREATE TABLE public.bar (id int);\n"},
    )

    result = _validate("--check-ownership-coverage")

    assert result.exit_code == 1, result.output
    assert "own_001" in result.output


def test_a_config_outside_db_environments_reads_no_other_environment(project: Path) -> None:
    """``--config`` names the config; the check never loads ``db/environments/local.yaml``."""
    (project / "confiture.yaml").write_text(
        "name: test\n"
        "database_url: postgresql://localhost/nonexistent\n"
        "include_dirs: []\n" + textwrap.dedent(_ACLS)
    )
    (project / "db" / "migrations").mkdir(parents=True)
    (project / "db" / "migrations" / "001_foo.up.sql").write_text(
        "CREATE TABLE foo (id int);\nGRANT SELECT ON foo TO my_app;\n"
    )

    result = CliRunner().invoke(
        app,
        [
            "migrate",
            "validate",
            "--check-acls",
            "--config",
            "confiture.yaml",
            "--migrations-dir",
            "db/migrations",
        ],
    )

    assert result.exit_code == 0, result.output
