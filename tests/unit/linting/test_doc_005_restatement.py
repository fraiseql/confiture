"""`doc_005`: a comment that says only what the object's name already says (#250).

The issue's own example — `COMMENT ON FUNCTION app.delete_widget(…) IS 'Deletes
a widget'` — satisfies `doc_002` and tells a reader nothing. The rule is
deliberately the narrowest mechanical band: every meaningful word of the comment
is already a word of the name. It is `info`, opt-in, and wrong sometimes, which
is what `--baseline` is for; the length bound the issue also offers is
**not implemented** (D8), because a short accurate comment is common and the
rule would punish it.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.linting.restatement import adds_nothing
from confiture.core.linting.rule_registry import LINT_RULES, default_codes, resolve_selection

runner = CliRunner()

_ISSUE = "Deletes a widget"
_INFORMATIVE = "Soft-deletes a widget and cascades to its variants, returning the affected count"


class TestHeuristic:
    def test_the_issues_own_comment_adds_nothing(self) -> None:
        assert adds_nothing(_ISSUE, "delete_widget") is True

    def test_a_comment_carrying_a_word_the_name_does_not_is_left_alone(self) -> None:
        assert adds_nothing(_INFORMATIVE, "delete_widget") is False

    def test_a_one_word_name_gives_the_comment_nothing_to_restate(self) -> None:
        assert adds_nothing("The widget table", "widget") is False

    def test_inflections_of_a_name_word_still_count_as_that_word(self) -> None:
        assert adds_nothing("Creating widgets", "create_widget") is True

    def test_articles_and_prepositions_do_not_save_a_restatement(self) -> None:
        assert adds_nothing("Gets the count of the widgets", "get_widget_count") is True

    def test_an_empty_comment_is_not_a_restatement(self) -> None:
        """An object with no comment is `doc_002`'s finding, not this one."""
        assert adds_nothing("   ", "delete_widget") is False


_SCHEMA = """CREATE SCHEMA IF NOT EXISTS app;
CREATE FUNCTION app.delete_widget(id uuid) RETURNS void LANGUAGE sql AS $$ SELECT 1 $$;
COMMENT ON FUNCTION app.delete_widget(uuid) IS 'Deletes a widget';
CREATE FUNCTION app.purge_widget(id uuid) RETURNS void LANGUAGE sql AS $$ SELECT 1 $$;
COMMENT ON FUNCTION app.purge_widget(uuid) IS
    'Soft-deletes a widget and cascades to its variants, returning the affected count';
"""


@pytest.fixture
def project(tmp_path: Path) -> Iterator[Path]:
    (tmp_path / "db" / "schema").mkdir(parents=True)
    (tmp_path / "db" / "environments").mkdir(parents=True)
    (tmp_path / "db" / "environments" / "local.yaml").write_text(
        "database_url: postgresql://localhost/test\ninclude_dirs:\n  - path: db/schema\n"
    )
    (tmp_path / "db" / "schema" / "010_objects.sql").write_text(_SCHEMA)
    old_cwd = Path.cwd()
    os.chdir(tmp_path)
    try:
        yield tmp_path
    finally:
        os.chdir(old_cwd)


def _items(*args: str) -> list[dict]:
    result = runner.invoke(app, ["lint", "--format", "json", "--fail-on", "never", *args])
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)["violations"]["items"]


class TestCli:
    def test_a_default_run_is_silent_about_it(self, project: Path) -> None:
        assert [v for v in _items() if v["rule_id"] == "doc_005"] == []

    def test_selecting_it_reports_the_restatement(self, project: Path) -> None:
        found = [v for v in _items("--select", "default,doc_005") if v["rule_id"] == "doc_005"]

        assert [v["location"] for v in found] == ["app.delete_widget(uuid)"]

    def test_the_finding_is_info_and_carries_its_location(self, project: Path) -> None:
        (found,) = [v for v in _items("--select", "doc_005") if v["rule_id"] == "doc_005"]

        assert (found["severity"], found["file"], found["line"]) == (
            "info",
            "db/schema/010_objects.sql",
            2,
        )

    def test_the_message_quotes_the_comment_it_is_about(self, project: Path) -> None:
        (found,) = [v for v in _items("--select", "doc_005") if v["rule_id"] == "doc_005"]

        assert _ISSUE in found["message"]


class TestRegistry:
    def test_it_is_an_opt_in_info_rule_in_the_doc_family(self) -> None:
        (rule,) = [r for r in LINT_RULES if r.code == "doc_005"]

        assert (rule.family, rule.severity, rule.default_on) == ("doc", "info", False)

    def test_a_plain_lint_does_not_select_it(self) -> None:
        assert "doc_005" not in default_codes()
        assert "doc_005" in resolve_selection(["doc"], [])


class TestTableRendering:
    def test_a_comment_in_brackets_survives_the_violations_table(self, project: Path) -> None:
        """Rich reads `[a]` in a cell as a style tag; the message is data, not markup."""
        (project / "db" / "schema" / "010_objects.sql").write_text(
            "CREATE SCHEMA IF NOT EXISTS app;\n"
            "CREATE FUNCTION app.delete_widget(id uuid) RETURNS void "
            "LANGUAGE sql AS $$ SELECT 1 $$;\n"
            "COMMENT ON FUNCTION app.delete_widget(uuid) IS 'Deletes [a] widget';\n"
        )

        result = runner.invoke(app, ["lint", "--select", "doc_005", "--fail-on", "never"])

        assert "[a]" in result.output
