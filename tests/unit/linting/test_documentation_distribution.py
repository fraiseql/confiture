"""What the documentation counter cannot say, said beside it (#250).

`doc_001`–`doc_004` are satisfied by any `COMMENT`, so "documentation: 100 %"
reads the same whether a project wrote a paragraph per object or a hundred
one-line restatements of the signature — and the counter is what a project
drives to zero. The distribution is the difference: the same run reports how
many objects carry a comment, how many do not, and how long the comments are,
so a reader can see that the median function comment is nine characters.

It is reported *before* the findings, because the failure mode the issue
describes has no findings at all.
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

#: Five documented tables whose comments are 10, 20, 30, 40 and 50 characters,
#: so the nearest-rank percentiles are three different observed lengths.
_LENGTHS = (10, 20, 30, 40, 50)

_SCHEMA = (
    "".join(
        f"CREATE TABLE app.tb_{n} (id INT PRIMARY KEY);\n"
        f"COMMENT ON TABLE app.tb_{n} IS '{'x' * n}';\n"
        for n in _LENGTHS
    )
    + "CREATE TABLE app.tb_bare (id INT PRIMARY KEY);\n"
)


@pytest.fixture
def project(tmp_path: Path) -> Iterator[Path]:
    (tmp_path / "db" / "schema").mkdir(parents=True)
    (tmp_path / "db" / "environments").mkdir(parents=True)
    (tmp_path / "db" / "environments" / "local.yaml").write_text(
        "database_url: postgresql://localhost/test\ninclude_dirs:\n  - path: db/schema\n"
    )
    (tmp_path / "db" / "schema" / "010_objects.sql").write_text(
        "CREATE SCHEMA IF NOT EXISTS app;\n" + _SCHEMA
    )
    old_cwd = Path.cwd()
    os.chdir(tmp_path)
    try:
        yield tmp_path
    finally:
        os.chdir(old_cwd)


def _payload(*args: str) -> dict:
    result = runner.invoke(app, ["lint", "--format", "json", "--fail-on", "never", *args])
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


class TestJson:
    def test_the_payload_carries_the_documentation_block(self, project: Path) -> None:
        assert "documentation" in _payload()

    def test_the_counts_are_documented_and_undocumented_objects(self, project: Path) -> None:
        block = _payload()["documentation"]

        assert (block["documented"], block["undocumented"]) == (5, 1)

    def test_the_percentiles_are_observed_comment_lengths(self, project: Path) -> None:
        assert _payload()["documentation"]["comment_length"] == {"p10": 10, "p50": 30, "p90": 50}

    def test_every_doc_rule_has_a_row_even_with_nothing_to_report(self, project: Path) -> None:
        rules = _payload()["documentation"]["rules"]

        assert [r["code"] for r in rules] == ["doc_001", "doc_002", "doc_003", "doc_004"]

    def test_a_rule_with_no_objects_reports_zero_and_no_lengths(self, project: Path) -> None:
        views = next(r for r in _payload()["documentation"]["rules"] if r["code"] == "doc_003")

        assert (views["documented"], views["undocumented"], views["comment_length"]) == (0, 0, None)

    def test_the_block_is_absent_when_the_family_did_not_run(self, project: Path) -> None:
        assert "documentation" not in _payload("--ignore", "doc")


class TestTable:
    def test_the_summary_carries_one_line(self, project: Path) -> None:
        result = runner.invoke(app, ["lint", "--fail-on", "never"])

        assert (
            "doc: 5 documented, 1 undocumented, median comment 30 chars (p10 10, p90 50)"
            in result.output
        )

    def test_a_schema_with_no_findings_still_says_it(self, tmp_path: Path) -> None:
        """The failure mode #250 describes has no findings: a green counter and short comments."""
        _documented_project(tmp_path)
        old_cwd = Path.cwd()
        os.chdir(tmp_path)
        try:
            result = runner.invoke(app, ["lint", "--fail-on", "never"])
        finally:
            os.chdir(old_cwd)

        assert "No violations found" in result.output
        assert "doc: 1 documented, 0 undocumented, median comment 9 chars" in result.output


class TestWhatCountsAsDocumented:
    def test_a_comment_set_to_null_documents_nothing(self, project: Path) -> None:
        """``COMMENT ON … IS NULL`` *removes* the comment; it used to satisfy the rule."""
        (project / "db" / "schema" / "020_uncomment.sql").write_text(
            "COMMENT ON TABLE app.tb_10 IS NULL;\n"
        )

        payload = _payload()

        assert payload["documentation"]["documented"] == 4
        assert "app.tb_10" in [
            v["location"] for v in payload["violations"]["items"] if v["rule_id"] == "doc_001"
        ]

    def test_an_empty_comment_documents_nothing(self, project: Path) -> None:
        (project / "db" / "schema" / "020_blank.sql").write_text(
            "COMMENT ON TABLE app.tb_10 IS '   ';\n"
        )

        assert _payload()["documentation"]["documented"] == 4


def _documented_project(tmp_path: Path) -> None:
    (tmp_path / "db" / "schema").mkdir(parents=True)
    (tmp_path / "db" / "environments").mkdir(parents=True)
    (tmp_path / "db" / "environments" / "local.yaml").write_text(
        "database_url: postgresql://localhost/test\ninclude_dirs:\n  - path: db/schema\n"
    )
    (tmp_path / "db" / "schema" / "010.sql").write_text(
        "CREATE SCHEMA IF NOT EXISTS app;\n"
        "CREATE TABLE app.tb_widget (id INT PRIMARY KEY);\n"
        "COMMENT ON TABLE app.tb_widget IS 'A widget.';\n"
    )
