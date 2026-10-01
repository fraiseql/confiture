"""``migrate diff`` refuses a schema whose names need quotes (#487).

confiture supports a name only as PostgreSQL writes it bare (#484). The lint
reports every other name (``naming_003``, ``naming_004``), but generation does
not run the lint, so the differ refuses too: on either side, before any SQL is
written. A crafted name (``"v; DROP TABLE victim; --"``) never reaches a
generated statement.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.exceptions import ConfiturError
from confiture.platform import diff

_PLAIN = "CREATE SCHEMA app;\nCREATE TABLE app.t (id int PRIMARY KEY);\n"


@pytest.mark.parametrize(
    ("statement", "spelled"),
    [
        ('CREATE TABLE app."Order Line" (id int);', 'app."Order Line"'),
        ('CREATE TABLE app.u (id int, "user" int);', 'app.u."user"'),
        ('CREATE VIEW "v; DROP TABLE victim; --" AS SELECT 1 AS a;', '"v; DROP TABLE victim; --"'),
        ("CREATE TYPE app.\"Status\" AS ENUM ('a');", 'app."Status"'),
        ('CREATE INDEX "Idx" ON app.t (id);', 'app."Idx"'),
        ('ALTER TABLE app.t ADD CONSTRAINT "Pos" CHECK (id > 0);', 'app.t."Pos"'),
        (
            'CREATE FUNCTION app."Fn"() RETURNS int LANGUAGE sql AS $$ SELECT 1 $$;',
            'app."Fn"',
        ),
        (
            "CREATE FUNCTION app.f() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NEW; END $$;\n"
            'CREATE TRIGGER "Trg" BEFORE INSERT ON app.t FOR EACH ROW EXECUTE FUNCTION app.f();',
            '"Trg"',
        ),
        (
            "SELECT tviews.pg_tviews_create_or_replace('app.\"tv_Q\"', 'SELECT id FROM app.t');",
            'app."tv_Q"',
        ),
        ("SELECT pg_tviews_create('app.\"Q\"', 'SELECT id FROM app.t');", 'app."tv_Q"'),
    ],
)
@pytest.mark.parametrize("side", ["old", "new"])
def test_a_name_that_needs_quotes_is_refused(statement: str, spelled: str, side: str) -> None:
    quoted = f"{_PLAIN}{statement}\n"
    old, new = (quoted, _PLAIN) if side == "old" else (_PLAIN, quoted)

    with pytest.raises(ConfiturError) as caught:
        diff(old, new)

    assert caught.value.error_code == "DIFFER_403"
    assert spelled in str(caught.value)
    assert side in str(caught.value)


def test_an_extension_named_by_its_package_is_not_refused() -> None:
    """``"uuid-ossp"`` is the extension's own name: nothing confiture generates writes it."""
    new = f'{_PLAIN}CREATE EXTENSION IF NOT EXISTS "uuid-ossp";\n'

    assert diff(_PLAIN, new).changes


def test_a_schema_of_bare_names_is_compared() -> None:
    new = f"{_PLAIN}CREATE TABLE app.u (id int, user_name text);\n"

    assert [type(c).__name__ for c in diff(_PLAIN, new).changes] == ["TableAdded"]


def test_migrate_diff_exits_5_with_the_code(tmp_path: Path) -> None:
    old, new = tmp_path / "old.sql", tmp_path / "new.sql"
    old.write_text(_PLAIN)
    new.write_text(f'{_PLAIN}CREATE TABLE app.u (id int, "Bad Col" int);\n')

    result = CliRunner().invoke(app, ["migrate", "diff", str(old), str(new), "--format", "json"])

    assert result.exit_code == 5
    assert json.loads(result.stdout)["error"]["code"] == "DIFFER_403"
