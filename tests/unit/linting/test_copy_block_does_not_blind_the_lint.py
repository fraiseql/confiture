"""A seed file in the build costs the lint nothing (#274).

`SchemaLinter.lint()` parsed the whole concatenated build in one call, so one
`COPY … FROM stdin` block anywhere in it emptied the inventory — and the nine
rules that read the inventory (`naming_001`, `naming_002`, `pk_001`,
`doc_001`–`doc_005`, `sec_001`) then examined zero objects, `tables_checked`
reported 0, and the only trace was an `info` notice below every gate threshold.
The rules that read per file kept reporting, so the run looked alive.

The reporter's two environments are the test: the same tree, the second adding
`./db/seed` to `include_dirs`. They must agree on everything.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()

_SCHEMA = """CREATE SCHEMA app;
CREATE TABLE app.tb_widget (id uuid PRIMARY KEY, label text);
CREATE FUNCTION app.fn_widget_count() RETURNS bigint AS $$ SELECT count(*) FROM app.tb_widget $$ LANGUAGE sql;
"""

_SEED = (
    "COPY app.tb_widget (id, label) FROM stdin;\n0b6f1c2e-1111-4a4a-8888-000000000001\tfirst\n\\.\n"
)

_ENV = "database_url: postgresql://localhost/test\ninclude_dirs:\n"


@pytest.fixture
def two_environments(tmp_path: Path) -> Iterator[Path]:
    """One tree, two environments: schema only, and schema plus a seed file."""
    (tmp_path / "db" / "schema").mkdir(parents=True)
    (tmp_path / "db" / "seed").mkdir(parents=True)
    (tmp_path / "db" / "environments").mkdir(parents=True)
    (tmp_path / "db" / "schema" / "01_widget.sql").write_text(_SCHEMA)
    (tmp_path / "db" / "seed" / "01_widget_seed.sql").write_text(_SEED)
    (tmp_path / "db" / "environments" / "schema_only.yaml").write_text(_ENV + "  - db/schema\n")
    (tmp_path / "db" / "environments" / "with_seed.yaml").write_text(
        _ENV + "  - db/schema\n  - db/seed\n"
    )

    old_cwd = Path.cwd()
    os.chdir(tmp_path)
    try:
        yield tmp_path
    finally:
        os.chdir(old_cwd)


def _lint(env: str, *extra: str) -> dict:
    result = runner.invoke(
        app, ["lint", "--env", env, "--fail-on", "never", "--format", "json", *extra]
    )
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


def _findings(payload: dict) -> list[tuple]:
    return sorted(
        (i["rule_id"], i["location"], i["file"], i["line"]) for i in payload["violations"]["items"]
    )


class TestTheSeedFileCostsNothing:
    def test_both_environments_check_the_same_tables(self, two_environments: Path) -> None:
        schema_only, with_seed = _lint("schema_only"), _lint("with_seed")

        assert (with_seed["tables_checked"], with_seed["columns_checked"]) == (
            schema_only["tables_checked"],
            schema_only["columns_checked"],
        )
        assert with_seed["tables_checked"] == 1

    def test_both_environments_report_the_same_documentation(self, two_environments: Path) -> None:
        schema_only, with_seed = _lint("schema_only"), _lint("with_seed")

        assert with_seed["documentation"] == schema_only["documentation"]
        assert with_seed["documentation"]["undocumented"] == 2

    def test_both_environments_report_the_same_findings(self, two_environments: Path) -> None:
        schema_only, with_seed = _lint("schema_only"), _lint("with_seed")

        assert _findings(with_seed) == _findings(schema_only)

    def test_no_unparseable_notice_for_copy_data(self, two_environments: Path) -> None:
        """COPY rows are the one unparseable text that is not a finding about the schema."""
        codes = [i["rule_id"] for i in _lint("with_seed")["violations"]["items"]]

        assert "UNPARSEABLE" not in codes

    def test_the_findings_name_the_schema_file(self, two_environments: Path) -> None:
        located = {
            (i["rule_id"], i["file"], i["line"]) for i in _lint("with_seed")["violations"]["items"]
        }

        assert located == {
            ("doc_001", "db/schema/01_widget.sql", 2),
            ("doc_002", "db/schema/01_widget.sql", 3),
        }


class TestTheParseTextIsNotTheBuild:
    """Two strings, because two consumers want different things (D4).

    `bodies.diagnose()` materialises the build into a throwaway database through
    the COPY-aware psql applier, and `tenant_001` scans it as text. Blanking the
    string *they* read would silently drop the seed rows from a database the
    `body` family then asks questions about.
    """

    def test_the_build_keeps_its_copy_rows(self, two_environments: Path) -> None:
        from confiture.core.linting.schema_linter import SchemaLinter

        linter = SchemaLinter(env="with_seed")
        linter.lint()

        assert "0b6f1c2e-1111-4a4a-8888-000000000001" in (linter._schema_sql or "")

    def test_the_parse_text_does_not(self, two_environments: Path) -> None:
        from confiture.core.linting.schema_linter import SchemaLinter

        linter = SchemaLinter(env="with_seed")
        linter.lint()

        assert "0b6f1c2e-1111-4a4a-8888-000000000001" not in linter._parse_sql
        assert "CREATE TABLE app.tb_widget" in linter._parse_sql
