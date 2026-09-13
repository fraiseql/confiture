"""A file PostgreSQL's parser rejects costs the lint that file, and nothing else (#274).

The COPY fix removes the common cause of a whole-build parse failure; a file that
is *genuinely* broken still empties the inventory, and the nine rules that read it
still examine zero objects. So the residual failure is made cheap and loud: the
broken file is blanked out of the parse text, the other files are inventoried as
usual, and the notice that says so names the file, at a severity the default gate
can fire on.

`degraded` carries the other half — which rules read a short inventory — because a
baseline can record a finding and a baseline never sees `degraded` (D6).
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

_GOOD = """CREATE SCHEMA app;
CREATE TABLE app.tb_widget (id uuid PRIMARY KEY, label text);
"""

_ALSO_GOOD = "CREATE TABLE app.tb_gadget (id uuid);\n"

# Valid on line 1, rejected on line 3: a notice that names line 1 would be
# indistinguishable from one that names "the start of the file".
_BROKEN = """CREATE TABLE app.tb_ok (id int);

CREATE TABEL app.tb_broken (id int);
"""

_ENV = "database_url: postgresql://localhost/test\ninclude_dirs:\n  - db/schema\n"


@pytest.fixture
def one_broken_file(tmp_path: Path) -> Iterator[Path]:
    """Three schema files, the last of which pglast rejects outright."""
    (tmp_path / "db" / "schema").mkdir(parents=True)
    (tmp_path / "db" / "environments").mkdir(parents=True)
    (tmp_path / "db" / "schema" / "010_widget.sql").write_text(_GOOD)
    (tmp_path / "db" / "schema" / "020_gadget.sql").write_text(_ALSO_GOOD)
    (tmp_path / "db" / "schema" / "030_broken.sql").write_text(_BROKEN)
    (tmp_path / "db" / "environments" / "local.yaml").write_text(_ENV)

    old_cwd = Path.cwd()
    os.chdir(tmp_path)
    try:
        yield tmp_path
    finally:
        os.chdir(old_cwd)


def _lint(*extra: str) -> tuple[dict, int]:
    result = runner.invoke(app, ["lint", "--env", "local", "--format", "json", *extra])
    return json.loads(result.stdout), result.exit_code


class TestTheRestOfTheBuildIsInventoried:
    def test_the_rest_of_the_build_is_inventoried(self, one_broken_file: Path) -> None:
        """Two readable files, two tables — not zero."""
        payload, _ = _lint("--fail-on", "never")

        assert payload["tables_checked"] == 2

    def test_the_readable_files_still_report(self, one_broken_file: Path) -> None:
        payload, _ = _lint("--fail-on", "never")
        located = {
            (i["rule_id"], i["location"])
            for i in payload["violations"]["items"]
            if i["rule_id"] != "UNPARSEABLE"
        }

        assert ("pk_001", "app.tb_gadget") in located
        assert ("doc_001", "app.tb_widget") in located

    def test_a_comment_still_resolves_across_files(self, tmp_path: Path) -> None:
        """The whole-build inventory exists so a COMMENT can name a CREATE elsewhere."""
        (tmp_path / "db" / "schema").mkdir(parents=True)
        (tmp_path / "db" / "environments").mkdir(parents=True)
        (tmp_path / "db" / "schema" / "010_widget.sql").write_text(_GOOD)
        (tmp_path / "db" / "schema" / "020_comment.sql").write_text(
            "COMMENT ON TABLE app.tb_widget IS 'the widgets';\n"
        )
        (tmp_path / "db" / "schema" / "030_broken.sql").write_text(_BROKEN)
        (tmp_path / "db" / "environments" / "local.yaml").write_text(_ENV)

        old_cwd = Path.cwd()
        os.chdir(tmp_path)
        try:
            payload, _ = _lint("--fail-on", "never")
        finally:
            os.chdir(old_cwd)

        assert payload["tables_checked"] == 1
        assert payload["documentation"]["documented"] == 1
        assert [i["rule_id"] for i in payload["violations"]["items"]] == ["UNPARSEABLE"]


class TestTheNoticeNamesTheFile:
    def test_the_notice_names_the_file(self, one_broken_file: Path) -> None:
        payload, _ = _lint("--fail-on", "never")
        notices = [i for i in payload["violations"]["items"] if i["rule_id"] == "UNPARSEABLE"]

        assert [(i["file"], i["line"]) for i in notices] == [("db/schema/030_broken.sql", 3)]

    def test_the_notice_is_an_error(self, one_broken_file: Path) -> None:
        """A file that was not read is not an `info` about the file that was."""
        payload, _ = _lint("--fail-on", "never")
        notices = [i for i in payload["violations"]["items"] if i["rule_id"] == "UNPARSEABLE"]

        assert [i["severity"] for i in notices] == ["error"]

    def test_the_default_gate_fires(self, one_broken_file: Path) -> None:
        """#274's ask: the default gate cannot pass over a build it did not read."""
        _, exit_code = _lint()

        assert exit_code == 1

    def test_one_notice_per_rejected_file(self, tmp_path: Path) -> None:
        """Several rules read the same file; the reader learns about the file once.

        `func_001` and `sec_002` open the schema files themselves, so before the
        dedup one broken file produced a notice from each of them *and* one from
        the build — three identical `error` findings about one fact.
        """
        (tmp_path / "db" / "schema").mkdir(parents=True)
        (tmp_path / "db" / "environments").mkdir(parents=True)
        (tmp_path / "db" / "schema" / "010_widget.sql").write_text(_GOOD)
        (tmp_path / "db" / "schema" / "030_broken.sql").write_text(_BROKEN)
        (tmp_path / "db" / "environments" / "local.yaml").write_text(
            _ENV + "function_coverage:\n  enabled: true\nsecurity_lint:\n  enabled: true\n"
        )

        old_cwd = Path.cwd()
        os.chdir(tmp_path)
        try:
            payload, _ = _lint("--fail-on", "never", "--select", "default,func_001,sec_002")
        finally:
            os.chdir(old_cwd)

        notices = [i for i in payload["violations"]["items"] if i["rule_id"] == "UNPARSEABLE"]
        assert [(i["file"], i["line"]) for i in notices] == [("db/schema/030_broken.sql", 3)]

    def test_a_whole_string_lint_reports_one_notice_with_no_file(self) -> None:
        """`lint(schema=...)` has no files, so the notice has no file to name."""
        from confiture.core.linting.schema_linter import RuleSeverity, SchemaLinter

        report = SchemaLinter(env="local").lint("CREATE TABEL broken (;")

        notices = [v for v in report.errors if v.rule_id == "UNPARSEABLE"]
        assert len(notices) == 1
        assert notices[0].file_path is None
        assert notices[0].severity is RuleSeverity.ERROR
