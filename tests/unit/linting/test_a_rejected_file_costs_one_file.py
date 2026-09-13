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

_BROKEN = "CREATE TABLE app.tb_broken (\n"

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
