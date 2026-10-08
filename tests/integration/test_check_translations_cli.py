"""``confiture check translations``: the coverage count, its output and its exit codes (#657)."""

import json
from pathlib import Path
from urllib.parse import urlparse

import psycopg
import pytest
from tests.integration.test_translation_coverage import DATA, DDL
from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()

PROJECT = (
    "soft_delete: {}\n"
    "translations:\n  tables: 'tl_*'\n  locale_table: tb_locale\n  required: [en-US, fr-FR]\n"
)


@pytest.fixture
def project(clean_test_db: psycopg.Connection, test_db_url: str, tmp_path: Path) -> Path:
    with clean_test_db.cursor() as cur:
        cur.execute(DDL)
        cur.execute(DATA)
    clean_test_db.commit()
    (tmp_path / "db" / "schema").mkdir(parents=True)
    (tmp_path / "db" / "schema" / "010_i18n.sql").write_text(DDL)
    (tmp_path / "db" / "environments").mkdir()
    (tmp_path / "db" / "environments" / "local.yaml").write_text(
        f"name: local\ndatabase_url: {test_db_url}\ninclude_dirs:\n  - db/schema\n"
    )
    (tmp_path / "db" / "project.yaml").write_text(PROJECT)
    return tmp_path


def _run(project: Path, *args: str):
    return runner.invoke(app, ["check", "translations", "--project-dir", str(project), *args])


def test_the_text_report_is_one_line_per_table(project: Path) -> None:
    result = _run(project)

    assert result.exit_code == 0, result.output
    assert "tl_category: en-US 0 missing, fr-FR 3 missing (e.g. 3, 4, 5)" in result.output


def test_fail_on_missing_exits_findings(project: Path) -> None:
    assert _run(project, "--fail-on", "missing").exit_code == 1


def test_the_json_report(project: Path) -> None:
    result = _run(project, "--format", "json", "--sample", "2")

    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["command"] == "check translations"
    assert payload["missing"] == 3
    assert payload["tables"] == [
        {
            "table": "tl_category",
            "locales": [
                {"locale": "en-US", "missing": 0, "sample": []},
                {"locale": "fr-FR", "missing": 3, "sample": ["3", "4"]},
            ],
        }
    ]


def test_a_covered_locale_set_passes_the_gate(project: Path) -> None:
    (project / "db" / "project.yaml").write_text(PROJECT.replace("[en-US, fr-FR]", "[en-US]"))
    assert _run(project, "--fail-on", "missing").exit_code == 0


def test_no_translations_block_is_not_run(project: Path) -> None:
    (project / "db" / "project.yaml").write_text("soft_delete: {}\n")
    result = _run(project)
    assert result.exit_code == 2
    assert "No translations: block" in result.output


def test_an_unknown_fail_on_is_a_usage_error(project: Path) -> None:
    assert _run(project, "--fail-on", "always").exit_code == 2


def test_an_unreachable_database_exits_three(project: Path, test_db_url: str) -> None:
    unreachable = urlparse(test_db_url)._replace(netloc="localhost:1").geturl()
    result = _run(project, "--database-url", unreachable)
    assert result.exit_code == 3, result.output
