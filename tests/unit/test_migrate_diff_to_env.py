"""``migrate diff --to-env``: the desired state is what ``confiture build --env`` selects (#679).

A FraiseQL index fragment is composed into the environment's tree through
``include_dirs``, after the file that declares its table; the diff then reads
that tree in build order, ``order``, ``include`` and ``exclude`` honoured — never
a second walk of its own.
"""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.builder import SchemaBuilder
from confiture.core.desired_state import EnvSource

runner = CliRunner()

TV_PRODUCT = "CREATE TABLE tv_product (id INT NOT NULL, data JSONB NOT NULL);\n"
INDEX = "CREATE INDEX IF NOT EXISTS ix_tv_product_name ON tv_product ((data->>'name'));\n"
COMPOSED = """\
database_url: postgresql://localhost/unused
include_dirs:
  - db/schema
  - path: db/fraiseql/indexes
    order: 900
    auto_discover: false
"""


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    files = {
        "db/schema/10_tv_product.sql": TV_PRODUCT,
        "db/fraiseql/indexes/90_indexes.sql": INDEX,
        "db/environments/local.yaml": COMPOSED,
        "current.sql": TV_PRODUCT,
    }
    for name, text in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _diff(*args: str):
    return runner.invoke(app, ["migrate", "diff", *args, "--format", "json"])


def test_the_env_source_reads_the_build_s_selection_in_build_order(project: Path) -> None:
    files, _seeds = SchemaBuilder(env="local").categorize_sql_files()

    segments = EnvSource("local").segments()

    assert [segment.file for segment in segments] == files
    assert [segment.label for segment in segments] == [
        "db/schema/10_tv_product.sql",
        "db/fraiseql/indexes/90_indexes.sql",
    ]


def test_a_composed_fragment_is_one_concurrent_index(project: Path) -> None:
    result = _diff("--from", "current.sql", "--to-env", "local")

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert [change["type"] for change in payload["changes"]] == ["ADD_INDEX"]
    assert payload["warnings"] == []
    assert payload["source"] == {"kind": "env", "path": "local"}


def test_the_fragment_diffed_alone_is_refused(project: Path) -> None:
    result = _diff("--from", "current.sql", "--to", "db/fraiseql/indexes")

    assert result.exit_code == 5, result.output
    assert json.loads(result.stdout)["error"]["code"] == "DIFFER_406"


def test_an_excluded_file_is_not_read(project: Path) -> None:
    (project / "db/environments/local.yaml").write_text(
        COMPOSED.replace("  - db/schema\n", "  - path: db/schema\n    exclude: ['10_*']\n")
    )

    result = _diff("--from", "current.sql", "--to-env", "local")

    assert result.exit_code == 5, result.output
    assert json.loads(result.stdout)["error"]["code"] == "DIFFER_406"


def test_to_and_to_env_together_are_refused(project: Path) -> None:
    result = _diff("--from", "current.sql", "--to", "current.sql", "--to-env", "local")

    assert result.exit_code == 5, result.output


def test_a_missing_environment_is_named(project: Path) -> None:
    result = _diff("--from", "current.sql", "--to-env", "staging")

    assert result.exit_code != 0
    assert "staging" in result.output
