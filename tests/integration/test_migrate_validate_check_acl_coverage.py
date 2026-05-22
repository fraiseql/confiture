"""Integration tests for ``confiture migrate validate --check-acls`` (issue #120).

Wires the ACL coverage lint rule into the ``migrate validate`` command
so a CI gate can refuse PRs that ship uncovered tables.  ``--check-acls``
is the canonical flag from 0.12.0 onward; ``--check-acl-coverage`` is
kept as a deprecated alias and covered by one dedicated test.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from typer.testing import CliRunner

from confiture.cli.main import app


def _project_with_migrations(
    tmp_path: Path, migrations: dict[str, str], grant_files: dict[str, str] | None = None
) -> tuple[Path, Path]:
    """Lay out a minimal project tree.

    Returns ``(config_path, migrations_dir)``.
    """
    project = tmp_path
    (project / "db" / "migrations").mkdir(parents=True)
    for name, body in migrations.items():
        (project / "db" / "migrations" / name).write_text(body)
    if grant_files:
        (project / "db" / "7_grant").mkdir(parents=True)
        for name, body in grant_files.items():
            (project / "db" / "7_grant" / name).write_text(body)

    cfg = project / "confiture.yaml"
    cfg.write_text(
        textwrap.dedent(
            """\
            name: test
            database_url: postgresql://localhost/test
            include_dirs: []
            acls:
              - schema: public
                apply_to: ALL_TABLES
                grants:
                  - role: my_app
                    privileges: [SELECT, INSERT]
            """
        )
    )
    return cfg, project / "db" / "migrations"


def test_validate_check_acl_coverage_exits_1_on_uncovered_table(tmp_path: Path) -> None:
    cfg, migrations_dir = _project_with_migrations(
        tmp_path,
        {"20260522120000_add_foo.up.sql": "CREATE TABLE foo (id int);"},
    )
    result = CliRunner().invoke(
        app,
        [
            "migrate",
            "validate",
            "--check-acls",
            "--config",
            str(cfg),
            "--migrations-dir",
            str(migrations_dir),
        ],
    )
    assert result.exit_code == 1, result.output
    assert "acl_001" in result.output.lower()


def test_validate_check_acl_coverage_passes_when_covered_inline(tmp_path: Path) -> None:
    cfg, migrations_dir = _project_with_migrations(
        tmp_path,
        {
            "20260522120000_add_foo.up.sql": (
                "CREATE TABLE foo (id int);\nGRANT SELECT, INSERT ON foo TO my_app;\n"
            )
        },
    )
    result = CliRunner().invoke(
        app,
        [
            "migrate",
            "validate",
            "--check-acls",
            "--config",
            str(cfg),
            "--migrations-dir",
            str(migrations_dir),
        ],
    )
    assert result.exit_code == 0, result.output


def test_validate_check_acl_coverage_passes_with_global_grant_sweep(tmp_path: Path) -> None:
    cfg, migrations_dir = _project_with_migrations(
        tmp_path,
        {"20260522120000_add_foo.up.sql": "CREATE TABLE foo (id int);"},
        {"grants.sql": "GRANT SELECT, INSERT ON foo TO my_app;\n"},
    )
    result = CliRunner().invoke(
        app,
        [
            "migrate",
            "validate",
            "--check-acls",
            "--config",
            str(cfg),
            "--migrations-dir",
            str(migrations_dir),
        ],
    )
    assert result.exit_code == 0, result.output


def test_validate_check_acl_coverage_no_op_when_acls_absent(tmp_path: Path) -> None:
    """Without an `acls:` block, the flag is a no-op (exit 0)."""
    project = tmp_path
    (project / "db" / "migrations").mkdir(parents=True)
    (project / "db" / "migrations" / "20260522120000.up.sql").write_text(
        "CREATE TABLE foo (id int);"
    )
    cfg = project / "confiture.yaml"
    cfg.write_text(
        textwrap.dedent(
            """\
            name: test
            database_url: postgresql://localhost/test
            include_dirs: []
            """
        )
    )
    result = CliRunner().invoke(
        app,
        [
            "migrate",
            "validate",
            "--check-acls",
            "--config",
            str(cfg),
            "--migrations-dir",
            str(project / "db" / "migrations"),
        ],
    )
    assert result.exit_code == 0, result.output


def test_validate_check_acl_coverage_deprecated_alias_still_works(tmp_path: Path) -> None:
    """``--check-acl-coverage`` keeps working as a back-compat alias (0.12.0)."""
    cfg, migrations = _project_with_migrations(
        tmp_path,
        {"20260522120000_add_uncovered.up.sql": ("CREATE TABLE uncovered (id int);\n")},
    )
    result = CliRunner().invoke(
        app,
        [
            "migrate",
            "validate",
            "--check-acl-coverage",
            "--config",
            str(cfg),
            "--migrations-dir",
            str(migrations),
        ],
    )
    # Same behavior as ``--check-acls``: exits 1 because ``uncovered`` has no GRANT.
    assert result.exit_code == 1, result.output
