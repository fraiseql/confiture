"""``build`` validates its flags before any database or seed work."""

from __future__ import annotations

from pathlib import Path

import psycopg
import pytest
from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()


def _table_count(url: str) -> int:
    with psycopg.connect(url) as conn:
        return conn.execute(
            "SELECT count(*) FROM pg_tables WHERE schemaname = 'public'"
        ).fetchone()[0]


@pytest.mark.integration
def test_bad_format_with_sequential_touches_nothing(
    clean_test_db, test_db_url: str, tmp_path: Path
) -> None:
    (tmp_path / "db" / "schema").mkdir(parents=True)
    (tmp_path / "db" / "schema" / "10_t.sql").write_text("CREATE TABLE t (id INT);\n")
    (tmp_path / "db" / "seeds").mkdir()
    (tmp_path / "db" / "seeds" / "rows.sql").write_text("INSERT INTO t VALUES (1);\n")
    (tmp_path / "db" / "environments").mkdir()
    (tmp_path / "db" / "environments" / "local.yaml").write_text(
        f"name: local\ndatabase_url: {test_db_url}\ninclude_dirs:\n  - db/schema\n  - db/seeds\n"
    )
    before = _table_count(test_db_url)

    result = runner.invoke(
        app,
        [
            "build",
            "--env",
            "local",
            "--project-dir",
            str(tmp_path),
            "--sequential",
            "--format",
            "xml",
        ],
    )

    assert result.exit_code == 5, result.output
    assert result.stdout == ""
    assert _table_count(test_db_url) == before
