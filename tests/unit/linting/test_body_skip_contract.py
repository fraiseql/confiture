"""A rule that needs a database and has not got one says so, and is not a pass.

``body_001`` is the first rule that cannot answer from the files alone: it
materialises the DDL into a scratch database and asks ``plpgsql_check`` what the
bodies do. The extension is in no stock PostgreSQL — not CI's ``postgres:15``,
not the compose stack's ``postgres:16-alpine``, not this machine's 18 — so *not
running* is the common case, not the exceptional one, and it is built first for
that reason.

The contract that matters is what a run reports when it could not run: a
``skipped`` entry with a reason that says what to do, in the table and in the
JSON, and an exit code that does not call the run clean. A gate told to fail on
warnings, whose one selected rule is a warning rule that never executed, has not
established that there are no warnings.
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

#: A server nothing is listening on: reachable in configuration, not in fact.
_UNREACHABLE = "postgresql://127.0.0.1:1/confiture_no_such_server"

_BODY = """CREATE SCHEMA IF NOT EXISTS app;
CREATE TABLE app.tb_widget (pk_widget BIGINT PRIMARY KEY, name TEXT NOT NULL);
CREATE FUNCTION app.fn_widget_pk(p_name TEXT) RETURNS uuid
LANGUAGE plpgsql AS $$
DECLARE
    v_pk UUID;
BEGIN
    SELECT pk_widget INTO v_pk FROM app.tb_widget WHERE name = p_name;
    RETURN v_pk;
END;
$$;
"""


def _project(root: Path, *, database_url: str = _UNREACHABLE) -> None:
    (root / "db" / "schema").mkdir(parents=True, exist_ok=True)
    (root / "db" / "environments").mkdir(parents=True, exist_ok=True)
    (root / "db" / "environments" / "local.yaml").write_text(
        f"database_url: {database_url}\ninclude_dirs:\n  - path: db/schema\n"
    )
    (root / "db" / "schema" / "010_widget.sql").write_text(_BODY)


@pytest.fixture
def in_tmp(tmp_path: Path) -> Iterator[Path]:
    old = Path.cwd()
    os.chdir(tmp_path)
    try:
        yield tmp_path
    finally:
        os.chdir(old)


def _payload(*args: str) -> dict:
    result = runner.invoke(
        app, ["lint", "--format", "json", "--fail-on", "never", "--select", *args]
    )
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


def _skipped(payload: dict) -> dict[str, str]:
    return {status["code"]: status["reason"] for status in payload["skipped"]}


class TestASkippedRuleIsReported:
    """The server is configured — every environment config has one — and not answering."""

    def test_body_001_is_reported_as_skipped(self, in_tmp: Path) -> None:
        _project(in_tmp)

        assert "body_001" in _skipped(_payload("body_001"))

    def test_the_reason_says_what_happened_and_what_to_do(self, in_tmp: Path) -> None:
        _project(in_tmp)

        reason = _skipped(_payload("body_001"))["body_001"]

        assert "did not answer" in reason
        assert "--server-url" in reason

    def test_the_skip_reaches_the_table_too(self, in_tmp: Path) -> None:
        _project(in_tmp)

        result = runner.invoke(app, ["lint", "--select", "body_001", "--fail-on", "never"])

        assert result.exit_code == 0, result.output
        assert "body_001 did not run" in result.output

    def test_each_selected_body_rule_is_skipped_on_its_own(self, in_tmp: Path) -> None:
        """Two codes, two entries: a project may adopt one and not the other."""
        _project(in_tmp)

        assert sorted(_skipped(_payload("body"))) == ["body_001", "body_002"]

    def test_a_rule_nobody_selected_is_not_reported_as_skipped(self, in_tmp: Path) -> None:
        """A run that never asked for the body rules is not a run that lost them."""
        _project(in_tmp)

        assert _skipped(_payload("default")) == {}


class TestTheGateDoesNotReadASkipAsAPass:
    """#245's whole point: a body check that did not run has established nothing."""

    def test_fail_on_warning_does_not_report_success(self, in_tmp: Path) -> None:
        _project(in_tmp)

        result = runner.invoke(app, ["lint", "--select", "body_001", "--fail-on", "warning"])

        assert result.exit_code == 1, result.output

    def test_the_summary_says_which_rule_left_the_run_unclean(self, in_tmp: Path) -> None:
        """Exit 1 with no reason printed is a pipeline nobody can act on."""
        _project(in_tmp)

        result = runner.invoke(app, ["lint", "--select", "body_001", "--fail-on", "warning"])

        assert result.exit_code == 1
        assert "body_001 did not run" in result.output

    def test_a_threshold_above_the_skipped_rule_still_passes(self, in_tmp: Path) -> None:
        """``body_001`` is a warning: a gate that only fails on errors is unaffected."""
        _project(in_tmp)

        result = runner.invoke(app, ["lint", "--select", "body_001", "--fail-on", "error"])

        assert result.exit_code == 0, result.output

    def test_fail_on_never_stays_never(self, in_tmp: Path) -> None:
        """The one threshold that is a deliberate choice not to fail, skip or no skip."""
        _project(in_tmp)

        result = runner.invoke(app, ["lint", "--select", "body", "--fail-on", "never"])

        assert result.exit_code == 0, result.output


class TestTheCatalogueSaysARuleNeedsADatabase:
    """``--list-rules`` is where an operator finds out before the run, not after."""

    def test_the_json_catalogue_carries_requires_db(self) -> None:
        result = runner.invoke(app, ["lint", "--list-rules", "--format", "json"])

        assert result.exit_code == 0, result.output
        rules = {rule["code"]: rule for rule in json.loads(result.stdout)["rules"]}
        assert rules["body_001"]["requires_db"] is True
        assert rules["naming_001"]["requires_db"] is False

    def test_the_table_marks_it(self) -> None:
        result = runner.invoke(app, ["lint", "--list-rules"])

        assert result.exit_code == 0, result.output
        assert "body_001" in result.output
