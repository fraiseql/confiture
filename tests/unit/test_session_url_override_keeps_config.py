"""A URL override replaces a session's connection, not its configuration (#825)."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from confiture.config.environment import Environment
from confiture.core._migrator.session import MigratorSession


def _env(tracking_table: str) -> Environment:
    return Environment.model_validate(
        {
            "name": "t",
            "database_url": "postgresql://localhost/nonexistent",
            "migration": {"tracking_table": tracking_table},
        }
    )


@pytest.mark.parametrize(
    ("config", "table_override", "expected"),
    [
        (_env("public.ledger"), None, "public.ledger"),
        (_env("public.ledger"), "ops.other", "ops.other"),
        (None, None, "tb_confiture"),
    ],
)
def test_the_session_reads_the_ledger_its_config_names(
    config: Environment | None, table_override: str | None, expected: str
) -> None:
    opened: list[str] = []

    def connect(url: str) -> MagicMock:
        opened.append(url)
        return MagicMock()

    session = MigratorSession(
        config,
        Path("db/migrations"),
        database_url_override="postgresql://localhost/test",
        migration_table_override=table_override,
        connection_factory=connect,
    )
    with session as s:
        assert s.migrator.migration_table == expected
    assert opened == ["postgresql://localhost/test"]
