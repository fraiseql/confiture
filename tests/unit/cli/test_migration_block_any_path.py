"""The ``migration:`` block of the file ``--config`` names applies wherever it lives (#832).

Every migrate command read it only when the file sat at ``db/environments/<name>.yaml``;
anywhere else it silently meant the defaults, while ``tracking_table`` was read from the
same block. One reader now parses and validates it for every command, and refuses a key
the block does not have.
"""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from tests.unit._doubles import session_double
from typer.testing import CliRunner

from confiture.cli.commands.migrate._settings import migration_settings
from confiture.cli.main import app
from confiture.config.environment import Environment, MigrationConfig, migration_block
from confiture.exceptions import ConfigurationError
from confiture.models.results import MigrateDownResult, MigrateUpResult

runner = CliRunner()

_FLAT = """\
database_url: postgresql://localhost/test
apply_as:
  postgres:
    url: postgresql://localhost/test
migration:
  tracking_table: public.ledger_832
  strict_mode: true
  view_helpers: auto
  locking:
    timeout_ms: 1234
    extra_keys: [42]
  backfill:
    batch_size: 77
  rebuild_threshold: 2
  destructive: forbid
  snapshot_history: false
  migration_generators:
    g:
      command: "echo {from} {to} > {output}"
"""


@pytest.fixture
def flat(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A project whose config is ``c.yaml`` at its root, not under ``db/environments/``."""
    migrations = tmp_path / "db" / "migrations"
    migrations.mkdir(parents=True)
    for i in (1, 2, 3):
        (migrations / f"2026010112000{i}_m{i}.up.sql").write_text(f"CREATE TABLE t{i} (id INT);\n")
        (migrations / f"2026010112000{i}_m{i}.down.sql").write_text(f"DROP TABLE t{i};\n")
    (tmp_path / "c.yaml").write_text(_FLAT)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("CONFITURE_DATABASE_URL", raising=False)
    return tmp_path


# --- the one reader ---------------------------------------------------------


def test_the_block_is_read_from_a_file_outside_db_environments(flat: Path) -> None:
    settings = migration_settings(Path("c.yaml"))
    assert settings is not None
    assert settings.migration.strict_mode is True
    assert settings.migration.view_helpers == "auto"
    assert settings.migration.locking.extra_keys == [42]


def test_a_missing_file_means_defaults(flat: Path) -> None:
    assert migration_settings(Path("absent.yaml")) is None


@pytest.mark.parametrize(
    ("block", "named"),
    [
        ({"strict_mode": "not-a-bool"}, "strict_mode"),
        ({"strict_mod": True}, "strict_mod"),
        ({"locking": {"timeout": 5}}, "timeout"),
        ("strict", "migration"),
    ],
    ids=["bad-value", "unknown-key", "unknown-nested-key", "not-a-mapping"],
)
def test_a_malformed_block_is_config_002(block: Any, named: str) -> None:
    with pytest.raises(ConfigurationError) as info:
        migration_block({"migration": block}, Path("c.yaml"))
    assert info.value.error_code == "CONFIG_002"
    assert named in str(info.value)
    assert "c.yaml" in str(info.value)


def test_an_absent_or_empty_block_is_the_defaults() -> None:
    assert migration_block({}, Path("c.yaml")) == MigrationConfig()
    assert migration_block({"migration": None}, Path("c.yaml")) == MigrationConfig()


def test_an_environment_carries_its_block_already() -> None:
    env = Environment.model_validate(
        {"database_url": "postgresql://localhost/test", "migration": {"strict_mode": True}}
    )
    assert migration_block(env, Path("c.yaml")).strict_mode is True


def test_a_malformed_flat_block_fails_migrate_up(flat: Path) -> None:
    (flat / "c.yaml").write_text(
        "database_url: postgresql://localhost/test\nmigration:\n  strict_mod: true\n"
    )
    with patch("confiture.core.migrator.MigratorSession", autospec=True) as cls:
        result = runner.invoke(app, ["migrate", "up", "-c", "c.yaml"])
    assert result.exit_code == 5, result.output
    assert "strict_mod" in result.output
    cls.assert_not_called()


# --- every caller -----------------------------------------------------------


def _session(**returns: Any) -> MagicMock:
    session = session_double(**returns)
    session.__enter__.return_value = session
    return session


def test_migrate_up_applies_a_flat_block(flat: Path) -> None:
    session = _session(up=MigrateUpResult(success=True, migrations_applied=[], total_duration_ms=0))
    with patch(
        "confiture.core.migrator.MigratorSession", autospec=True, return_value=session
    ) as cls:
        result = runner.invoke(app, ["migrate", "up", "-c", "c.yaml"])
    assert result.exit_code == 0, result.output
    assert cls.call_args.kwargs["extra_lock_keys"] == (42,)
    assert cls.call_args.kwargs["migration_table_override"] == "public.ledger_832"
    options = session.up.call_args.kwargs
    assert options["strict_mode"] is True
    assert options["install_view_helpers"] is True
    assert options["lock_timeout"] == 1234
    assert options["backfill"].batch_size == 77


def test_migrate_down_applies_a_flat_block(flat: Path) -> None:
    session = _session(
        down=MigrateDownResult(success=True, migrations_rolled_back=[], total_duration_ms=0)
    )
    with patch(
        "confiture.core.migrator.MigratorSession", autospec=True, return_value=session
    ) as cls:
        runner.invoke(app, ["migrate", "down", "-c", "c.yaml"])
    assert cls.call_args.kwargs["extra_lock_keys"] == (42,)


def test_migrate_down_to_hands_the_session_the_flat_environment(flat: Path) -> None:
    session = _session()
    with patch(
        "confiture.core.migrator.MigratorSession", autospec=True, return_value=session
    ) as cls:
        runner.invoke(app, ["migrate", "down-to", "20260101120001", "-c", "c.yaml"])
    assert cls.call_args.args[0].migration.locking.extra_keys == [42]


def test_squash_ledger_applies_a_flat_block(flat: Path) -> None:
    session = _session()
    with patch(
        "confiture.core.migrator.MigratorSession", autospec=True, return_value=session
    ) as cls:
        runner.invoke(app, ["migrate", "squash-ledger", "-c", "c.yaml"])
    assert cls.call_args.kwargs["extra_lock_keys"] == (42,)


def test_apply_as_applies_a_flat_block(flat: Path) -> None:
    session = _session()
    with patch(
        "confiture.core.migrator.MigratorSession", autospec=True, return_value=session
    ) as cls:
        runner.invoke(
            app,
            [
                "migrate",
                "apply-as",
                "postgres",
                "20260101120001",
                "-c",
                "c.yaml",
                "--migrations-dir",
                "db/migrations",
            ],
        )
    assert cls.call_args.kwargs["extra_lock_keys"] == (42,)


def test_generate_finds_a_generator_in_a_flat_block(flat: Path) -> None:
    (flat / "a.sql").write_text("CREATE TABLE a (id INT);\n")
    (flat / "b.sql").write_text("CREATE TABLE b (id INT);\n")
    result = runner.invoke(
        app,
        [
            "migrate",
            "generate",
            "add_b",
            "--generator",
            "g",
            "--from",
            "a.sql",
            "--to",
            "b.sql",
            "--dry-run",
            "-c",
            "c.yaml",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "not found in migration_generators" not in result.output


def test_status_reads_the_threshold_of_a_flat_block(flat: Path) -> None:
    from confiture.cli.commands.migrate._settings import _effective_rebuild_threshold

    assert _effective_rebuild_threshold(None, Path("c.yaml")) == 2


def test_diff_reads_the_destructive_policy_of_a_flat_block(flat: Path) -> None:
    from confiture.cli.commands.migrate.diff import _destructive_policy

    policy = _destructive_policy(
        Path("c.yaml"), allow=False, forbid=False, json_mode=False, report=None
    )
    assert policy == "forbid"
