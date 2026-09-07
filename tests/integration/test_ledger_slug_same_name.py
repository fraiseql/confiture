"""Two migrations with the same name applied in one run are both recorded.

The ledger's ``slug`` was ``<name>_<timestamp to the second>``; two migrations
sharing a name and applied within the same second collided on ``slug UNIQUE``.
"""

from __future__ import annotations

from pathlib import Path

import psycopg
import pytest

from confiture.core.migrator import MigratorSession

V1, V2 = "20260906000009", "20260906000010"


@pytest.mark.integration
def test_same_name_twice_in_one_second(clean_test_db, test_db_url: str, tmp_path: Path) -> None:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    for version, table in ((V1, "alpha"), (V2, "beta")):
        (migrations / f"{version}_add_table.up.sql").write_text(f"CREATE TABLE {table} (id INT);\n")
        (migrations / f"{version}_add_table.down.sql").write_text(f"DROP TABLE {table};\n")

    with MigratorSession(None, migrations, database_url_override=test_db_url) as s:
        result = s.up()

    assert result.success is True, result.errors
    with psycopg.connect(test_db_url) as conn:
        rows = conn.execute("SELECT version, slug FROM tb_confiture ORDER BY version").fetchall()
    assert [r[0] for r in rows] == [V1, V2]
    assert len({r[1] for r in rows}) == 2
