"""Reachability + threading tests for `migrate schema-to-schema` (Phase 04, ARCH-N2).

The Medium-4 FDW feature was advertised in docs but had no CLI. These tests pin
that the subcommand group is reachable and threads to SchemaToSchemaMigrator,
without needing a database (the migrator is mocked via the `_migrator` factory).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()

_SUBCOMMANDS = ("setup", "analyze", "migrate", "migrate-table", "verify", "cleanup")


def test_group_help_lists_all_subcommands() -> None:
    result = runner.invoke(app, ["migrate", "schema-to-schema", "--help"])
    assert result.exit_code == 0, result.output
    for sub in _SUBCOMMANDS:
        assert sub in result.output


def test_each_subcommand_help_is_reachable() -> None:
    for sub in _SUBCOMMANDS:
        result = runner.invoke(app, ["migrate", "schema-to-schema", sub, "--help"])
        assert result.exit_code == 0, f"{sub} --help failed:\n{result.output}"


def test_setup_threads_to_core() -> None:
    mock_migrator = MagicMock()
    with patch(
        "confiture.cli.schema_to_schema._migrator", return_value=mock_migrator
    ) as factory:
        result = runner.invoke(
            app,
            ["migrate", "schema-to-schema", "setup", "--source", "old", "--target", "new"],
        )
    assert result.exit_code == 0, result.output
    factory.assert_called_once_with("old", "new")
    mock_migrator.setup_fdw.assert_called_once_with(skip_import=False)


def test_migrate_table_parses_inline_mapping() -> None:
    mock_migrator = MagicMock()
    mock_migrator.migrate_table.return_value = 42
    with patch("confiture.cli.schema_to_schema._migrator", return_value=mock_migrator):
        result = runner.invoke(
            app,
            [
                "migrate",
                "schema-to-schema",
                "migrate-table",
                "--source",
                "old",
                "--target",
                "new",
                "--source-table",
                "old_users",
                "--target-table",
                "users",
                "--mapping",
                "full_name:display_name,email:email",
            ],
        )
    assert result.exit_code == 0, result.output
    mock_migrator.migrate_table.assert_called_once_with(
        source_table="old_users",
        target_table="users",
        column_mapping={"full_name": "display_name", "email": "email"},
    )
    assert "42 rows migrated" in result.output


def test_verify_mismatch_exits_1() -> None:
    mock_migrator = MagicMock()
    mock_migrator.verify_migration.return_value = {
        "users": {"match": True, "source_count": 10, "target_count": 10},
        "posts": {"match": False, "source_count": 5, "target_count": 4},
    }
    with patch("confiture.cli.schema_to_schema._migrator", return_value=mock_migrator):
        result = runner.invoke(
            app,
            [
                "migrate",
                "schema-to-schema",
                "verify",
                "--source",
                "old",
                "--target",
                "new",
                "--tables",
                "users,posts",
            ],
        )
    # success-signal: a row-count mismatch is a found-issue gate
    assert result.exit_code == 1, result.output
    assert "posts" in result.output


def test_unresolvable_source_is_config_error(tmp_path, monkeypatch) -> None:
    # No db/environments and not a DSN → ConfigurationError (CONFIG_004 → exit 5).
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        app,
        ["migrate", "schema-to-schema", "cleanup", "--source", "nope", "--target", "nope"],
    )
    assert result.exit_code == 5, result.output
