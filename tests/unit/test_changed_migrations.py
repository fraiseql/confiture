"""Which changed paths are migrations: the runner's own listing rule, from the root (#709)."""

from pathlib import Path

import pytest

from confiture.core._migrator.discovery import changed_migrations, is_migration_name


@pytest.mark.parametrize(
    ("name", "is_one"),
    [
        ("20260101000000_add.up.sql", True),
        ("20260101000000_add.py", True),
        ("20260101000000_add.down.sql", False),
        ("20260101000000_add.sql", False),
        ("__init__.py", False),
        ("_helpers.py", False),
    ],
)
def test_a_migration_is_named_as_the_runner_lists_it(name: str, is_one: bool) -> None:
    assert is_migration_name(name) is is_one


def test_only_files_directly_in_the_directory_are_its_migrations() -> None:
    changed = [
        Path("services/api/db/migrations/1_a.up.sql"),
        Path("services/api/db/migrations/archive/2_b.up.sql"),
        Path("db/migrations/3_c.up.sql"),
        Path("services/api/db/schema/a.sql"),
    ]

    found = changed_migrations(changed, "services/api/db/migrations")

    assert found == [Path("services/api/db/migrations/1_a.up.sql")]
