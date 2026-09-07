"""One definition of "seed path".

The builder decides with a whole-token rule (``seed``/``seeds`` delimited by
``_``/``-``): ``30_seed_backend`` is a seed directory, ``reseed_tools`` is not.
The CLI's ``--schema-only`` filtered include dirs by the substring ``"seed"``
and counted files with an exact-component match — two other answers.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()


@pytest.fixture
def project(tmp_path: Path) -> Path:
    for rel, sql in {
        "db/schema/10_tables.sql": "CREATE TABLE t (id INT);\n",
        "db/reseed_tools/util.sql": "CREATE FUNCTION reseed() RETURNS void LANGUAGE sql AS 'SELECT 1';\n",
        "db/30_seed_backend/rows.sql": "INSERT INTO t VALUES (1);\n",
    }.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(sql)
    (tmp_path / "db" / "environments").mkdir()
    (tmp_path / "db" / "environments" / "local.yaml").write_text(
        "name: local\n"
        "database_url: postgresql://localhost/test\n"
        "include_dirs:\n  - db/schema\n  - db/reseed_tools\n  - db/30_seed_backend\n"
    )
    return tmp_path


def test_schema_only_uses_the_builders_seed_rule(project: Path) -> None:
    result = runner.invoke(
        app,
        [
            "build",
            "--env",
            "local",
            "--project-dir",
            str(project),
            "--schema-only",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    # schema + reseed_tools kept, 30_seed_backend excluded
    assert payload["files_processed"] == 2, payload
    generated = (project / "db" / "generated" / "schema_local.sql").read_text()
    assert "reseed()" in generated
    assert "INSERT INTO t" not in generated
